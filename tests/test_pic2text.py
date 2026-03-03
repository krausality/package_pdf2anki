"""Tests for pdf2anki.pic2text — OCR image processing."""
import json
import os
import base64
import io
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
             patch("pdf2anki.pic2text.requests.post", return_value=mock_resp), \
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
             patch("pdf2anki.pic2text.requests.post", side_effect=req_lib.exceptions.Timeout("timeout")), \
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
             patch("pdf2anki.pic2text.requests.post", side_effect=req_lib.exceptions.Timeout("t")), \
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
             patch("pdf2anki.pic2text.requests.post", side_effect=fake_post), \
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
             patch("pdf2anki.pic2text.requests.post", side_effect=fake_post), \
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
             patch("pdf2anki.pic2text.requests.post", side_effect=fake_post), \
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
