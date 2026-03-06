import os
import requests
import json
import getpass
from dotenv import load_dotenv
from .console_utils import safe_print

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

def get_llm_decision(header_context, prompt_body, model="google/gemini-2.5-flash"):
    """
    Führt einen API-Aufruf an OpenRouter durch, sammelt die volle Antwort und gibt die Entscheidung zurück.
    """
    if not API_KEY and not _initialize_api_key():
        return None

    full_prompt = f"{header_context}\n\n---\n\n{prompt_body}"

    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={ "Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json" },
            data=json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": full_prompt}],
                "temperature": 0.1,
                # --- KORREKTUR: Sende das `usage`-Objekt genau wie von der API gefordert ---
                "usage": {
                    "include": True
                }
            }),
            timeout=60
        )
        response.raise_for_status()
        response_data = response.json()
        
        _session_responses.append(response_data)
        
        safe_print("--- Full OpenRouter API Response ---", "INFO")
        safe_print(json.dumps(response_data, indent=2, ensure_ascii=False))
        safe_print("------------------------------------", "INFO")
        
        usage = response_data.get('usage', {})
        cost = usage.get('cost', 0.0) # Dieses Feld wird jetzt vorhanden sein
        cached_tokens = usage.get('prompt_tokens_details', {}).get('cached_tokens', 0) # Dieses Feld auch
        safe_print(f"LLM call successful. Cost: ${cost:.8f} (Cached: {cached_tokens} tokens)", "INFO")
        
        return response_data['choices'][0]['message']['content'].strip()

    except requests.exceptions.RequestException as e:
        safe_print(f"API-Anfrage fehlgeschlagen: {e}", "ERROR")
        _session_responses.append({"error": str(e)})
        return None
    except (KeyError, IndexError) as e:
        safe_print(f"Unerwartete API-Antwortstruktur: {e}", "ERROR")
        _session_responses.append({"error": f"Invalid response structure: {e}"})
        return None