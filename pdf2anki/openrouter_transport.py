"""Shared OpenRouter HTTP transport -- the single chokepoint for chat calls.

Moved verbatim out of pic2text.py (history: commits b5f1985 and a6df397) so
that every subsystem talking to OpenRouter -- OCR/judge calls in pic2text and
the card-generation/decision calls in text2anki.llm_helper -- is bounded by
the same transport guards. The core problem this solves: requests' `timeout=`
is a per-socket-read *inactivity* timeout, and OpenRouter keeps non-streamed
connections warm with a whitespace keep-alive line (b'\\n         \\n') every
~0.4s (measured live), so that timeout can never fire and a stuck generation
blocks its thread forever. `_http_post` upgrades chat-completion calls to SSE
streaming, where token deltas are a real progress signal, and enforces the
graded guards documented in the constants block at the bottom.

Callers keep sending a plain payload and keep receiving an ordinary eager
`requests.Response` whose .json() looks like a non-streamed chat.completion.

Patch seams for tests:
  * `pdf2anki.pic2text._http_post` and `pdf2anki.text2anki.llm_helper._http_post`
    (the importing modules' bindings) -- mock the whole transport.
  * `pdf2anki.openrouter_transport._get_session` and the HTTP_* constants in
    THIS module -- exercise the real transport against a fake session. The
    constants are deliberately not re-exported by value anywhere: patching a
    stale copy would silently do nothing, so consumers must patch them here.
"""

import os
import json
import time
import threading
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

# Per-process requests.Session cache. OpenRouter does not rate-limit paid
# models, but each call without a Session pays a fresh TLS handshake and
# urllib3's default pool would silently throttle past ~10 concurrent sockets.
# Keying by os.getpid() makes this fork-safe (Linux) and is a harmless no-op
# under spawn (Windows / ProcessPoolExecutor) where child modules re-import.
_session_lock = threading.Lock()
_session_by_pid: Dict[int, requests.Session] = {}


def _get_session() -> requests.Session:
    pid = os.getpid()
    s = _session_by_pid.get(pid)
    if s is not None:
        return s
    with _session_lock:
        s = _session_by_pid.get(pid)
        if s is not None:
            return s
        s = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=8,
            pool_maxsize=64,
        )
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        _session_by_pid[pid] = s
        return s


