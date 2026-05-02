"""Tests for pdf2anki.perf_tuner — per-model OCR concurrency tuner."""
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

# Re-import the module fresh for each test so PDF2ANKI_DISABLE_TUNER changes
# applied within tests are honored. The conftest sets it to "1" globally.
import importlib
import pdf2anki.perf_tuner as perf_tuner


@pytest.fixture
def tuner_with_tmp_home(tmp_path, monkeypatch):
    """Run tuner against a temp home directory and re-enable it for the test."""
    monkeypatch.setenv("PDF2ANKI_DISABLE_TUNER", "0")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    importlib.reload(perf_tuner)
    yield perf_tuner
    # Reset disable flag for the rest of the suite
    monkeypatch.setenv("PDF2ANKI_DISABLE_TUNER", "1")


def _read_log(tmp_path: Path) -> list[dict]:
    log = tmp_path / ".pdf2anki" / "perf_log.ndjson"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


class TestColdStart:
    def test_seed_for_known_provider(self, tuner_with_tmp_home):
        assert tuner_with_tmp_home.get_recommended_concurrency("google/gemini-2.5-flash") == 12
        assert tuner_with_tmp_home.get_recommended_concurrency("anthropic/claude-sonnet-4-5") == 6
        assert tuner_with_tmp_home.get_recommended_concurrency("openai/gpt-4o") == 8

    def test_seed_for_unknown_provider(self, tuner_with_tmp_home):
        # Falls back to _DEFAULT_COLD_START
        assert tuner_with_tmp_home.get_recommended_concurrency("foo/bar") == 4

    def test_resolve_explicit_overrides_tuner(self, tuner_with_tmp_home):
        assert tuner_with_tmp_home.resolve_concurrency("google/gemini-2.5-flash", 24) == 24
        assert tuner_with_tmp_home.resolve_concurrency("foo/bar", 1) == 1


class TestDisabled:
    def test_disabled_returns_seed(self, monkeypatch):
        monkeypatch.setenv("PDF2ANKI_DISABLE_TUNER", "1")
        importlib.reload(perf_tuner)
        assert perf_tuner.get_recommended_concurrency("google/foo") == 12

    def test_disabled_skips_recording(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PDF2ANKI_DISABLE_TUNER", "1")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        importlib.reload(perf_tuner)
        perf_tuner.record_observation("foo/bar", 8, pages_completed=20, errors=0, paused=False)
        assert _read_log(tmp_path) == []


class TestRoundTrip:
    def test_record_then_read(self, tuner_with_tmp_home, tmp_path):
        tuner_with_tmp_home.record_observation(
            "google/gemini-2.5-flash", concurrency=10,
            pages_completed=20, errors=0, paused=False,
        )
        log = _read_log(tmp_path)
        assert len(log) == 1
        assert log[0]["model"] == "google/gemini-2.5-flash"
        assert log[0]["concurrency"] == 10

    def test_too_few_pages_skipped_unless_paused(self, tuner_with_tmp_home, tmp_path):
        # 2 pages, no pause → no record
        tuner_with_tmp_home.record_observation("foo/bar", 4, pages_completed=2, errors=0, paused=False)
        assert _read_log(tmp_path) == []
        # 2 pages but paused → recorded (pause is strong signal)
        tuner_with_tmp_home.record_observation("foo/bar", 4, pages_completed=2, errors=0, paused=True)
        assert len(_read_log(tmp_path)) == 1


class TestPolicy:
    def test_pause_halves(self, tuner_with_tmp_home):
        tuner_with_tmp_home.record_observation("google/foo", 16, 20, 0, paused=True)
        assert tuner_with_tmp_home.get_recommended_concurrency("google/foo") == 8

    def test_errors_decrement(self, tuner_with_tmp_home):
        tuner_with_tmp_home.record_observation("google/foo", 12, 20, errors=3, paused=False)
        assert tuner_with_tmp_home.get_recommended_concurrency("google/foo") == 11

    def test_three_clean_runs_probe_higher(self, tuner_with_tmp_home):
        for _ in range(3):
            tuner_with_tmp_home.record_observation("google/foo", 8, 20, 0, paused=False)
        assert tuner_with_tmp_home.get_recommended_concurrency("google/foo") == 9

    def test_two_clean_runs_stay_put(self, tuner_with_tmp_home):
        for _ in range(2):
            tuner_with_tmp_home.record_observation("google/foo", 8, 20, 0, paused=False)
        assert tuner_with_tmp_home.get_recommended_concurrency("google/foo") == 8

    def test_per_model_isolation(self, tuner_with_tmp_home):
        tuner_with_tmp_home.record_observation("google/foo", 16, 20, 0, paused=True)
        # Different model is not affected
        assert tuner_with_tmp_home.get_recommended_concurrency("openai/bar") == 8

    def test_demote_floor_is_one(self, tuner_with_tmp_home):
        tuner_with_tmp_home.record_observation("foo/bar", 1, 20, 0, paused=True)
        assert tuner_with_tmp_home.get_recommended_concurrency("foo/bar") == 1

    def test_promote_capped_at_max(self, tuner_with_tmp_home):
        # Push to ceiling
        for _ in range(3):
            tuner_with_tmp_home.record_observation(
                "google/foo", tuner_with_tmp_home.MAX_RECOMMENDED_CONCURRENCY, 20, 0, paused=False,
            )
        assert (
            tuner_with_tmp_home.get_recommended_concurrency("google/foo")
            == tuner_with_tmp_home.MAX_RECOMMENDED_CONCURRENCY
        )


class TestResilience:
    def test_corrupt_line_tolerated(self, tuner_with_tmp_home, tmp_path):
        log = tmp_path / ".pdf2anki" / "perf_log.ndjson"
        log.parent.mkdir(parents=True, exist_ok=True)
        good = json.dumps({"model": "foo/bar", "concurrency": 8, "errors": 0, "paused": False})
        log.write_text(good + "\n{not valid json\n" + good + "\n", encoding="utf-8")
        # Should still produce a valid recommendation, ignoring the bad line.
        rec = tuner_with_tmp_home.get_recommended_concurrency("foo/bar")
        assert rec == 8

    def test_unreadable_log_falls_back_to_seed(self, tuner_with_tmp_home, tmp_path, monkeypatch):
        # Force the read to raise via mocking open
        import builtins
        real_open = builtins.open

        def boom(path, *args, **kwargs):
            if "perf_log" in str(path):
                raise OSError("simulated unreadable")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", boom)
        # Should not raise; falls back to provider seed.
        assert tuner_with_tmp_home.get_recommended_concurrency("google/foo") == 12

    def test_record_failure_silent(self, tuner_with_tmp_home, monkeypatch):
        # Ensure a write failure does not propagate.
        import builtins
        real_open = builtins.open

        def boom(path, *args, **kwargs):
            if "perf_log" in str(path) and ("a" in (args[0] if args else kwargs.get("mode", ""))):
                raise OSError("simulated write fail")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", boom)
        # Should not raise
        tuner_with_tmp_home.record_observation("foo/bar", 4, 20, 0, paused=False)
