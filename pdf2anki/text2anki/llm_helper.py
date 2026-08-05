import os
import time
import random
import requests
import json
import getpass
from dotenv import load_dotenv
from .console_utils import safe_print, is_verbose, verbose_print
from .forensic_logger import log_event
# Shared OpenRouter transport chokepoint. requests' `timeout=` alone cannot
# bound a chat call: it is a per-socket-read *inactivity* timeout, and
# OpenRouter keeps non-streamed connections warm with whitespace keep-alives
# every ~0.4s, so a stuck generation would block forever. _http_post upgrades
# chat calls to SSE streaming with idle/wall/completion-size guards and still
# returns an eager Response (.raise_for_status()/.json() unchanged); it also
# reuses a per-process Session instead of paying a TLS handshake per call.
# Tests mock the transport by patching `pdf2anki.text2anki.llm_helper._http_post`.
from ..openrouter_transport import _http_post, OpenRouterStreamError

load_dotenv()

# --- Retry policy for transient upstream failures ---------------------------
#
# Observed in production (and reproducibly in test_dedup): OpenRouter relays
# upstream rate limits as code=429 -- sometimes as an HTTP status, sometimes
# (with SSE) as a mid-stream error event after the 200 was already committed.
# Without a retry, one transient 429 turns a whole call into None, which e.g.
# silently converts a dedup voting pass into "no duplicates found".
#
# Scope decisions (deliberate, keep in sync with the tests in
# tests/test_llm_helper_retry.py):
#  * The retry lives HERE, not in the transport: pic2text already has its own
#    per-page attempt loop (max_page_attempts, pause/resume state); stacking a
#    second retry underneath it would multiply waits and blur page status.
#    llm_helper had no retry layer at all -- this is it.
#  * Retryable: 429 plus the transient 5xx trio (500/502/503), whether they
#    arrive as an HTTP status (pre-generation, nothing billed yet) or as an
#    OpenRouterStreamError code (mid-stream; only the fragment up to the error
#    was billed, and text2anki calls cost micro-cents -- the lost dedup pass
#    is worth more than the duplicate fragment cost).
#  * NOT retryable: other 4xx (deterministic: bad request/auth/quota),
#    OpenRouterStreamError with code=None (premature EOF -- that is
#    truncation, not throttling), Timeout (the idle/wall guards exist to make
#    stuck generations loud; auto-repeating a call that just burned minutes
#    hides that signal), and ConnectionError (usually "network gone" -- a
#    backoff would only delay the user-facing failure; revisit if measured
#    otherwise).
#  * Profile: 2 attempts after the first (total 3), delays 2s then 8s with
#    +/-25% jitter. Bounded well under the transport's own guards, loud via
#    safe_print WARNING + forensic log_event so a *persistent* rate limit is
#    visible instead of silently absorbed.
#
# Known limitation -- no circuit breaker. Each call retries independently, so
# a *persistent* rate limit costs up to 12.5s (2s + 8s, both jittered up) per
# call before it gives up, where it used to fail instantly. Accepted at the
# current call volume: a dedup run makes single-digit calls, and the WARNING
# lines make the cause obvious rather than looking like a hang. It stops being
# acceptable once a single workflow issues calls in bulk -- N calls against a
# rate limit that is not going away means N x 12.5s of pure waiting. The fix
# then is a shared breaker: after K consecutive exhausted retries, stop
# retrying for the rest of the run and fail fast.
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503}
_RETRY_DELAYS_SECONDS = (2.0, 8.0)


def _retryable_code(exc):
    """Upstream status code if `exc` is a retryable transient failure, else None."""
    if isinstance(exc, OpenRouterStreamError):
        return exc.code if exc.code in _RETRYABLE_STATUS_CODES else None
    if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
        sc = exc.response.status_code
        return sc if sc in _RETRYABLE_STATUS_CODES else None
    return None