class OpenRouterStreamError(requests.exceptions.RequestException):
    """An error event arrived inside an SSE stream, after HTTP 200 was sent.

    Streaming moves upstream failures past the status line: OpenRouter commits
    to 200 as soon as it starts relaying, so a provider error mid-generation
    arrives as a `data: {"error": ...}` event instead of an HTTP status code.
    Subclassing RequestException keeps the callers' existing
    `except requests.exceptions.RequestException` handlers working unchanged.

    `code` carries the upstream error code machine-readably (e.g. 429 for
    "temporarily rate-limited upstream", observed in production). Today
    nothing branches on it -- but a future retry-on-429 must not have to
    parse it back out of a message text that is truncated at 300 chars.
    None when the event carried no code (or none applies, as for the
    premature-EOF case).
    """

    def __init__(self, *args, code=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.code = code


def _read_body_eager(response) -> None:
    """Read a non-SSE body under the wall clock and restore the eager-Response
    contract (.raise_for_status(), .json()) by handing requests the pre-read
    body -- the same attribute requests itself fills on the stream=False path,
    where Session.send simply touches r.content.

    Under urllib3 2.x, iter_content yields once per received transfer chunk
    rather than per chunk_size, so even a keep-alive dribble re-arms the
    deadline check every ~0.4s. Should the connection instead fall completely
    silent, the caller-supplied per-read timeout still fires -- surfacing as a
    ConnectionError wrapping ReadTimeoutError, which the callers'
    RequestException handlers catch.
    """
    deadline = time.monotonic() + HTTP_WALL_TIMEOUT_SECONDS
    chunks: List[bytes] = []
    for chunk in response.iter_content(chunk_size=8192):
        chunks.append(chunk)
        if time.monotonic() > deadline:
            raise requests.exceptions.Timeout(
                f"OpenRouter call exceeded the wall-clock limit of "
                f"{HTTP_WALL_TIMEOUT_SECONDS}s while reading a non-SSE body."
            )
    response._content = b"".join(chunks)
    response._content_consumed = True


def _consume_sse_stream(response) -> Dict[str, Any]:
    """Consume an OpenRouter SSE chat stream into a non-streamed-shaped dict.

    Returns {"id", "object", "model", "choices": [{"message": {...},
    "finish_reason": ...}], "usage"?} so the callers' response parsing works
    identically for streamed and non-streamed transports.

    Guards, in order of expected relevance (see the constants block below for
    the rationale and the measured numbers behind each):
      * idle timeout -- no parsed data event for HTTP_STREAM_IDLE_TIMEOUT_SECONDS.
        Keep-alive comments and blank separator lines do NOT reset the clock;
        any parsed data event does (including reasoning deltas).
      * wall ceiling -- HTTP_WALL_TIMEOUT_SECONDS, absolute.
      * completion cap -- HTTP_MAX_COMPLETION_CHARS on accumulated content;
        trips the callers' existing finish_reason == "length" handling, but
        mid-flight, before the runaway finishes billing.
    Total socket silence (no lines at all) is covered by the caller-supplied
    per-read timeout, surfacing as a ConnectionError the callers already catch.

    Two post-conditions of the loop:
      * After [DONE] the result is complete and paid for, so nothing that
        happens while draining to EOF (timeout, transport failure) may
        discard it -- the connection is dropped instead of pooled, and the
        assembled result is returned.
      * A clean EOF before [DONE] with no finish_reason means the stream was
        cut short. The fragment is NOT returned: these pages go into
        documents where silently truncated text that reads as complete is
        strictly worse than a loud failed attempt, so the call fails into
        the callers' retry path instead.
    """
    now = time.monotonic()
    idle_deadline = now + HTTP_STREAM_IDLE_TIMEOUT_SECONDS
    wall_deadline = now + HTTP_WALL_TIMEOUT_SECONDS
    content_parts: List[str] = []
    content_len = 0
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    response_id: Optional[str] = None
    model_id: Optional[str] = None
    saw_done = False

    line_iter = response.iter_lines(chunk_size=1024)
    while True:
        try:
            raw_line = next(line_iter)
        except StopIteration:
            break
        except Exception:
            if saw_done:
                # The result is complete and paid for; a transport failure
                # while draining to EOF -- a silent socket tripping the
                # per-read timeout (ConnectionError), or an abortive close
                # without the chunked terminator (ChunkedEncodingError) --
                # must not discard it. Drop the connection, keep the result.
                response.close()
                break
            raise
        now = time.monotonic()
        if now > wall_deadline or now > idle_deadline:
            if saw_done:
                # Same principle: past [DONE] the deadlines only bound the
                # drain, not the generation. Keep the result, drop the
                # connection instead of pooling it half-read.
                response.close()
                break
            if now > wall_deadline:
                raise requests.exceptions.Timeout(
                    f"OpenRouter stream exceeded the wall-clock ceiling of "
                    f"{HTTP_WALL_TIMEOUT_SECONDS}s."
                )
            raise requests.exceptions.Timeout(
                f"OpenRouter stream produced no data event for "
                f"{HTTP_STREAM_IDLE_TIMEOUT_SECONDS}s (keep-alives only); "
                f"treating the generation as stuck."
            )
        if not raw_line or raw_line.startswith(b":"):
            # Blank event separator or ': OPENROUTER PROCESSING' comment:
            # proves the socket is alive, not that the model is producing.
            continue
        if not raw_line.startswith(b"data:"):
            continue  # other SSE fields (event:, id:) -- unused by OpenRouter
        data = raw_line[len(b"data:"):].strip()
        if data == b"[DONE]":
            # Deliberately no break: the server ends the response right after
            # [DONE], and draining to EOF lets urllib3 return the connection
            # to the pool instead of discarding it mid-read. The drain gets a
            # small budget of its own: past it, keeping the finished result
            # beats keeping the connection.
            saw_done = True
            idle_deadline = min(idle_deadline, now + 5.0)
            continue
        try:
            event = json.loads(data)
        except ValueError:
            continue  # tolerate one malformed line rather than kill the call
        if not isinstance(event, dict) or saw_done:
            continue
        if event.get("error"):
            err = event["error"] if isinstance(event["error"], dict) else {"message": str(event["error"])}
            raise OpenRouterStreamError(
                f"OpenRouter mid-stream error (HTTP status was already 200): "
                f"code={err.get('code')}, message={str(err.get('message'))[:300]}",
                code=err.get("code"),
            )
        idle_deadline = now + HTTP_STREAM_IDLE_TIMEOUT_SECONDS  # progress
        if event.get("usage") is not None:
            usage = event["usage"]
        if response_id is None:
            response_id = event.get("id")
            model_id = event.get("model")
        choices = event.get("choices")
        if not (isinstance(choices, list) and choices and isinstance(choices[0], dict)):
            continue  # e.g. a bare usage event
        if choices[0].get("finish_reason"):
            finish_reason = choices[0]["finish_reason"]
        delta = choices[0].get("delta")
        piece = delta.get("content") if isinstance(delta, dict) else None
        if piece:
            content_parts.append(piece)
            content_len += len(piece)
            if content_len > HTTP_MAX_COMPLETION_CHARS:
                # Runaway generation: stop paying for it now and let the
                # callers' finish_reason == "length" branch fail the attempt.
                # The half-read connection must not go back to the pool.
                finish_reason = "length"
                response.close()
                break

    if not saw_done and finish_reason is None:
        # Clean EOF before [DONE] with no finish_reason: the stream was cut
        # short. Returning the fragment would count a half page as a success
        # (and a half judge verdict as final); fail the attempt instead.
        raise OpenRouterStreamError(
            "OpenRouter stream ended prematurely: EOF before [DONE] and no "
            "finish_reason; discarding the partial completion."
        )
    result: Dict[str, Any] = {
        "id": response_id,
        "object": "chat.completion",
        "model": model_id,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "".join(content_parts)},
            "finish_reason": finish_reason,
        }],
    }
    if usage is not None:
        result["usage"] = usage
    return result


