import os
import requests
import json
import getpass
from dotenv import load_dotenv
from .console_utils import safe_print, is_verbose, verbose_print
from .forensic_logger import log_event

load_dotenv()

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
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={ "Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json" },
            data=json.dumps(payload),
            timeout=60
        )
        response.raise_for_status()
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
        response = requests.post(
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
        response.raise_for_status()
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