def _post_chat_with_retry(caller, **kwargs):
    """_http_post + raise_for_status, with bounded backoff on transient errors.

    Returns a Response whose status has already been checked. Non-retryable
    failures and exhausted retries re-raise into the callers' existing
    RequestException handlers (-> None, logged), unchanged.
    """
    delays = _RETRY_DELAYS_SECONDS + (None,)  # None marks the last attempt
    for attempt, delay in enumerate(delays, start=1):
        try:
            response = _http_post(**kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            code = _retryable_code(e)
            if code is None or delay is None:
                raise
            sleep_s = delay * random.uniform(0.75, 1.25)
            safe_print(
                f"Transienter Upstream-Fehler (HTTP {code}), "
                f"Versuch {attempt}/{len(delays)} fehlgeschlagen -- "
                f"neuer Versuch in {sleep_s:.1f}s...", "WARNING")
            log_event("llm_retry", {
                "caller": caller,
                "code": code,
                "attempt": attempt,
                "delay_s": round(sleep_s, 2),
                "error": str(e)[:300],
            })
            time.sleep(sleep_s)


# --- NEUE, ROBUSTE SESSION-VERWALTUNG ---
# Speichert die vollständigen JSON-Antworten jedes API-Aufrufs in der Session.
_session_responses = []
API_KEY = None

def reset_llm_session():
    """Setzt die Liste der gesammelten LLM-Antworten für die aktuelle Session zurück."""
    global _session_responses
    _session_responses = []

def get_session_responses():
    """Gibt eine Kopie aller gesammelten LLM-Antworten für diese Session zurück."""
    return _session_responses.copy()

def _initialize_api_key():
    """Initialisiert den OpenRouter API-Key sicher, falls noch nicht geschehen."""
    global API_KEY
    if API_KEY:
        return True

    API_KEY = os.getenv("OPENROUTER_API_KEY")
    if API_KEY:
        safe_print("🔑 OpenRouter API Key aus Umgebungsvariable geladen.", "SUCCESS")
        return True

    safe_print("OpenRouter API Key nicht in Umgebungsvariablen gefunden.", "WARNING")
    safe_print("Bitte geben Sie Ihren OpenRouter API Key ein. Er wird nicht gespeichert, nur für diese Session verwendet.", "INFO")
    try:
        API_KEY = getpass.getpass("API Key: ")
        if not API_KEY:
            safe_print("Kein API-Key angegeben. LLM-Funktionen deaktiviert.", "ERROR")
            return False
        safe_print("🔑 API Key für diese Session gespeichert.", "SUCCESS")
        return True
    except Exception as e:
        safe_print(f"Fehler bei der Eingabe des API-Keys: {e}", "ERROR")
        return False

def get_llm_decision(header_context, prompt_body, model="google/gemini-2.5-flash",
                     json_mode=False, system_message=None):
    """
    Führt einen API-Aufruf an OpenRouter durch, sammelt die volle Antwort und gibt die Entscheidung zurück.

    Args:
        json_mode: If True, sets response_format=json_object so the model is
                   forced to produce valid JSON (proper escaping of backslashes etc.).
        system_message: Optional stable system message (enables provider-side prompt caching
                        when the same prefix is reused across calls).
    """
    if not API_KEY and not _initialize_api_key():
        return None

    full_prompt = f"{header_context}\n\n---\n\n{prompt_body}" if header_context else prompt_body

    messages = []
    if system_message:
        messages.append({"role": "system", "content": system_message})
    messages.append({"role": "user", "content": full_prompt})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "usage": {
            "include": True
        },
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    log_event("llm_request", {
        "caller": "get_llm_decision",
        "model": model,
        "json_mode": json_mode,
        "prompt_length": len(full_prompt),
        "prompt": full_prompt,
    })

    try:
        # timeout=60 only guards connect time and total socket silence; the
        # transport's SSE idle/wall guards bound the generation itself.
        # _post_chat_with_retry adds bounded backoff on transient 429/5xx and
        # has already called raise_for_status on the returned response.
        response = _post_chat_with_retry(
            "get_llm_decision",
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={ "Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json" },
            data=json.dumps(payload),
            timeout=60
        )
        response_data = response.json()

        _session_responses.append(response_data)
        log_event("llm_response", {
            "caller": "get_llm_decision",
            "response": response_data,
        })

        if is_verbose():
            safe_print("--- Full OpenRouter API Response ---", "INFO")
            safe_print(json.dumps(response_data, indent=2, ensure_ascii=False))
            safe_print("------------------------------------", "INFO")

        usage = response_data.get('usage', {})
        cost = usage.get('cost', 0.0)
        cached_tokens = usage.get('prompt_tokens_details', {}).get('cached_tokens', 0)
        safe_print(f"LLM call successful. Cost: ${cost:.8f} (Cached: {cached_tokens} tokens)", "INFO")
        verbose_print(f"  Prompt: {len(full_prompt)} chars, model={model}, json_mode={json_mode}")

        return response_data['choices'][0]['message']['content'].strip()

    except requests.exceptions.RequestException as e:
        safe_print(f"API-Anfrage fehlgeschlagen: {e}", "ERROR")
        _session_responses.append({"error": str(e)})
        log_event("llm_error", {"caller": "get_llm_decision", "error": str(e)})
        return None
    except (KeyError, IndexError) as e:
        safe_print(f"Unerwartete API-Antwortstruktur: {e}", "ERROR")
        _session_responses.append({"error": f"Invalid response structure: {e}"})
        log_event("llm_error", {"caller": "get_llm_decision", "error": str(e)})
        return None


def get_llm_conversation_turn(
    conversation_history: list,
    new_user_message: str,
    model: str = "google/gemini-2.5-flash",
) -> str | None:
    """
    Send one turn in a multi-turn conversation and return the assistant reply.

    conversation_history is mutated in-place: the new user message and the
    assistant reply are both appended so the caller can continue the loop.
    Returns the reply text, or None on any failure.
    """
    if not API_KEY and not _initialize_api_key():
        return None

    conversation_history.append({"role": "user", "content": new_user_message})

    log_event("llm_request", {
        "caller": "get_llm_conversation_turn",
        "model": model,
        "turn": len(conversation_history),
        "message_length": len(new_user_message),
        "message": new_user_message,
    })

    try:
        # Same transport routing, retry policy and rationale as in
        # get_llm_decision above; raise_for_status happens inside the helper.
        response = _post_chat_with_retry(
            "get_llm_conversation_turn",
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            data=json.dumps({
                "model": model,
                "messages": conversation_history,
                "temperature": 0.1,
                "usage": {"include": True},
            }),
            timeout=60,
        )
        response_data = response.json()

        _session_responses.append(response_data)
        log_event("llm_response", {
            "caller": "get_llm_conversation_turn",
            "response": response_data,
        })

        content = response_data["choices"][0]["message"]["content"].strip()
        conversation_history.append({"role": "assistant", "content": content})

        usage = response_data.get("usage", {})
        cost = usage.get("cost", 0.0)
        safe_print(f"LLM turn successful. Cost: ${cost:.8f}", "INFO")
        verbose_print(f"  Turn {len(conversation_history)}, model={model}")

        return content

    except requests.exceptions.RequestException as e:
        safe_print(f"API-Anfrage fehlgeschlagen: {e}", "ERROR")
        _session_responses.append({"error": str(e)})
        log_event("llm_error", {"caller": "get_llm_conversation_turn", "error": str(e)})
        conversation_history.pop()  # remove the user message we appended
        return None
    except (KeyError, IndexError) as e:
        safe_print(f"Unerwartete API-Antwortstruktur: {e}", "ERROR")
        _session_responses.append({"error": f"Invalid response structure: {e}"})
        log_event("llm_error", {"caller": "get_llm_conversation_turn", "error": str(e)})
        conversation_history.pop()
        return None