def _http_post(**kwargs):
    # Single chokepoint for OpenRouter HTTP calls. Production routes through
    # the per-process Session; tests patch the importing modules' bindings of
    # this name (pdf2anki.pic2text._http_post,
    # pdf2anki.text2anki.llm_helper._http_post) directly with side_effect.
    #
    # Chat-completion calls are upgraded to SSE streaming here, invisibly to
    # the callers: they keep sending a plain payload and keep receiving an
    # ordinary eager Response whose .json() looks like a non-streamed
    # chat.completion. Rationale and guard values: see the constants block
    # below (HTTP_STREAM_IDLE_TIMEOUT_SECONDS and friends). Anything that is
    # not a successfully negotiated event stream -- error statuses arrive as
    # application/json even for stream:true requests (verified live), and a
    # non-chat URL never asks for one -- takes the eager fallback path with
    # the wall-clock guard.
    url = kwargs.get("url", "")
    body = kwargs.get("data")
    wants_sse = False
    if isinstance(url, str) and url.rstrip("/").endswith("/chat/completions") and isinstance(body, str):
        try:
            payload = json.loads(body)
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            payload["stream"] = True
            # Without this flag the stream carries no usage block; the
            # finish_reason == "length" logging reads usage.completion_tokens.
            # Verified live: OpenRouter sends usage as the final data event.
            payload["stream_options"] = {"include_usage": True}
            kwargs = dict(kwargs)
            kwargs["data"] = json.dumps(payload)
            wants_sse = True

    response = _get_session().post(stream=True, **kwargs)
    try:
        content_type = (response.headers.get("Content-Type") or "").lower()
        if not wants_sse or response.status_code != 200 or "text/event-stream" not in content_type:
            _read_body_eager(response)
            return response
        response_data = _consume_sse_stream(response)
        # Restore the eager-Response contract the callers rely on
        # (.raise_for_status(), .json()) by handing requests the assembled
        # body -- the same attribute requests itself fills on the
        # stream=False path, where Session.send simply touches r.content.
        response._content = json.dumps(response_data).encode("utf-8")
        response._content_consumed = True
        return response
    except BaseException:
        # Deadline hit, mid-stream error, or transport failure: drop the
        # connection rather than returning a half-read socket to the pool.
        response.close()
        raise


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    """Integer knob from the environment, clamped below by `minimum`.

    load_dotenv() already ran above, so a project .env is picked up without
    further plumbing. Malformed values fall back to the default rather than
    aborting an OCR run over a typo.
    """
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


