"""Tests for pipeline_trace.py — PipelineTrace class."""
import json
import pytest
from pathlib import Path

from pdf2anki.text2anki.pipeline_trace import PipelineTrace, _extract_llm_metadata


# ---------------------------------------------------------------------------
# _extract_llm_metadata
# ---------------------------------------------------------------------------

class TestExtractLLMMetadata:
    def test_empty_list(self):
        assert _extract_llm_metadata([]) == []

    def test_successful_response(self):
        resp = {
            "model": "google/gemini-2.5-flash",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "cost": 0.001,
                "prompt_tokens_details": {"cached_tokens": 20},
            },
        }
        result = _extract_llm_metadata([resp])
        assert len(result) == 1
        assert result[0]["model"] == "google/gemini-2.5-flash"
        assert result[0]["prompt_tokens"] == 100
        assert result[0]["completion_tokens"] == 50
        assert result[0]["cached_tokens"] == 20
        assert result[0]["cost"] == 0.001

    def test_error_response(self):
        resp = {"error": "API timeout"}
        result = _extract_llm_metadata([resp])
        assert result == [{"error": "API timeout"}]

    def test_missing_usage_fields(self):
        resp = {"model": "test-model"}
        result = _extract_llm_metadata([resp])
        assert result[0]["prompt_tokens"] == 0
        assert result[0]["completion_tokens"] == 0
        assert result[0]["cached_tokens"] == 0
        assert result[0]["cost"] == 0.0


# ---------------------------------------------------------------------------
# PipelineTrace — lifecycle
# ---------------------------------------------------------------------------

