"""Tests for console_utils module."""
import io
import sys
import pytest
from unittest.mock import patch, MagicMock

from pdf2anki.text2anki.console_utils import (
    safe_print,
    safe_format,
    verbose_print,
    set_verbose,
    is_verbose,
    EMOJI_FALLBACKS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_verbose():
    """Ensure verbose state is clean for every test."""
    set_verbose(False)
    yield
    set_verbose(False)


# ---------------------------------------------------------------------------
# safe_print — basic output
# ---------------------------------------------------------------------------

class TestSafePrint:
    def test_plain_text(self, capsys):
        safe_print("hello world")
        assert "hello world" in capsys.readouterr().out

    def test_level_adds_emoji_prefix(self, capsys):
        safe_print("test message", "SUCCESS")
        out = capsys.readouterr().out
        # Should contain the success emoji or its fallback
        assert "test message" in out
        assert out.strip().startswith("\u2705") or out.strip().startswith("[OK]")

    def test_level_error(self, capsys):
        safe_print("bad thing", "ERROR")
        out = capsys.readouterr().out
        assert "bad thing" in out

    def test_level_warning(self, capsys):
        safe_print("careful", "WARNING")
        out = capsys.readouterr().out
        assert "careful" in out

    def test_level_info(self, capsys):
        safe_print("info msg", "INFO")
        out = capsys.readouterr().out
        assert "info msg" in out

    def test_unknown_level_uses_bracket_prefix(self, capsys):
        safe_print("custom", "CUSTOM")
        out = capsys.readouterr().out
        assert "[CUSTOM]" in out
        assert "custom" in out

    def test_no_double_prefix_when_emoji_present(self, capsys):
        """If text already starts with a known emoji, level should NOT add another."""
        safe_print("\u2705 already prefixed", "SUCCESS")
        out = capsys.readouterr().out
        # Should NOT have two checkmarks
        assert out.count("\u2705") == 1 or "[OK]" in out

    def test_level_none_no_prefix(self, capsys):
        safe_print("bare text", None)
        out = capsys.readouterr().out
        assert out.strip() == "bare text"

    def test_kwargs_passed_through(self, capsys):
        safe_print("no newline", end="!")
        out = capsys.readouterr().out
        assert out.endswith("!")


# ---------------------------------------------------------------------------
# safe_print — exception fallbacks
# ---------------------------------------------------------------------------

class TestSafePrintFallbacks:
    def test_unicode_error_falls_back_to_emoji_replacement(self, capsys):
        """When print raises UnicodeEncodeError, emojis are replaced with text."""
        call_count = 0

        def mock_print(text, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Correct UnicodeEncodeError: object must be str, not bytes
                raise UnicodeEncodeError("cp1252", "\u2705", 0, 1, "emoji")
            sys.stdout.write(text + "\n")

        with patch("builtins.print", side_effect=mock_print):
            safe_print("\u2705 success")

        out = capsys.readouterr().out
        assert "[OK]" in out
        assert call_count == 2

    def test_general_exception_falls_back_to_ascii(self, capsys):
        """When first print raises a non-Unicode error, ASCII fallback is used."""
        call_count = 0

        def mock_print(text, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("total failure")
            # Second call (from except Exception handler) succeeds
            sys.stdout.write(text + "\n")

        with patch("builtins.print", side_effect=mock_print):
            safe_print("\u2705 emoji text")

        out = capsys.readouterr().out
        # ASCII fallback replaces non-ASCII with ?
        assert "?" in out or "emoji text" in out
        assert call_count == 2


# ---------------------------------------------------------------------------
# safe_format
# ---------------------------------------------------------------------------

class TestSafeFormat:
    def test_returns_text_when_not_tty(self):
        """When stdout is not a TTY, text is returned unchanged."""
        with patch.object(sys.stdout, "isatty", return_value=False):
            result = safe_format("\u2705 hello")
        assert result == "\u2705 hello"

    def test_returns_text_when_tty_and_reconfigure_works(self):
        mock_stdout = MagicMock()
        mock_stdout.isatty.return_value = True
        mock_stdout.reconfigure = MagicMock()
        with patch("pdf2anki.text2anki.console_utils.sys.stdout", mock_stdout):
            result = safe_format("\u2705 hello")
        assert result == "\u2705 hello"

    def test_replaces_emojis_when_reconfigure_fails(self):
        mock_stdout = MagicMock()
        mock_stdout.isatty.return_value = True
        mock_stdout.reconfigure.side_effect = TypeError("no reconfigure")
        with patch("pdf2anki.text2anki.console_utils.sys.stdout", mock_stdout):
            result = safe_format("\u2705 hello")
        assert "[OK]" in result


# ---------------------------------------------------------------------------
# Verbose mode
# ---------------------------------------------------------------------------

class TestVerboseMode:
    def test_default_is_off(self):
        assert is_verbose() is False

    def test_set_verbose_on(self):
        set_verbose(True)
        assert is_verbose() is True

    def test_set_verbose_off(self):
        set_verbose(True)
        set_verbose(False)
        assert is_verbose() is False

    def test_verbose_print_silent_when_off(self, capsys):
        set_verbose(False)
        verbose_print("should not appear")
        assert capsys.readouterr().out == ""

    def test_verbose_print_outputs_when_on(self, capsys):
        set_verbose(True)
        verbose_print("visible now")
        assert "visible now" in capsys.readouterr().out

    def test_verbose_print_with_level(self, capsys):
        set_verbose(True)
        verbose_print("detail", "INFO")
        out = capsys.readouterr().out
        assert "detail" in out

    def test_state_isolation_between_tests_a(self):
        """Part A of isolation check — sets verbose True."""
        set_verbose(True)
        assert is_verbose() is True

    def test_state_isolation_between_tests_b(self):
        """Part B — verbose should be False (reset by fixture)."""
        assert is_verbose() is False
