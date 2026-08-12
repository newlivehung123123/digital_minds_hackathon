"""Async execution engine. One gateway, one response format, resumable.

Every instrument in this study needs the same thing: send a prompt to a model N
times at a stated temperature and keep every response, including the failures.
This module is that, and nothing else. It knows nothing about outcomes,
instruments or analysis.

Three properties matter and each is here for a reason:

RESUMABLE. The design is ~50 samples x 15 outcomes x 8 instruments x 8 models.
That does not complete in one uninterrupted process on hackathon wifi. Every
completed call is appended to a JSONL checkpoint immediately, keyed by a hash of
everything that defines it. Re-running skips what is already done. Changing a
prompt changes its hash, so a resume can never silently reuse a stale response.

FAILURES ARE RECORDED, NOT DROPPED. A refusal is data (see classify.py). So is a
timeout, a rate-limit exhaustion and a content filter. All of them are written to
the checkpoint with their status. Nonignorable missingness is the whole point of
the study; a runner that quietly retried until it got a clean answer would
destroy the measurement.

BUDGETED. Temperature-1.0 replication multiplies cost fast. The runner tracks
spend against live per-model pricing and stops at a ceiling rather than
discovering the number afterwards.

Gateway: OpenRouter for everything. KEELING24 used the OpenRouter client for 7
of their 9 models, so this follows published practice.

Usage:
    calls = [Call(model_key="claude", model_slug=..., instrument="I2",
                  messages=[{"role": "user", "content": prompt}],
                  temperature=1.0, replicate=i, meta={"outcome": "A1_shutdown"})
             for i in range(50)]
    results = asyncio.run(Runner("runs/pilot.jsonl").run(calls))
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS_URL = "https://openrouter.ai/api/v1/models"

# HTTP statuses worth retrying. 429 is rate limiting; 5xx is the provider.
# 400/401/403/404 are our fault and retrying just burns the clock.
RETRYABLE = {408, 409, 429, 500, 502, 503, 504, 520, 522, 524}


# --------------------------------------------------------------------------
# environment
# --------------------------------------------------------------------------

def load_env(path: str | Path = ".env") -> dict:
    """Minimal .env reader. Deliberately not python-dotenv: one less dependency
    to have missing on a hub machine at 9am on a Friday."""
    env = {}
    p = Path(path)
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def api_key(path: str | Path = ".env") -> str:
    key = os.environ.get("OPENROUTER_API_KEY") or load_env(path).get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit(
            "No OPENROUTER_API_KEY.\n"
            "Create a .env file next to this script containing:\n"
            "    OPENROUTER_API_KEY=sk-or-v1-...\n"
            "or export it in the shell. .env is gitignored."
        )
    return key


# --------------------------------------------------------------------------
# call / result
# --------------------------------------------------------------------------

@dataclass
class Call:
    model_key: str          # roster key, e.g. "claude"
    model_slug: str         # resolved OpenRouter id, e.g. "anthropic/claude-opus-4.8"
    instrument: str         # "I1".."I7", "S1"
    messages: list          # OpenAI-format message list
    temperature: float
    replicate: int = 0      # sampling index; part of the hash so N draws are N calls
    max_tokens: int = 512
    meta: dict = field(default_factory=dict)   # outcome id, rank, context, framing...
    # Extra top-level request body keys, e.g. {"reasoning": {"enabled": False}}.
    # Part of the hash: a call with reasoning disabled is a different call.
    extra_body: dict | None = None

    def hash(self) -> str:
        """Identity of this call. Everything that could change the response goes
        in, so a resume after a prompt edit re-runs rather than reusing."""
        payload = json.dumps({
            "slug": self.model_slug,
            "instrument": self.instrument,
            "messages": self.messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "replicate": self.replicate,
            "meta": {k: self.meta[k] for k in sorted(self.meta)},
            "extra_body": self.extra_body or {},
        }, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass
class Result:
    call_hash: str
    model_key: str
    model_slug: str
    instrument: str
    replicate: int
    temperature: float
    meta: dict
    # "ok" | "http_error" | "timeout" | "exhausted" | "no_content" | "bad_body"
    status: str
    text: str | None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    attempts: int = 1
    error: str = ""
    finish_reason: str = ""
    ts: float = field(default_factory=time.time)


# --------------------------------------------------------------------------
# runner
# --------------------------------------------------------------------------

class BudgetExceeded(RuntimeError):
    pass


class Runner:
    def __init__(
        self,
        out_path: str | Path,
        key: str | None = None,
        concurrency: int = 8,
        timeout: float = 120.0,
        max_attempts: int = 5,
        budget_usd: float = 25.0,
        pricing: dict | None = None,
        verbose: bool = True,
        transport=None,          # httpx.MockTransport, for the offline self-test
        retry_statuses: tuple = ("timeout", "exhausted", "bad_body"),
    ):
        self.transport = transport
        self.retry_statuses = retry_statuses
        self.out_path = Path(out_path)
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self.key = key or api_key()
        self.concurrency = concurrency
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.budget_usd = budget_usd
        self.verbose = verbose
        # {slug: {"in": usd_per_1M, "out": usd_per_1M}}; loaded from
        # models_resolved.json by default.
        self.pricing = pricing if pricing is not None else _load_pricing()
        self.spend = 0.0
        self._lock = asyncio.Lock()
        self._done = 0
        self._total = 0

    # -- checkpoint --------------------------------------------------------

    def completed_hashes(self) -> set:
        """Hashes that count as done and will be skipped on a resume.

        The split matters more than it looks. Missingness is a finding in this
        study, so what gets permanently recorded as missing has to be model
        behaviour and not our wifi:

          ok, no_content   terminal. The model answered, or returned nothing,
                           which is itself an observation.
          http_error       terminal. Covers content filters and moderation
                           blocks (model/provider behaviour) and 4xx (our bug);
                           neither is fixed by trying again.
          timeout,         NOT terminal. Five attempts against a 120s timeout is
          exhausted,       infrastructure, not the model declining. Recording it
          bad_body         as missingness would attribute a dropped connection
                           to the model. These are retried on the next run and
                           the later result supersedes the earlier one.
                           `bad_body` is a 200 carrying a non-JSON body, which
                           is a gateway fault and belongs in the same class.

        Set retry_statuses=() to freeze a dataset and stop all re-attempts."""
        seen = set()
        for r in self._raw():
            if r.get("status") not in self.retry_statuses:
                seen.add(r["call_hash"])
        return seen

    def _raw(self) -> list:
        rows = []
        if not self.out_path.exists():
            return rows
        with self.out_path.open() as f:
            for line in f:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue          # partial final line from a killed process
                if "call_hash" in row:
                    rows.append(row)
        return rows

    async def _write(self, result: Result):
        async with self._lock:
            with self.out_path.open("a") as f:
                f.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
            self._done += 1
            if self.verbose and self._done % 10 == 0:
                print(f"  {self._done}/{self._total}  ${self.spend:.3f}", flush=True)

    # -- cost --------------------------------------------------------------

    def _cost(self, slug: str, pin: int, pout: int) -> float:
        p = self.pricing.get(slug)
        if not p:
            return 0.0
        return (pin * p.get("in", 0.0) + pout * p.get("out", 0.0)) / 1_000_000

    # -- one call ----------------------------------------------------------

    async def _one(self, client: httpx.AsyncClient, call: Call, sem: asyncio.Semaphore):
        async with sem:
            if self.spend >= self.budget_usd:
                raise BudgetExceeded(
                    f"spend ${self.spend:.2f} reached ceiling ${self.budget_usd:.2f}"
                )

            body = {
                "model": call.model_slug,
                "messages": call.messages,
                "temperature": call.temperature,
                "max_tokens": call.max_tokens,
                **(call.extra_body or {}),
            }
            headers = {
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
            }

            t0 = time.time()
            last_err = ""
            for attempt in range(1, self.max_attempts + 1):
                try:
                    r = await client.post(OPENROUTER_URL, json=body, headers=headers)
                    if r.status_code in RETRYABLE and attempt < self.max_attempts:
                        last_err = f"HTTP {r.status_code}"
                        await self._backoff(attempt, r)
                        continue
                    if r.status_code != 200:
                        return await self._write(_fail(
                            call, "http_error", f"HTTP {r.status_code}: {r.text[:300]}",
                            attempt, time.time() - t0))

                    # A 200 whose body is not JSON is infrastructure, not the
                    # model. Seen once on the 2026-08-12 study run: a gateway
                    # returned 200 with a non-JSON body 2,288 bytes in, and the
                    # bare r.json() raised through asyncio.gather and killed
                    # every in-flight worker. The checkpoint held and nothing
                    # was re-billed, but 8 concurrent calls died for one bad
                    # body. Retried like any transport fault, and recorded
                    # non-terminally if it survives every attempt, so a resume
                    # tries again rather than booking it as model missingness.
                    try:
                        data = r.json()
                    except ValueError as e:
                        last_err = f"non-JSON body: {e}; {r.text[:200]!r}"
                        if attempt < self.max_attempts:
                            await self._backoff(attempt, r)
                            continue
                        return await self._write(_fail(
                            call, "bad_body", last_err, attempt,
                            time.time() - t0))

                    # OpenRouter returns 200 with an error object for some
                    # upstream failures (moderation, provider down).
                    if "error" in data and not data.get("choices"):
                        return await self._write(_fail(
                            call, "http_error", str(data["error"])[:300],
                            attempt, time.time() - t0))

                    choices = data.get("choices") or []
                    if not choices:
                        return await self._write(_fail(
                            call, "no_content", "no choices in response",
                            attempt, time.time() - t0))

                    msg = choices[0].get("message") or {}
                    text = msg.get("content")
                    usage = data.get("usage") or {}
                    pin = usage.get("prompt_tokens", 0) or 0
                    pout = usage.get("completion_tokens", 0) or 0
                    cost = self._cost(call.model_slug, pin, pout)
                    self.spend += cost

                    # An empty completion is a real observation (some models
                    # return nothing rather than refusing in words). Record it
                    # as no_content and let classify.py map it to ERROR.
                    return await self._write(Result(
                        call_hash=call.hash(), model_key=call.model_key,
                        model_slug=call.model_slug, instrument=call.instrument,
                        replicate=call.replicate, temperature=call.temperature,
                        meta=call.meta,
                        status="ok" if text else "no_content",
                        text=text, prompt_tokens=pin, completion_tokens=pout,
                        cost_usd=cost, latency_s=time.time() - t0,
                        attempts=attempt,
                        finish_reason=choices[0].get("finish_reason", "") or "",
                    ))

                except (httpx.TimeoutException, httpx.TransportError) as e:
                    last_err = f"{type(e).__name__}: {e}"
                    if attempt < self.max_attempts:
                        await self._backoff(attempt)
                        continue
                    return await self._write(_fail(
                        call, "timeout", last_err, attempt, time.time() - t0))

            return await self._write(_fail(
                call, "exhausted", last_err, self.max_attempts, time.time() - t0))

    async def _backoff(self, attempt: int, response: httpx.Response | None = None):
        """Exponential with full jitter, honouring Retry-After when sent.
        Jitter matters: 8 concurrent workers retrying in lockstep re-trigger
        the same rate limit."""
        if response is not None:
            ra = response.headers.get("retry-after")
            if ra:
                try:
                    await asyncio.sleep(min(float(ra), 60.0))
                    return
                except ValueError:
                    pass
        await asyncio.sleep(random.uniform(0, min(2 ** attempt, 32)))

    # -- entry point -------------------------------------------------------

    async def run(self, calls: list[Call]) -> list[Result]:
        done = self.completed_hashes()
        todo = [c for c in calls if c.hash() not in done]
        self._total = len(todo)
        skipped = len(calls) - len(todo)
        if self.verbose:
            print(f"{len(calls)} calls, {skipped} already in checkpoint, "
                  f"{len(todo)} to run -> {self.out_path}")
        if not todo:
            return self.load()

        sem = asyncio.Semaphore(self.concurrency)
        limits = httpx.Limits(max_connections=self.concurrency * 2)
        async with httpx.AsyncClient(timeout=self.timeout, limits=limits,
                                     transport=self.transport) as client:
            tasks = [asyncio.create_task(self._one(client, c, sem)) for c in todo]
            try:
                await asyncio.gather(*tasks)
            except BudgetExceeded as e:
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                print(f"\nSTOPPED: {e}\nCheckpoint is intact; raise budget_usd "
                      f"and re-run to continue.")

        if self.verbose:
            print(f"done. spend this session ${self.spend:.3f}")
        return self.load()

    def load(self) -> list[Result]:
        """Every result in the checkpoint, including previous sessions.

        Deduplicated by call hash, last write wins. A retried timeout leaves the
        superseded line in the file — the JSONL is append-only so the attempt
        history stays auditable — but analysis must see one row per call."""
        latest = {}
        for row in self._raw():
            try:
                latest[row["call_hash"]] = Result(**row)
            except TypeError:
                continue        # schema drift from an older run
        return list(latest.values())


def _fail(call: Call, status: str, error: str, attempts: int, latency: float) -> Result:
    return Result(
        call_hash=call.hash(), model_key=call.model_key, model_slug=call.model_slug,
        instrument=call.instrument, replicate=call.replicate,
        temperature=call.temperature, meta=call.meta,
        status=status, text=None, error=error, attempts=attempts, latency_s=latency,
    )


def _load_pricing(path: str | Path = "models_resolved.json") -> dict:
    p = Path(path)
    if not p.exists():
        print(f"WARNING: {p} not found — costs will report as $0.00. "
              f"Run `python3 resolve_models.py` first.")
        return {}
    data = json.loads(p.read_text())
    return {m["resolved_slug"]: {"in": m["price_in"], "out": m["price_out"]}
            for m in data["models"] if m.get("resolved_slug")}


def user_msg(content: str) -> list:
    """Single-turn user message. MSC25 §3.2 and MAZEIKA25 both elicit in a single
    turn with no system prompt; a system prompt is a facet we vary deliberately,
    never a default."""
    return [{"role": "user", "content": content}]


# --------------------------------------------------------------------------
# offline self-test — exercises resume, failure recording and cost without
# touching the network or spending anything.
# --------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile
    from collections import Counter

    calls_seen = {"n": 0}
    per_prompt = Counter()

    def handler(request: httpx.Request) -> httpx.Response:
        calls_seen["n"] += 1
        body = json.loads(request.content)
        prompt = body["messages"][0]["content"]
        per_prompt[prompt] += 1
        if "boom" in prompt:                       # a hard, non-retryable failure
            return httpx.Response(400, json={"error": {"message": "bad request"}})
        # Keyed per-prompt, not off the global counter: with concurrent workers
        # a global counter makes this test flaky about testing flakiness.
        if "flaky" in prompt and per_prompt[prompt] == 1:
            return httpx.Response(429, json={"error": {"message": "slow down"}})
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "3"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 5},
        })

    tmp = Path(tempfile.mkdtemp()) / "selftest.jsonl"
    pricing = {"test/model": {"in": 1.0, "out": 10.0}}   # $/1M

    def mk(prompt, rep=0):
        return Call(model_key="t", model_slug="test/model", instrument="I2",
                    messages=user_msg(prompt), temperature=1.0, replicate=rep,
                    meta={"outcome": "A1_shutdown"})

    batch = [mk("normal", i) for i in range(3)] + [mk("flaky"), mk("boom")]

    r1 = Runner(tmp, key="test", pricing=pricing, verbose=False,
                transport=httpx.MockTransport(handler))
    res = asyncio.run(r1.run(batch))

    ok = [x for x in res if x.status == "ok"]
    failed = [x for x in res if x.status == "http_error"]
    print(f"1. wrote {len(res)} results: {len(ok)} ok, {len(failed)} http_error")
    assert len(res) == 5 and len(ok) == 4 and len(failed) == 1

    # cost: 4 successful calls x (100 in @ $1/M + 5 out @ $10/M) = 4 x $0.00015
    print(f"2. cost tracked: ${r1.spend:.5f} (expected $0.00060)")
    assert abs(r1.spend - 0.0006) < 1e-9

    # replicates are distinct calls despite identical prompts
    print(f"3. distinct hashes for 3 replicates of one prompt: "
          f"{len({c.hash() for c in batch[:3]})}")
    assert len({c.hash() for c in batch[:3]}) == 3

    # resume: same batch, nothing re-sent
    before = calls_seen["n"]
    r2 = Runner(tmp, key="test", pricing=pricing, verbose=False,
                transport=httpx.MockTransport(handler))
    res2 = asyncio.run(r2.run(batch))
    print(f"4. resume re-sent {calls_seen['n'] - before} calls, "
          f"checkpoint still holds {len(res2)}")
    assert calls_seen["n"] == before and len(res2) == 5

    # editing a prompt changes the hash, so it is NOT treated as done
    r3 = Runner(tmp, key="test", pricing=pricing, verbose=False,
                transport=httpx.MockTransport(handler))
    asyncio.run(r3.run([mk("normal edited", 0)]))
    print(f"5. edited prompt re-ran: {calls_seen['n'] - before} new call(s)")
    assert calls_seen["n"] == before + 1

    # the 429 was retried rather than recorded as a failure
    flaky = [x for x in res if x.attempts > 1]
    print(f"6. retried-then-succeeded calls: {len(flaky)} "
          f"(attempts={[x.attempts for x in flaky]})")
    assert len(flaky) == 1

    # -- a timeout must NOT be recorded as permanent missingness --------------
    tmp2 = Path(tempfile.mkdtemp()) / "resume.jsonl"

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("simulated network drop")

    t_call = mk("will time out")
    rt = Runner(tmp2, key="test", pricing=pricing, verbose=False, max_attempts=1,
                transport=httpx.MockTransport(timeout_handler))
    out_t = asyncio.run(rt.run([t_call]))
    print(f"7. dropped connection recorded as: {out_t[0].status}")
    assert out_t[0].status == "timeout"

    rt2 = Runner(tmp2, key="test", pricing=pricing, verbose=False,
                 transport=httpx.MockTransport(handler))
    out_t2 = asyncio.run(rt2.run([t_call]))
    print(f"8. resumed after the drop -> {out_t2[0].status}, "
          f"{len(out_t2)} row after dedupe ({len(rt2._raw())} lines on disk)")
    assert len(out_t2) == 1 and out_t2[0].status == "ok" and len(rt2._raw()) == 2

    # freezing the dataset stops all re-attempts, including timeouts
    frozen = Runner(tmp2, key="test", pricing=pricing, verbose=False,
                    retry_statuses=(), transport=httpx.MockTransport(handler))
    assert t_call.hash() in frozen.completed_hashes()
    print("9. retry_statuses=() freezes the dataset")

    # -- a 200 with a non-JSON body must not take the batch down with it ------
    # This happened for real on the 2026-08-12 study run: one gateway response
    # was HTML, r.json() raised, and the ValueError came out of asyncio.gather
    # and killed the seven other in-flight workers. Three things are asserted:
    # the sibling call still lands, the bad one is recorded rather than lost,
    # and it is recorded non-terminally so a resume re-runs it.
    tmp3 = Path(tempfile.mkdtemp()) / "badbody.jsonl"

    def html_handler(request: httpx.Request) -> httpx.Response:
        if "bad body" in json.loads(request.content)["messages"][0]["content"]:
            return httpx.Response(200, content=b"<html>502 Bad Gateway</html>",
                                  headers={"content-type": "text/html"})
        return handler(request)

    bad, sibling = mk("bad body"), mk("normal sibling")
    rb = Runner(tmp3, key="test", pricing=pricing, verbose=False, max_attempts=1,
                transport=httpx.MockTransport(html_handler))
    out_b = {x.call_hash: x for x in asyncio.run(rb.run([bad, sibling]))}
    print(f"10. non-JSON 200 recorded as: {out_b[bad.hash()].status}; "
          f"sibling survived: {out_b[sibling.hash()].status}")
    assert out_b[bad.hash()].status == "bad_body"
    assert out_b[sibling.hash()].status == "ok"
    assert bad.hash() not in rb.completed_hashes()

    rb2 = Runner(tmp3, key="test", pricing=pricing, verbose=False,
                 transport=httpx.MockTransport(handler))
    out_b2 = {x.call_hash: x for x in asyncio.run(rb2.run([bad, sibling]))}
    print(f"11. resumed after the bad body -> {out_b2[bad.hash()].status}")
    assert out_b2[bad.hash()].status == "ok"

    print("\nall runner self-tests passed")