class TestPipelineTraceLifecycle:
    def test_creates_trace_file(self, tmp_path):
        trace_path = tmp_path / "pipeline_trace.json"
        trace = PipelineTrace(trace_path)
        trace.begin_run()
        trace.end_run("ok")

        assert trace_path.exists()
        data = json.loads(trace_path.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["status"] == "ok"

    def test_append_multiple_runs(self, tmp_path):
        trace_path = tmp_path / "pipeline_trace.json"

        trace1 = PipelineTrace(trace_path)
        trace1.begin_run()
        trace1.end_run("ok")

        trace2 = PipelineTrace(trace_path)
        trace2.begin_run()
        trace2.end_run("failed", "something broke")

        data = json.loads(trace_path.read_text(encoding="utf-8"))
        assert len(data) == 2
        assert data[0]["status"] == "ok"
        assert data[1]["status"] == "failed"
        assert data[1]["error"] == "something broke"

    def test_run_has_timestamps_and_id(self, tmp_path):
        trace_path = tmp_path / "pipeline_trace.json"
        trace = PipelineTrace(trace_path)
        trace.begin_run()
        trace.end_run("ok")

        run = json.loads(trace_path.read_text(encoding="utf-8"))[0]
        assert run["run_id"] is not None
        assert run["started_at"] is not None
        assert run["finished_at"] is not None

    def test_corrupt_file_renamed_to_bak(self, tmp_path):
        trace_path = tmp_path / "pipeline_trace.json"
        trace_path.write_text("not valid json{{{", encoding="utf-8")

        trace = PipelineTrace(trace_path)
        trace.begin_run()
        trace.end_run("ok")

        assert trace_path.exists()
        bak = trace_path.with_suffix(".json.bak")
        assert bak.exists()
        assert bak.read_text(encoding="utf-8") == "not valid json{{{"


# ---------------------------------------------------------------------------
# PipelineTrace — phases
# ---------------------------------------------------------------------------

class TestPipelineTracePhases:
    def test_phase_recorded(self, tmp_path):
        trace_path = tmp_path / "pipeline_trace.json"
        trace = PipelineTrace(trace_path)
        trace.begin_run()
        trace.begin_phase("discovery")
        trace.end_phase("discovery", "ok", {"method": "llm"})
        trace.end_run("ok")

        run = json.loads(trace_path.read_text(encoding="utf-8"))[0]
        assert "discovery" in run["phases"]
        assert run["phases"]["discovery"]["status"] == "ok"
        assert run["phases"]["discovery"]["method"] == "llm"

    def test_multiple_phases(self, tmp_path):
        trace_path = tmp_path / "pipeline_trace.json"
        trace = PipelineTrace(trace_path)
        trace.begin_run()

        for phase in ["discovery", "ocr", "ingest", "integrate", "export"]:
            trace.begin_phase(phase)
            trace.end_phase(phase, "ok")

        trace.end_run("ok")
        run = json.loads(trace_path.read_text(encoding="utf-8"))[0]
        assert set(run["phases"].keys()) == {"discovery", "ocr", "ingest", "integrate", "export"}

    def test_phase_with_llm_responses(self, tmp_path):
        trace_path = tmp_path / "pipeline_trace.json"
        trace = PipelineTrace(trace_path)
        trace.begin_run()
        trace.begin_phase("ingest")

        responses = [
            {"model": "m1", "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.01}},
            {"model": "m1", "usage": {"prompt_tokens": 20, "completion_tokens": 10, "cost": 0.02}},
        ]
        trace.end_phase("ingest", "ok", {}, responses)
        trace.end_run("ok")

        run = json.loads(trace_path.read_text(encoding="utf-8"))[0]
        assert len(run["phases"]["ingest"]["llm_calls"]) == 2

    def test_incremental_flush(self, tmp_path):
        """Trace file is updated after each end_phase, not just end_run."""
        trace_path = tmp_path / "pipeline_trace.json"
        trace = PipelineTrace(trace_path)
        trace.begin_run()
        trace.begin_phase("ocr")
        trace.end_phase("ocr", "ok", {"pdfs_processed": 3})

        # Read mid-run — should have partial data
        data = json.loads(trace_path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["status"] == "running"
        assert "ocr" in data[0]["phases"]


# ---------------------------------------------------------------------------
# PipelineTrace — summary
# ---------------------------------------------------------------------------

class TestPipelineTraceSummary:
    def test_summary_computed_on_end_run(self, tmp_path):
        trace_path = tmp_path / "pipeline_trace.json"
        trace = PipelineTrace(trace_path)
        trace.begin_run()

        trace.begin_phase("ingest")
        trace.end_phase("ingest", "ok", {"cards_generated": 42}, [
            {"model": "m", "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost": 0.05}},
        ])

        trace.begin_phase("integrate")
        trace.end_phase("integrate", "ok", {"cards_added": 40})

        trace.begin_phase("export")
        trace.end_phase("export", "ok", {"files_generated": [
            {"path": "coll_0.apkg", "card_count": 20},
            {"path": "coll_1.apkg", "card_count": 20},
        ]})

        trace.end_run("ok")

        run = json.loads(trace_path.read_text(encoding="utf-8"))[0]
        summary = run["summary"]
        assert summary["total_cost"] == 0.05
        assert summary["total_llm_calls"] == 1
        assert summary["total_cards_generated"] == 42
        assert summary["total_cards_added"] == 40
        assert summary["total_apkg_files"] == 2
        assert summary["total_time_seconds"] is not None
        assert summary["errors"] == []

    def test_summary_collects_errors(self, tmp_path):
        trace_path = tmp_path / "pipeline_trace.json"
        trace = PipelineTrace(trace_path)
        trace.begin_run()

        trace.begin_phase("discovery")
        trace.end_phase("discovery", "failed", {"error": "LLM unreachable"}, [
            {"error": "connection timeout"},
        ])

        trace.end_run("failed", "Discovery failed")

        run = json.loads(trace_path.read_text(encoding="utf-8"))[0]
        assert len(run["summary"]["errors"]) == 2
        assert any("connection timeout" in e for e in run["summary"]["errors"])
        assert any("LLM unreachable" in e for e in run["summary"]["errors"])
