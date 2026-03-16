# console_utils.py
#!/usr/bin/env python3
"""
Console Utilities für Windows-Unicode-Kompatibilität

Stellt Windows-sichere Ausgabefunktionen zur Verfügung, die Emojis fallback-fähig ausgeben.
"""

import sys
import codecs

# Emoji-Mapping für Windows-Fallbacks
EMOJI_FALLBACKS = {
    '✅': '[OK]',      '❌': '[ERROR]',   '⚠️': '[WARNING]',
    '🔍': '[SEARCH]',  '📝': '[NOTE]',    '📊': '[STATUS]',
    '⏸️': '[PAUSE]',   '🎯': '[TARGET]',  '🔄': '[PROCESS]',
    '💾': '[SAVE]',    '🗂️': '[FILE]',    '🔥': '[DELETE]',
    '🧹': '[CLEANUP]', '🚀': '[RUN]',     '💡': '[INFO]',
    '🎉': '[SUCCESS]', '📚': '[COLLECTION]','📁': '[FOLDER]',
    '🤖': '[AI]',      '🔑': '[KEY]',     '💰': '[COST]',
    '🧪': '[TEST]'
}

# --- KORREKTUR: Die Funktion akzeptiert jetzt optional ein 'level'-Argument ---
def safe_print(text: str, level: str = None, **kwargs):
    """
    Sichere print-Funktion, die unter Windows mit Emojis funktioniert.
    Akzeptiert optional ein 'level' (z.B. "INFO", "SUCCESS"), um die Ausgabe zu präfixen.

    Args:
        text (str): Die auszugebende Nachricht.
        level (str, optional): Ein Log-Level wie "INFO", "SUCCESS", "ERROR", "WARNING".
                               Wird ignoriert, wenn der Text bereits mit einem Emoji beginnt.
        **kwargs: Zusätzliche Argumente für die print-Funktion (z.B. end, file).
    """
    # Überprüfen, ob der Text bereits ein Emoji-Präfix hat
    has_prefix = any(text.strip().startswith(emoji) for emoji in EMOJI_FALLBACKS)

    # Erzeuge das Präfix basierend auf dem Level, aber nur wenn kein Emoji vorhanden ist.
    prefix = ""
    if level and not has_prefix:
        level_map = {
            "SUCCESS": "✅", "ERROR": "❌", "WARNING": "⚠️",
            "INFO": "💡", "DEBUG": "🔍"
        }
        # Füge das entsprechende Emoji oder den Level-Text als Präfix hinzu
        prefix = level_map.get(level.upper(), f"[{level.upper()}]") + " "
    
    # Füge das Präfix zum Text hinzu
    final_text = f"{prefix}{text}"

    try:
        # Versuche normale Ausgabe mit Emojis
        print(final_text, **kwargs)
    except UnicodeEncodeError:
        # Fallback: Ersetze Emojis durch Text-Alternativen
        safe_text = final_text
        for emoji, fallback in EMOJI_FALLBACKS.items():
            safe_text = safe_text.replace(emoji, fallback)
        print(safe_text, **kwargs)
    except Exception:
        # Letzter Fallback: Nur ASCII-Zeichen
        ascii_text = final_text.encode('ascii', errors='replace').decode('ascii')
        print(ascii_text, **kwargs)

def safe_format(text: str) -> str:
    """
    Formatiert Text für sichere Ausgabe, behält Emojis in Log-Dateien bei.
    """
    if hasattr(sys.stdout, 'isatty') and sys.stdout.isatty():
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            return text
        except (TypeError, AttributeError):
            safe_text = text
            for emoji, fallback in EMOJI_FALLBACKS.items():
                safe_text = safe_text.replace(emoji, fallback)
            return safe_text
    else:
        return text

def configure_windows_console():
    """
    Konfiguriert Windows-Konsole für beste Unicode-Unterstützung.
    """
    if sys.platform == 'win32':
        try:
            if hasattr(sys.stdout, 'reconfigure'):
                sys.stdout.reconfigure(encoding='utf-8')
                sys.stderr.reconfigure(encoding='utf-8')
            else:
                # Fallback für ältere Python-Versionen
                sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
                sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
        except Exception:
            pass # Ignoriere Fehler, wenn die Konfiguration fehlschlägt
        
        try:
            os.system('chcp 65001 >nul 2>&1')
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Verbose mode
# ---------------------------------------------------------------------------

_verbose: bool = False


def set_verbose(v: bool) -> None:
    """Enable or disable verbose console output (Layer 1 summaries)."""
    global _verbose
    _verbose = v


def is_verbose() -> bool:
    """Return True if verbose mode is active."""
    return _verbose


def verbose_print(text: str, level: str = None, **kwargs):
    """Print only when verbose mode is active. Same signature as safe_print."""
    if _verbose:
        safe_print(text, level, **kwargs)


# Initialisiere Windows-Konsole beim Import
if sys.platform == 'win32':
    configure_windows_console()