# Transport guards for a single OpenRouter call -- enforced inside _http_post,
# NOT by the `timeout=` the callers pass (that only bounds connect time and
# per-read socket *inactivity*).
#
# Chat-completion calls are streamed (SSE) at the transport layer. The reason
# is that non-streaming offers no progress signal: OpenRouter pads the silent
# generation phase with whitespace keep-alives (b'\n         \n' every ~0.4s,
# measured live), which reset the per-read inactivity timeout indefinitely --
# a stuck generation once blocked a worker thread forever, and the only
# possible defense was a blunt wall-clock ceiling that had to referee between
# "slow but healthy model" and "stuck model" without being able to tell them
# apart. In SSE mode token deltas ARE the progress signal, so three graded
# guards replace the single lossy wall value:
#
#  * HTTP_STREAM_IDLE_TIMEOUT_SECONDS -- the workhorse. Abort when no new SSE
#    data event has arrived for this long. Keep-alive comments
#    (': OPENROUTER PROCESSING') deliberately do NOT count as progress -- they
#    only say the socket is alive -- but ANY parsed data event does, including
#    role-only preambles and delta.reasoning: reasoning models stream thought
#    tokens for minutes while content stays empty (verified live), and an
#    idle clock keyed to content alone would kill them. 120s is ~85x the
#    observed time-to-first-token; a stuck generation now dies after 2
#    minutes, while a slow model that keeps producing deltas can never be
#    killed by it. Stall-detection is duration-independent, which is why the
#    same value serves both the OCR calls and the (shorter) text2anki
#    decision/card-generation calls.
#  * HTTP_WALL_TIMEOUT_SECONDS -- pure backstop, no longer the primary guard.
#    Caps a pathological producer that dribbles one delta every few seconds
#    indefinitely, and bounds the non-SSE fallback path (HTTP error bodies,
#    intermediaries that strip streaming). Raised from 300 to 1800 alongside
#    the semantics change: with the idle timeout refereeing stuck-vs-slow,
#    this value only needs to cap the absurd, and must sit safely above any
#    legitimate slow stream so it never re-creates the unhealable-page
#    failure mode (a guard below a model's honest per-page duration would
#    kill the page on every one of the max_page_attempts retries).
#  * HTTP_MAX_COMPLETION_CHARS -- in-flight version of the
#    finish_reason == "length" runaway check in pic2text (observed incident:
#    65k tokens / ~2MB of text for a ~200-token page, 150x normal cost).
#    Streaming lets us cut such a blob after ~10% of that instead of paying
#    for it to complete; the synthesized finish_reason == "length" routes the
#    attempt through the exact same retry path as the post-hoc check. 200k
#    chars is >10x a dense OCR page and far above any card-generation batch.
HTTP_STREAM_IDLE_TIMEOUT_SECONDS = _env_int("PDF2ANKI_HTTP_IDLE_TIMEOUT_S", 120)
HTTP_WALL_TIMEOUT_SECONDS = _env_int("PDF2ANKI_HTTP_WALL_TIMEOUT_S", 1800)
HTTP_MAX_COMPLETION_CHARS = _env_int("PDF2ANKI_HTTP_MAX_COMPLETION_CHARS", 200_000)
