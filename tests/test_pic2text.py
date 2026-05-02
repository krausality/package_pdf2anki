"""Tests for pdf2anki.pic2text — OCR image processing."""
import json
import os
import base64
import io
import threading
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

from pdf2anki.pic2text import (
    sanitize_filename,
    extract_page_number,
    _is_error_text,
    _is_info_text,
    _is_successful_ocr_text,
    _parse_output_sections,
    _write_output_sections_atomic,
    _initialize_state_from_legacy,
    _state_matches_current_images,
    _compute_images_fingerprint,
    OCRPauseException,
    convert_images_to_text,
    STATE_SCHEMA_VERSION,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_png_image(tmp_path, name="page_1.png"):
    """Create a minimal 1x1 PNG in tmp_path and return its path."""
    from PIL import Image as PILImage
    path = tmp_path / name
    PILImage.new("RGB", (4, 4), color=(128, 64, 32)).save(str(path))
    return path


def make_mock_ocr_response(text):
    """Build a mock requests.Response for OCR result."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"choices": [{"message": {"content": text}}]}
    return mock_resp


# ─────────────────────────────────────────────────────────────────────────────
# Pure utility functions
# ─────────────────────────────────────────────────────────────────────────────

class TestSanitizeFilename:
    def test_alphanumeric_unchanged(self):
        assert sanitize_filename("page1") == "page1"

    def test_spaces_replaced(self):
        assert sanitize_filename("my file") == "my_file"

    def test_dots_replaced(self):
        assert sanitize_filename("file.txt") == "file_txt"

    def test_multiple_special_chars_collapsed(self):
        result = sanitize_filename("a!@#b")
        assert result == "a___b" or "_" in result  # re.sub replaces each or run


class TestExtractPageNumber:
    def test_standard_filename(self):
        assert extract_page_number("page_3.png") == 3

    def test_larger_number(self):
        assert extract_page_number("page_42.png") == 42

    def test_no_match_returns_inf(self):
        assert extract_page_number("image_001.jpg") == float("inf")

    def test_zero_page(self):
        assert extract_page_number("page_0.png") == 0


class TestTextClassifiers:
    def test_is_error_text(self):
        assert _is_error_text("[ERROR: timeout]") is True
        assert _is_error_text("normal text") is False
        assert _is_error_text(None) is False
        assert _is_error_text("") is False

    def test_is_info_text(self):
        assert _is_info_text("[INFO: skipped]") is True
        assert _is_info_text("text") is False
        assert _is_info_text(None) is False

    def test_is_successful_ocr_text(self):
        assert _is_successful_ocr_text("Some OCR result") is True
        assert _is_successful_ocr_text("[ERROR: failed]") is False
        assert _is_successful_ocr_text("[INFO: blah]") is False
        assert _is_successful_ocr_text(None) is False
        assert _is_successful_ocr_text("") is False
        assert _is_successful_ocr_text("   ") is False


# ─────────────────────────────────────────────────────────────────────────────
# _parse_output_sections
# ─────────────────────────────────────────────────────────────────────────────

class TestParseOutputSections:
    def test_empty_file(self, tmp_path):
        f = tmp_path / "out.txt"
        f.write_text("", encoding="utf-8")
        assert _parse_output_sections(f) == {}

    def test_nonexistent_file(self, tmp_path):
        assert _parse_output_sections(tmp_path / "missing.txt") == {}

    def test_single_section(self, tmp_path):
        content = "Image: page_1.png\nHello world"
        f = tmp_path / "out.txt"
        f.write_text(content, encoding="utf-8")
        sections = _parse_output_sections(f)
        assert "page_1.png" in sections
        assert sections["page_1.png"] == "Hello world"

    def test_multiple_sections(self, tmp_path):
        content = (
            "Image: page_1.png\nText for page 1\n\n"
            "Image: page_2.png\nText for page 2"
        )
        f = tmp_path / "out.txt"
        f.write_text(content, encoding="utf-8")
        sections = _parse_output_sections(f)
        assert len(sections) == 2
        assert sections["page_1.png"] == "Text for page 1"
        assert sections["page_2.png"] == "Text for page 2"

    def test_trailing_whitespace_stripped(self, tmp_path):
        content = "Image: page_1.png\nContent   \n\n"
        f = tmp_path / "out.txt"
        f.write_text(content, encoding="utf-8")
        sections = _parse_output_sections(f)
        assert sections["page_1.png"] == "Content"


# ─────────────────────────────────────────────────────────────────────────────
# _write_output_sections_atomic
# ─────────────────────────────────────────────────────────────────────────────

class TestWriteOutputSectionsAtomic:
    def test_writes_correct_format(self, tmp_path):
        out = tmp_path / "output.txt"
        page_texts = {"page_1.png": "OCR result", "page_2.png": "More text"}
        _write_output_sections_atomic(out, ["page_1.png", "page_2.png"], page_texts)
        content = out.read_text(encoding="utf-8")
        assert "Image: page_1.png" in content
        assert "OCR result" in content
        assert "Image: page_2.png" in content

    def test_skips_missing_pages(self, tmp_path):
        out = tmp_path / "output.txt"
        _write_output_sections_atomic(out, ["page_1.png"], {"page_2.png": "text"})
        content = out.read_text(encoding="utf-8")
        assert "page_1" not in content


# ─────────────────────────────────────────────────────────────────────────────
# _initialize_state_from_legacy
# ─────────────────────────────────────────────────────────────────────────────

class TestInitializeStateFromLegacy:
    def test_done_pages_from_existing(self):
        state, page_texts = _initialize_state_from_legacy(
            image_files=["page_1.png"],
            existing_sections={"page_1.png": "Good OCR text"},
            images_fingerprint="abc123",
            max_page_attempts=40,
        )
        assert state["pages"]["page_1.png"]["status"] == "done"
        assert page_texts["page_1.png"] == "Good OCR text"

    def test_error_pages_pending(self):
        state, _ = _initialize_state_from_legacy(
            image_files=["page_1.png"],
            existing_sections={"page_1.png": "[ERROR: timeout]"},
            images_fingerprint="abc123",
            max_page_attempts=40,
        )
        assert state["pages"]["page_1.png"]["status"] == "pending"

    def test_missing_page_is_pending(self):
        state, _ = _initialize_state_from_legacy(
            image_files=["page_1.png"],
            existing_sections={},
            images_fingerprint="fp",
            max_page_attempts=10,
        )
        assert state["pages"]["page_1.png"]["status"] == "pending"

    def test_fingerprint_stored(self):
        state, _ = _initialize_state_from_legacy(["p.png"], {}, "myfp", 10)
        assert state["images_fingerprint"] == "myfp"


# ─────────────────────────────────────────────────────────────────────────────
# _state_matches_current_images
# ─────────────────────────────────────────────────────────────────────────────

class TestStateMatchesCurrentImages:
    def _valid_state(self, image_files, fingerprint):
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "images_fingerprint": fingerprint,
            "pages": {name: {} for name in image_files},
        }

    def test_matching_state(self):
        state = self._valid_state(["p1.png", "p2.png"], "fp1")
        assert _state_matches_current_images(state, ["p1.png", "p2.png"], "fp1") is True

    def test_wrong_fingerprint(self):
        state = self._valid_state(["p1.png"], "fp1")
        assert _state_matches_current_images(state, ["p1.png"], "fp2") is False

    def test_missing_image_in_state(self):
        state = self._valid_state(["p1.png"], "fp1")
        assert _state_matches_current_images(state, ["p1.png", "p2.png"], "fp1") is False

    def test_wrong_schema_version(self):
        state = self._valid_state(["p1.png"], "fp1")
        state["schema_version"] = 999
        assert _state_matches_current_images(state, ["p1.png"], "fp1") is False

    def test_not_a_dict(self):
        assert _state_matches_current_images(None, [], "fp") is False


# ─────────────────────────────────────────────────────────────────────────────
# _compute_images_fingerprint
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeImagesFingerprint:
    def test_returns_string(self, tmp_path):
        img = make_png_image(tmp_path, "page_1.png")
        fp = _compute_images_fingerprint(str(tmp_path), ["page_1.png"])
        assert isinstance(fp, str)
        assert len(fp) == 64  # sha256 hex

    def test_different_files_different_fingerprints(self, tmp_path):
        make_png_image(tmp_path, "page_1.png")
        make_png_image(tmp_path, "page_2.png")
        fp1 = _compute_images_fingerprint(str(tmp_path), ["page_1.png"])
        fp2 = _compute_images_fingerprint(str(tmp_path), ["page_1.png", "page_2.png"])
        assert fp1 != fp2

    def test_missing_file_uses_missing_sentinel(self, tmp_path):
        fp = _compute_images_fingerprint(str(tmp_path), ["ghost.png"])
        assert isinstance(fp, str)


# ─────────────────────────────────────────────────────────────────────────────
# convert_images_to_text — integration-level (mocked requests)
# ─────────────────────────────────────────────────────────────────────────────

class TestConvertImagesToText:
    def test_success_path_single_image(self, tmp_path):
        """Single image, single OCR model — happy path writes output file."""
        img = make_png_image(tmp_path, "page_1.png")
        out_file = str(tmp_path / "output.txt")

        mock_resp = make_mock_ocr_response("This is the OCR text.")

        with patch("pdf2anki.pic2text.OPENROUTER_API_KEY", "fake-key"), \
             patch("pdf2anki.pic2text._http_post", return_value=mock_resp), \
             patch("pdf2anki.pic2text.time.sleep"):
            result = convert_images_to_text(
                images_dir=str(tmp_path),
                output_file=out_file,
                model_repeats=[("ocr/model", 1)],
                max_page_attempts=3,
            )

        assert result == out_file
        content = Path(out_file).read_text(encoding="utf-8")
        assert "page_1.png" in content
        assert "This is the OCR text." in content

    def test_api_timeout_eventually_raises_or_writes_error(self, tmp_path):
        """When requests.post repeatedly raises Timeout, OCRPauseException is raised
        (max attempts exhausted) and the output file contains an error marker."""
        import requests as req_lib
        img = make_png_image(tmp_path, "page_1.png")
        out_file = str(tmp_path / "output.txt")

        with patch("pdf2anki.pic2text.OPENROUTER_API_KEY", "fake-key"), \
             patch("pdf2anki.pic2text._http_post", side_effect=req_lib.exceptions.Timeout("timeout")), \
             patch("pdf2anki.pic2text.time.sleep"):
            with pytest.raises(OCRPauseException):
                convert_images_to_text(
                    images_dir=str(tmp_path),
                    output_file=out_file,
                    model_repeats=[("ocr/model", 1)],
                    max_page_attempts=2,
                )

        # After pause the state file should exist and mark page as paused
        state_file = Path(out_file + ".ocr_state.json")
        assert state_file.exists()
        state = json.loads(state_file.read_text(encoding="utf-8"))
        assert state["pages"]["page_1.png"]["status"] == "paused"

    def test_max_attempts_raises_pause_exception(self, tmp_path):
        """Hitting max_page_attempts raises OCRPauseException."""
        import requests as req_lib
        img = make_png_image(tmp_path, "page_1.png")
        out_file = str(tmp_path / "output.txt")

        with patch("pdf2anki.pic2text.OPENROUTER_API_KEY", "fake-key"), \
             patch("pdf2anki.pic2text._http_post", side_effect=req_lib.exceptions.Timeout("t")), \
             patch("pdf2anki.pic2text.time.sleep"):
            with pytest.raises(OCRPauseException):
                convert_images_to_text(
                    images_dir=str(tmp_path),
                    output_file=out_file,
                    model_repeats=[("ocr/model", 1)],
                    max_page_attempts=1,
                )

    def test_resume_skips_done_pages(self, tmp_path):
        """Pages already marked 'done' in state file are not re-processed."""
        img = make_png_image(tmp_path, "page_1.png")
        out_file = tmp_path / "output.txt"

        # Pre-write output and state so page_1.png is already 'done'
        out_file.write_text("Image: page_1.png\nPre-existing OCR result", encoding="utf-8")
        fp = _compute_images_fingerprint(str(tmp_path), ["page_1.png"])
        state = {
            "schema_version": STATE_SCHEMA_VERSION,
            "images_fingerprint": fp,
            "max_page_attempts": 40,
            "run_status": "running",
            "pause_reason": None,
            "updated_at": "2026-01-01T00:00:00",
            "pages": {
                "page_1.png": {
                    "status": "done",
                    "attempts_used": 1,
                    "last_error": None,
                    "updated_at": "2026-01-01T00:00:00",
                }
            },
        }
        state_file = tmp_path / f"{out_file.name}.ocr_state.json"
        state_file.write_text(json.dumps(state), encoding="utf-8")

        call_count = {"n": 0}

        def fake_post(*args, **kwargs):
            call_count["n"] += 1
            return make_mock_ocr_response("Should not be called")

        with patch("pdf2anki.pic2text.OPENROUTER_API_KEY", "fake-key"), \
             patch("pdf2anki.pic2text._http_post", side_effect=fake_post), \
             patch("pdf2anki.pic2text.time.sleep"):
            convert_images_to_text(
                images_dir=str(tmp_path),
                output_file=str(out_file),
                model_repeats=[("ocr/model", 1)],
                max_page_attempts=5,
            )

        # API should not have been called since page is already done
        assert call_count["n"] == 0

    def test_multiple_images_all_processed(self, tmp_path):
        """Two images → both appear in output file."""
        make_png_image(tmp_path, "page_1.png")
        make_png_image(tmp_path, "page_2.png")
        out_file = str(tmp_path / "output.txt")

        responses = [
            make_mock_ocr_response("Text from page 1"),
            make_mock_ocr_response("Text from page 2"),
        ]
        idx = {"i": 0}

        def fake_post(*args, **kwargs):
            r = responses[min(idx["i"], len(responses) - 1)]
            idx["i"] += 1
            return r

        with patch("pdf2anki.pic2text.OPENROUTER_API_KEY", "fake-key"), \
             patch("pdf2anki.pic2text._http_post", side_effect=fake_post), \
             patch("pdf2anki.pic2text.time.sleep"):
            convert_images_to_text(
                images_dir=str(tmp_path),
                output_file=out_file,
                model_repeats=[("ocr/model", 1)],
                max_page_attempts=5,
            )

        content = Path(out_file).read_text(encoding="utf-8")
        assert "page_1.png" in content
        assert "page_2.png" in content

    def test_no_resume_flag_ignores_existing_state(self, tmp_path):
        """no_resume=True → existing state file is ignored, pages re-processed."""
        img = make_png_image(tmp_path, "page_1.png")
        out_file = tmp_path / "output.txt"
        out_file.write_text("Image: page_1.png\nOld result", encoding="utf-8")

        fp = _compute_images_fingerprint(str(tmp_path), ["page_1.png"])
        state = {
            "schema_version": STATE_SCHEMA_VERSION,
            "images_fingerprint": fp,
            "max_page_attempts": 40,
            "run_status": "running",
            "pause_reason": None,
            "updated_at": "2026-01-01T00:00:00",
            "pages": {"page_1.png": {"status": "done", "attempts_used": 1, "last_error": None, "updated_at": "x"}},
        }
        state_file = tmp_path / f"{out_file.name}.ocr_state.json"
        state_file.write_text(json.dumps(state), encoding="utf-8")

        call_count = {"n": 0}

        def fake_post(*args, **kwargs):
            call_count["n"] += 1
            return make_mock_ocr_response("Fresh OCR")

        with patch("pdf2anki.pic2text.OPENROUTER_API_KEY", "fake-key"), \
             patch("pdf2anki.pic2text._http_post", side_effect=fake_post), \
             patch("pdf2anki.pic2text.time.sleep"):
            convert_images_to_text(
                images_dir=str(tmp_path),
                output_file=str(out_file),
                model_repeats=[("ocr/model", 1)],
                max_page_attempts=5,
                no_resume=True,
            )

        # Should have been called since we forced a fresh start
        assert call_count["n"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Extended test helpers
# ─────────────────────────────────────────────────────────────────────────────

def _create_page_images(tmp_path, count):
    """Create page_1.png .. page_{count}.png, return sorted name list."""
    for i in range(1, count + 1):
        make_png_image(tmp_path, f"page_{i}.png")
    return [f"page_{i}.png" for i in range(1, count + 1)]


def _sequential_side_effect(responses):
    """requests.post side_effect: pop responses in call order.

    Each entry is a str (success text) or an Exception (raised).
    Extra calls beyond the list return a generic success.
    """
    idx = {"i": 0}

    def _handler(*_args, **_kwargs):
        i = idx["i"]
        idx["i"] += 1
        if i < len(responses):
            item = responses[i]
            if isinstance(item, BaseException):
                raise item
            return make_mock_ocr_response(item)
        return make_mock_ocr_response(f"<extra call {i}>")

    return _handler


def _threadsafe_side_effect(responses):
    """Thread-safe variant of _sequential_side_effect."""
    lock = threading.Lock()
    count = [0]

    def _handler(*_args, **_kwargs):
        with lock:
            i = count[0]
            count[0] += 1
        if i < len(responses):
            item = responses[i]
            if isinstance(item, BaseException):
                raise item
            return make_mock_ocr_response(item)
        return make_mock_ocr_response(f"<extra call {i}>")

    return _handler


def _model_aware_side_effect(*, ocr_fn, judge_fn):
    """requests.post side_effect that distinguishes OCR from judge calls
    via the X-Title header.

    ocr_fn(call_index) -> str   for OCR calls  (X-Title: pdf2anki-ocr)
    judge_fn(call_index) -> str for judge calls (X-Title: pdf2anki-judge)
    """
    lock = threading.Lock()
    ocr_idx = [0]
    judge_idx = [0]

    def _handler(*_args, **kwargs):
        headers = kwargs.get("headers", {})
        title = headers.get("X-Title", "")

        if title == "pdf2anki-judge":
            with lock:
                i = judge_idx[0]
                judge_idx[0] += 1
            return make_mock_ocr_response(judge_fn(i))

        with lock:
            i = ocr_idx[0]
            ocr_idx[0] += 1
        return make_mock_ocr_response(ocr_fn(i))

    return _handler


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1 — Regression baseline: pin current sequential behaviour
# ─────────────────────────────────────────────────────────────────────────────

class TestSequentialRegressionBaseline:
    """Pin the sequential page-processing contract.

    Every test MUST pass on the unmodified codebase.  If any test breaks
    after a refactor the change violated an existing behavioural guarantee.
    """

    def test_output_ordering_5_pages(self, tmp_path):
        """5 pages → output sections appear in page_1 .. page_5 order."""
        _create_page_images(tmp_path, 5)
        out = str(tmp_path / "output.txt")
        responses = [f"OCR for page {i}" for i in range(1, 6)]

        with patch("pdf2anki.pic2text.OPENROUTER_API_KEY", "fake-key"), \
             patch("pdf2anki.pic2text._http_post",
                   side_effect=_sequential_side_effect(responses)), \
             patch("pdf2anki.pic2text.time.sleep"):
            convert_images_to_text(
                images_dir=str(tmp_path), output_file=out,
                model_repeats=[("m", 1)], max_page_attempts=3,
            )

        content = Path(out).read_text(encoding="utf-8")
        positions = [content.index(f"Image: page_{i}.png") for i in range(1, 6)]
        assert positions == sorted(positions), f"Sections out of order: {positions}"

    def test_output_text_matches_per_page(self, tmp_path):
        """Each page's OCR text lands under its correct section header."""
        _create_page_images(tmp_path, 3)
        out = str(tmp_path / "output.txt")
        texts = ["Alpha", "Beta", "Gamma"]

        with patch("pdf2anki.pic2text.OPENROUTER_API_KEY", "fake-key"), \
             patch("pdf2anki.pic2text._http_post",
                   side_effect=_sequential_side_effect(texts)), \
             patch("pdf2anki.pic2text.time.sleep"):
            convert_images_to_text(
                images_dir=str(tmp_path), output_file=out,
                model_repeats=[("m", 1)], max_page_attempts=3,
            )

        sections = _parse_output_sections(Path(out))
        assert sections["page_1.png"] == "Alpha"
        assert sections["page_2.png"] == "Beta"
        assert sections["page_3.png"] == "Gamma"

    def test_state_completed_after_full_success(self, tmp_path):
        """After all pages succeed the archived state shows run_status=completed
        and every page as done."""
        _create_page_images(tmp_path, 3)
        out = str(tmp_path / "output.txt")

        with patch("pdf2anki.pic2text.OPENROUTER_API_KEY", "fake-key"), \
             patch("pdf2anki.pic2text._http_post",
                   side_effect=_sequential_side_effect(["t1", "t2", "t3"])), \
             patch("pdf2anki.pic2text.time.sleep"):
            convert_images_to_text(
                images_dir=str(tmp_path), output_file=out,
                model_repeats=[("m", 1)], max_page_attempts=3,
            )

        archive = tmp_path / "log_archive"
        assert archive.exists(), "log_archive should exist after successful run"
        candidates = list(archive.glob("output.txt.ocr_state*.json"))
        assert candidates, "Archived state file expected"
        state = json.loads(candidates[0].read_text(encoding="utf-8"))
        assert state["run_status"] == "completed"
        for i in range(1, 4):
            assert state["pages"][f"page_{i}.png"]["status"] == "done"

    def test_state_after_pause(self, tmp_path):
        """Page 1 succeeds, page 2 exhausts attempts → pause.
        State: page_1=done, page_2=paused, page_3=pending."""
        import requests as req_lib

        _create_page_images(tmp_path, 3)
        out = str(tmp_path / "output.txt")
        responses = [
            "Good page 1",
            req_lib.exceptions.Timeout("t"),   # page2 att1
            req_lib.exceptions.Timeout("t"),   # page2 att2 → pause
        ]

        with patch("pdf2anki.pic2text.OPENROUTER_API_KEY", "fake-key"), \
             patch("pdf2anki.pic2text._http_post",
                   side_effect=_sequential_side_effect(responses)), \
             patch("pdf2anki.pic2text.time.sleep"):
            with pytest.raises(OCRPauseException):
                convert_images_to_text(
                    images_dir=str(tmp_path), output_file=out,
                    model_repeats=[("m", 1)], max_page_attempts=2,
                )

        sf = Path(out + ".ocr_state.json")
        assert sf.exists()
        state = json.loads(sf.read_text(encoding="utf-8"))
        assert state["run_status"] == "paused"
        assert state["pages"]["page_1.png"]["status"] == "done"
        assert state["pages"]["page_2.png"]["status"] == "paused"
        assert state["pages"]["page_3.png"]["status"] == "pending"

    def test_pause_blocks_subsequent_pages(self, tmp_path):
        """When page 1 pauses, pages 2-3 never see an API call."""
        import requests as req_lib

        _create_page_images(tmp_path, 3)
        out = str(tmp_path / "output.txt")
        call_count = {"n": 0}

        def tracking(*_a, **_k):
            call_count["n"] += 1
            raise req_lib.exceptions.Timeout("t")

        with patch("pdf2anki.pic2text.OPENROUTER_API_KEY", "fake-key"), \
             patch("pdf2anki.pic2text._http_post", side_effect=tracking), \
             patch("pdf2anki.pic2text.time.sleep"):
            with pytest.raises(OCRPauseException):
                convert_images_to_text(
                    images_dir=str(tmp_path), output_file=out,
                    model_repeats=[("m", 1)], max_page_attempts=2,
                )

        # Page 1 × 2 attempts = 2 calls; pages 2-3 never attempted.
        assert call_count["n"] == 2

    def test_resume_skips_done_processes_pending(self, tmp_path):
        """Pages 1-2 done in state → only pages 3-5 trigger API calls."""
        names = _create_page_images(tmp_path, 5)
        out = tmp_path / "output.txt"
        out.write_text(
            "Image: page_1.png\nOld1\n\nImage: page_2.png\nOld2",
            encoding="utf-8",
        )

        fp = _compute_images_fingerprint(str(tmp_path), names)
        state = {
            "schema_version": STATE_SCHEMA_VERSION,
            "images_fingerprint": fp,
            "max_page_attempts": 40,
            "run_status": "running",
            "pause_reason": None,
            "updated_at": "2026-01-01T00:00:00",
            "pages": {
                n: {
                    "status": "done" if i < 2 else "pending",
                    "attempts_used": 1 if i < 2 else 0,
                    "last_error": None,
                    "updated_at": "2026-01-01T00:00:00",
                }
                for i, n in enumerate(names)
            },
        }
        (tmp_path / f"{out.name}.ocr_state.json").write_text(
            json.dumps(state), encoding="utf-8",
        )

        call_count = {"n": 0}

        def counter(*_a, **_k):
            call_count["n"] += 1
            return make_mock_ocr_response(f"New {call_count['n']}")

        with patch("pdf2anki.pic2text.OPENROUTER_API_KEY", "fake-key"), \
             patch("pdf2anki.pic2text._http_post", side_effect=counter), \
             patch("pdf2anki.pic2text.time.sleep"):
            convert_images_to_text(
                images_dir=str(tmp_path), output_file=str(out),
                model_repeats=[("m", 1)], max_page_attempts=5,
            )

        assert call_count["n"] == 3  # pages 3, 4, 5
        content = out.read_text(encoding="utf-8")
        for i in range(1, 6):
            assert f"page_{i}.png" in content

    def test_retry_then_succeed(self, tmp_path):
        """One failed attempt followed by success → page is done."""
        import requests as req_lib

        _create_page_images(tmp_path, 1)
        out = str(tmp_path / "output.txt")
        responses = [
            req_lib.exceptions.Timeout("t"),
            "Success on retry",
        ]

        with patch("pdf2anki.pic2text.OPENROUTER_API_KEY", "fake-key"), \
             patch("pdf2anki.pic2text._http_post",
                   side_effect=_sequential_side_effect(responses)), \
             patch("pdf2anki.pic2text.time.sleep"):
            convert_images_to_text(
                images_dir=str(tmp_path), output_file=out,
                model_repeats=[("m", 1)], max_page_attempts=5,
            )

        assert "Success on retry" in Path(out).read_text(encoding="utf-8")

    def test_failed_page_absent_from_output(self, tmp_path):
        """A page that never succeeds does NOT appear in the output."""
        import requests as req_lib

        _create_page_images(tmp_path, 2)
        out = str(tmp_path / "output.txt")
        responses = [
            "Good page 1",
            req_lib.exceptions.Timeout("t"),   # page2 att1
            req_lib.exceptions.Timeout("t"),   # page2 att2 → pause
        ]

        with patch("pdf2anki.pic2text.OPENROUTER_API_KEY", "fake-key"), \
             patch("pdf2anki.pic2text._http_post",
                   side_effect=_sequential_side_effect(responses)), \
             patch("pdf2anki.pic2text.time.sleep"):
            with pytest.raises(OCRPauseException):
                convert_images_to_text(
                    images_dir=str(tmp_path), output_file=out,
                    model_repeats=[("m", 1)], max_page_attempts=2,
                )

        sections = _parse_output_sections(Path(out))
        assert "page_1.png" in sections
        assert _is_successful_ocr_text(sections["page_1.png"])
        assert "page_2.png" not in sections

    def test_judge_selects_from_repeats(self, tmp_path):
        """2 repeats + judge → output is the judge's selection."""
        _create_page_images(tmp_path, 1)
        out = str(tmp_path / "output.txt")

        responder = _model_aware_side_effect(
            ocr_fn=lambda i: f"OCR attempt {i}",
            judge_fn=lambda _: "Judge selected text",
        )

        with patch("pdf2anki.pic2text.OPENROUTER_API_KEY", "fake-key"), \
             patch("pdf2anki.pic2text._http_post", side_effect=responder), \
             patch("pdf2anki.pic2text.time.sleep"):
            convert_images_to_text(
                images_dir=str(tmp_path), output_file=out,
                model_repeats=[("m", 2)],
                judge_model="judge/m",
                max_page_attempts=3,
            )

        content = Path(out).read_text(encoding="utf-8")
        assert "Judge selected text" in content


# ─────────────────────────────────────────────────────────────────────────────
# Concurrency regression tests: pin page-level parallel behaviour
# ─────────────────────────────────────────────────────────────────────────────


class TestPageLevelParallelismSpec:
    """Regression tests for page-level concurrent processing via max_concurrent_pages.

    Naming convention
    -----------------
    ``test_par_*``        happy-path parallel behaviour
    ``test_par_pause_*``  pause / error propagation under concurrency
    ``test_par_resume_*`` resume after partial parallel run
    ``test_par_diag_*``   diagnostic: pinpoint specific concurrency bugs
    """

    # ── happy path ──────────────────────────────────────────────────────────

    def test_par_all_pages_complete(self, tmp_path):
        """All 10 pages complete with max_concurrent_pages=4."""
        _create_page_images(tmp_path, 10)
        out = str(tmp_path / "output.txt")
        responses = [f"Text {i}" for i in range(1, 11)]

        with patch("pdf2anki.pic2text.OPENROUTER_API_KEY", "fake-key"), \
             patch("pdf2anki.pic2text._http_post",
                   side_effect=_threadsafe_side_effect(responses)), \
             patch("pdf2anki.pic2text.time.sleep"):
            result = convert_images_to_text(
                images_dir=str(tmp_path), output_file=out,
                model_repeats=[("m", 1)], max_page_attempts=3,
                max_concurrent_pages=4,
            )

        assert result == out
        sections = _parse_output_sections(Path(out))
        assert len(sections) == 10

    def test_par_output_ordering(self, tmp_path):
        """Concurrent processing preserves page_1..page_10 order in output."""
        _create_page_images(tmp_path, 10)
        out = str(tmp_path / "output.txt")
        responses = [f"Text {i}" for i in range(1, 11)]

        with patch("pdf2anki.pic2text.OPENROUTER_API_KEY", "fake-key"), \
             patch("pdf2anki.pic2text._http_post",
                   side_effect=_threadsafe_side_effect(responses)), \
             patch("pdf2anki.pic2text.time.sleep"):
            convert_images_to_text(
                images_dir=str(tmp_path), output_file=out,
                model_repeats=[("m", 1)], max_page_attempts=3,
                max_concurrent_pages=4,
            )

        content = Path(out).read_text(encoding="utf-8")
        positions = [content.index(f"Image: page_{i}.png") for i in range(1, 11)]
        assert positions == sorted(positions), \
            "Output sections must stay in page order under concurrency"

    def test_par_state_all_done(self, tmp_path):
        """After parallel success, archived state has every page as done."""
        _create_page_images(tmp_path, 5)
        out = str(tmp_path / "output.txt")

        with patch("pdf2anki.pic2text.OPENROUTER_API_KEY", "fake-key"), \
             patch("pdf2anki.pic2text._http_post",
                   side_effect=_threadsafe_side_effect(
                       [f"T{i}" for i in range(1, 6)])), \
             patch("pdf2anki.pic2text.time.sleep"):
            convert_images_to_text(
                images_dir=str(tmp_path), output_file=out,
                model_repeats=[("m", 1)], max_page_attempts=3,
                max_concurrent_pages=3,
            )

        archive = tmp_path / "log_archive"
        candidates = list(archive.glob("output.txt.ocr_state*.json"))
        assert candidates
        state = json.loads(candidates[0].read_text(encoding="utf-8"))
        assert state["run_status"] == "completed"
        for i in range(1, 6):
            assert state["pages"][f"page_{i}.png"]["status"] == "done"

    def test_par_sequential_fallback(self, tmp_path):
        """max_concurrent_pages=1 produces identical output to sequential."""
        _create_page_images(tmp_path, 3)
        out = str(tmp_path / "output.txt")

        with patch("pdf2anki.pic2text.OPENROUTER_API_KEY", "fake-key"), \
             patch("pdf2anki.pic2text._http_post",
                   side_effect=_sequential_side_effect(["A", "B", "C"])), \
             patch("pdf2anki.pic2text.time.sleep"):
            convert_images_to_text(
                images_dir=str(tmp_path), output_file=out,
                model_repeats=[("m", 1)], max_page_attempts=3,
                max_concurrent_pages=1,
            )

        sections = _parse_output_sections(Path(out))
        assert sections == {
            "page_1.png": "A",
            "page_2.png": "B",
            "page_3.png": "C",
        }

    # ── pause under concurrency ─────────────────────────────────────────────

    def test_par_pause_raises_exception(self, tmp_path):
        """At least one page exhausting attempts raises OCRPauseException
        even when other pages were processed concurrently."""
        import requests as req_lib

        _create_page_images(tmp_path, 5)
        out = str(tmp_path / "output.txt")
        lock = threading.Lock()
        counter = [0]

        def _mixed(*_a, **_k):
            with lock:
                i = counter[0]
                counter[0] += 1
            if i < 3:
                return make_mock_ocr_response(f"OK {i}")
            raise req_lib.exceptions.Timeout("t")

        with patch("pdf2anki.pic2text.OPENROUTER_API_KEY", "fake-key"), \
             patch("pdf2anki.pic2text._http_post", side_effect=_mixed), \
             patch("pdf2anki.pic2text.time.sleep"):
            with pytest.raises(OCRPauseException):
                convert_images_to_text(
                    images_dir=str(tmp_path), output_file=out,
                    model_repeats=[("m", 1)], max_page_attempts=2,
                    max_concurrent_pages=4,
                )

    def test_par_pause_state_not_overridden(self, tmp_path):
        """After a parallel pause, run_status is 'paused' — a concurrent
        success must NOT reset it to 'running'.

        Diagnostic: if this fails, the state-mutation path has no lock or
        the pause flag is checked too late.
        """
        import requests as req_lib

        _create_page_images(tmp_path, 6)
        out = str(tmp_path / "output.txt")
        lock = threading.Lock()
        counter = [0]

        def _mixed(*_a, **_k):
            with lock:
                i = counter[0]
                counter[0] += 1
            if i < 3:
                return make_mock_ocr_response(f"OK {i}")
            raise req_lib.exceptions.Timeout("t")

        with patch("pdf2anki.pic2text.OPENROUTER_API_KEY", "fake-key"), \
             patch("pdf2anki.pic2text._http_post", side_effect=_mixed), \
             patch("pdf2anki.pic2text.time.sleep"):
            with pytest.raises(OCRPauseException):
                convert_images_to_text(
                    images_dir=str(tmp_path), output_file=out,
                    model_repeats=[("m", 1)], max_page_attempts=2,
                    max_concurrent_pages=3,
                )

        sf = Path(out + ".ocr_state.json")
        assert sf.exists()
        state = json.loads(sf.read_text(encoding="utf-8"))
        assert state["run_status"] == "paused", \
            "Concurrent success must NOT reset run_status from paused to running"

    def test_par_pause_successful_pages_in_output(self, tmp_path):
        """Pages that completed before the pause appear in the output."""
        import requests as req_lib

        _create_page_images(tmp_path, 4)
        out = str(tmp_path / "output.txt")
        lock = threading.Lock()
        counter = [0]

        def _mixed(*_a, **_k):
            with lock:
                i = counter[0]
                counter[0] += 1
            if i < 2:
                return make_mock_ocr_response(f"Good {i}")
            raise req_lib.exceptions.Timeout("t")

        with patch("pdf2anki.pic2text.OPENROUTER_API_KEY", "fake-key"), \
             patch("pdf2anki.pic2text._http_post", side_effect=_mixed), \
             patch("pdf2anki.pic2text.time.sleep"):
            with pytest.raises(OCRPauseException):
                convert_images_to_text(
                    images_dir=str(tmp_path), output_file=out,
                    model_repeats=[("m", 1)], max_page_attempts=2,
                    max_concurrent_pages=3,
                )

        sections = _parse_output_sections(Path(out))
        successful = sum(
            1 for v in sections.values() if _is_successful_ocr_text(v)
        )
        assert successful >= 1, \
            "At least one successfully OCR'd page must survive in output"

    # ── resume after parallel partial run ────────────────────────────────────

    def test_par_resume_after_partial(self, tmp_path):
        """Resume with pages 1-3 done → only pages 4-6 trigger API calls."""
        names = _create_page_images(tmp_path, 6)
        out = tmp_path / "output.txt"
        out.write_text(
            "\n\n".join(f"Image: page_{i}.png\nOld {i}" for i in range(1, 4)),
            encoding="utf-8",
        )

        fp = _compute_images_fingerprint(str(tmp_path), names)
        state = {
            "schema_version": STATE_SCHEMA_VERSION,
            "images_fingerprint": fp,
            "max_page_attempts": 40,
            "run_status": "running",
            "pause_reason": None,
            "updated_at": "2026-01-01T00:00:00",
            "pages": {
                n: {
                    "status": "done" if i < 3 else "pending",
                    "attempts_used": 1 if i < 3 else 0,
                    "last_error": None,
                    "updated_at": "2026-01-01T00:00:00",
                }
                for i, n in enumerate(names)
            },
        }
        (tmp_path / f"{out.name}.ocr_state.json").write_text(
            json.dumps(state), encoding="utf-8",
        )

        lock = threading.Lock()
        api_calls = [0]

        def counting(*_a, **_k):
            with lock:
                api_calls[0] += 1
            return make_mock_ocr_response(f"New {api_calls[0]}")

        with patch("pdf2anki.pic2text.OPENROUTER_API_KEY", "fake-key"), \
             patch("pdf2anki.pic2text._http_post", side_effect=counting), \
             patch("pdf2anki.pic2text.time.sleep"):
            convert_images_to_text(
                images_dir=str(tmp_path), output_file=str(out),
                model_repeats=[("m", 1)], max_page_attempts=5,
                max_concurrent_pages=3,
            )

        assert api_calls[0] == 3  # only pages 4, 5, 6
        sections = _parse_output_sections(out)
        assert len(sections) == 6

    # ── diagnostics: pinpoint specific concurrency bugs ──────────────────────

    def test_par_diag_no_missing_pages(self, tmp_path):
        """No pages silently lost during concurrent output writes.

        Diagnostic: if this fails but test_par_all_pages_complete passes,
        _write_output_sections_atomic or page_texts has a race condition.
        """
        _create_page_images(tmp_path, 20)
        out = str(tmp_path / "output.txt")
        responses = [f"Page {i}" for i in range(1, 21)]

        with patch("pdf2anki.pic2text.OPENROUTER_API_KEY", "fake-key"), \
             patch("pdf2anki.pic2text._http_post",
                   side_effect=_threadsafe_side_effect(responses)), \
             patch("pdf2anki.pic2text.time.sleep"):
            convert_images_to_text(
                images_dir=str(tmp_path), output_file=out,
                model_repeats=[("m", 1)], max_page_attempts=3,
                max_concurrent_pages=5,
            )

        sections = _parse_output_sections(Path(out))
        for i in range(1, 21):
            assert f"page_{i}.png" in sections, \
                f"page_{i}.png missing — likely lost during concurrent write"

    def test_par_diag_state_valid_json(self, tmp_path):
        """State file is valid JSON after concurrent processing.

        Diagnostic: if this fails, _write_json_atomic has a temp-file
        collision or dict mutation during serialisation.
        """
        _create_page_images(tmp_path, 8)
        out = str(tmp_path / "output.txt")

        with patch("pdf2anki.pic2text.OPENROUTER_API_KEY", "fake-key"), \
             patch("pdf2anki.pic2text._http_post",
                   side_effect=_threadsafe_side_effect(
                       [f"T{i}" for i in range(1, 9)])), \
             patch("pdf2anki.pic2text.time.sleep"):
            convert_images_to_text(
                images_dir=str(tmp_path), output_file=out,
                model_repeats=[("m", 1)], max_page_attempts=3,
                max_concurrent_pages=4,
            )

        for jf in tmp_path.rglob("*.json"):
            raw = jf.read_text(encoding="utf-8")
            try:
                json.loads(raw)
            except json.JSONDecodeError:
                pytest.fail(f"Corrupt JSON in {jf}")

    def test_par_diag_no_deadlock(self, tmp_path):
        """20 pages × 2 repeats + judge with 4 concurrent completes
        within pytest timeout — no thread-pool starvation.

        Diagnostic: if this hangs, the API executor is too small for
        the combined page × repeat load, or a lock ordering bug exists.
        """
        _create_page_images(tmp_path, 20)
        out = str(tmp_path / "output.txt")

        responder = _model_aware_side_effect(
            ocr_fn=lambda i: f"OCR {i}",
            judge_fn=lambda _: "Judged",
        )

        with patch("pdf2anki.pic2text.OPENROUTER_API_KEY", "fake-key"), \
             patch("pdf2anki.pic2text._http_post", side_effect=responder), \
             patch("pdf2anki.pic2text.time.sleep"):
            convert_images_to_text(
                images_dir=str(tmp_path), output_file=out,
                model_repeats=[("m", 2)],
                judge_model="judge/m",
                max_page_attempts=3,
                max_concurrent_pages=4,
            )

        sections = _parse_output_sections(Path(out))
        assert len(sections) == 20
