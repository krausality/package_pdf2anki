"""Tests for forensic_logger module."""
import json
from pathlib import Path

from pdf2anki.text2anki.forensic_logger import (
    init_forensic_log,
    log_event,
    set_phase,
    get_forensic_log_path,
    close_forensic_log,
)


class TestForensicLoggerInit:
    def test_creates_forensic_directory(self, tmp_path):
        init_forensic_log(tmp_path / "log_archive", "test-run-001")
        assert (tmp_path / "log_archive" / "forensic").is_dir()
        close_forensic_log()

    def test_creates_jsonl_file(self, tmp_path):
        init_forensic_log(tmp_path / "log_archive", "test-run-001")
        path = get_forensic_log_path()
        assert path is not None
        assert path.name == "test-run-001.jsonl"
        assert path.exists()
        close_forensic_log()


class TestLogEvent:
    def test_appends_valid_jsonl(self, tmp_path):
        init_forensic_log(tmp_path, "run1")
        log_event("test_event", {"key": "value"})
        log_event("test_event_2", {"n": 42})
        close_forensic_log()

        path = tmp_path / "forensic" / "run1.jsonl"
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

        entry = json.loads(lines[0])
        assert entry["event"] == "test_event"
        assert entry["data"]["key"] == "value"
        assert "ts" in entry

    def test_includes_phase_context(self, tmp_path):
        init_forensic_log(tmp_path, "run2")
        set_phase("discovery")
        log_event("tool_call", {"name": "read_excerpts"})
        set_phase("ingest")
        log_event("prompt_built", {"length": 5000})
        close_forensic_log()

        lines = (tmp_path / "forensic" / "run2.jsonl").read_text(encoding="utf-8").strip().split("\n")
        assert json.loads(lines[0])["phase"] == "discovery"
        assert json.loads(lines[1])["phase"] == "ingest"

    def test_handles_unicode(self, tmp_path):
        init_forensic_log(tmp_path, "run3")
        log_event("card", {"front": "Was ist Σ*?", "back": "Alle Wörter über Σ"})
        close_forensic_log()

        line = (tmp_path / "forensic" / "run3.jsonl").read_text(encoding="utf-8").strip()
        entry = json.loads(line)
        assert "Σ*" in entry["data"]["front"]

    def test_handles_large_data(self, tmp_path):
        init_forensic_log(tmp_path, "run4")
        big_prompt = "x" * 200_000
        log_event("llm_request", {"prompt": big_prompt})
        close_forensic_log()

        line = (tmp_path / "forensic" / "run4.jsonl").read_text(encoding="utf-8").strip()
        entry = json.loads(line)
        assert len(entry["data"]["prompt"]) == 200_000


class TestNoInit:
    def test_log_event_noop_without_init(self):
        close_forensic_log()  # ensure clean state
        log_event("should_not_crash", {"data": "test"})
        assert get_forensic_log_path() is None

    def test_set_phase_noop_without_init(self):
        close_forensic_log()
        set_phase("discovery")  # should not crash


class TestClose:
    def test_close_resets_state(self, tmp_path):
        init_forensic_log(tmp_path, "run5")
        assert get_forensic_log_path() is not None
        close_forensic_log()
        assert get_forensic_log_path() is None

    def test_log_noop_after_close(self, tmp_path):
        init_forensic_log(tmp_path, "run6")
        close_forensic_log()
        log_event("after_close", {"should": "noop"})
        # File should exist but be empty (no events written after close)
        content = (tmp_path / "forensic" / "run6.jsonl").read_text(encoding="utf-8")
        assert content.strip() == ""


class TestCrashSafety:
    def test_each_line_independently_parseable(self, tmp_path):
        init_forensic_log(tmp_path, "run7")
        for i in range(50):
            log_event(f"event_{i}", {"index": i})
        close_forensic_log()

        lines = (tmp_path / "forensic" / "run7.jsonl").read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 50
        for i, line in enumerate(lines):
            entry = json.loads(line)
            assert entry["data"]["index"] == i
