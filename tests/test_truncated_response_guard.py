"""Guard against responses cut off at the output-token limit.

A model that hits its token ceiling has almost always run away into a repetition
loop. Before this guard, `_is_successful_ocr_text()` only rejected the
`[ERROR:`/`[INFO:` prefixes, so such a blob counted as a finished page: it was
written to the .txt, marked done in the resume state, and handed to the judge --
whose call then cost ~20x a normal one.
"""
import json
from unittest.mock import patch

import pytest

from pdf2anki import pic2text


def _response(content, finish_reason, completion_tokens=None):
    class R:
        status_code = 200

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {
                "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
                "usage": {"completion_tokens": completion_tokens},
            }
    return R()


class TestOcrTruncation:
    def test_truncated_response_becomes_an_error(self, tmp_path):
        log = tmp_path / "ocr.log"
        with patch.object(pic2text, "_http_post",
                          return_value=_response("BLA " * 40000, "length", 65532)), \
             patch.object(pic2text, "_image_to_base64", return_value="x"):
            out = pic2text._post_ocr_request("m/x", "x", str(log), "page_5.png", 1)
        assert out.startswith("[ERROR:")
        assert "finish_reason=length" in out
        assert "65532" in out
        # and therefore does NOT count as a finished page
        assert not pic2text._is_successful_ocr_text(out)

    def test_normal_response_is_untouched(self, tmp_path):
        log = tmp_path / "ocr.log"
        with patch.object(pic2text, "_http_post",
                          return_value=_response("# Folie\n\nText", "stop", 200)), \
             patch.object(pic2text, "_image_to_base64", return_value="x"):
            out = pic2text._post_ocr_request("m/x", "x", str(log), "page_1.png", 1)
        assert out == "# Folie\n\nText"
        assert pic2text._is_successful_ocr_text(out)

    def test_missing_finish_reason_is_not_treated_as_truncated(self, tmp_path):
        """Some providers omit the field; absence must not fail a good page."""
        log = tmp_path / "ocr.log"
        with patch.object(pic2text, "_http_post",
                          return_value=_response("Text", None, 12)), \
             patch.object(pic2text, "_image_to_base64", return_value="x"):
            out = pic2text._post_ocr_request("m/x", "x", str(log), "page_1.png", 1)
        assert out == "Text"
        assert pic2text._is_successful_ocr_text(out)

    def test_empty_content_still_reported_as_info(self, tmp_path):
        log = tmp_path / "ocr.log"
        with patch.object(pic2text, "_http_post",
                          return_value=_response("", "stop", 0)), \
             patch.object(pic2text, "_image_to_base64", return_value="x"):
            out = pic2text._post_ocr_request("m/x", "x", str(log), "page_1.png", 1)
        assert out.startswith("[INFO:")
        assert not pic2text._is_successful_ocr_text(out)


class TestJudgeTruncation:
    def _judge(self, tmp_path, content, finish_reason):
        log = tmp_path / "judge.log"
        with patch.object(pic2text, "_http_post",
                          return_value=_response(content, finish_reason, 65535)):
            return pic2text._post_judge_request(
                judge_model="m/judge",
                model_outputs=["Kandidat A voll", "Kandidat B voll"],
                image_name="page_5.png",
                model_info_for_judge=[("m/x", 1), ("m/x", 2)],
                judge_decision_log_file=str(log),
            )

    def test_truncated_verdict_falls_back_and_is_not_marked_judged(self, tmp_path):
        text, judged_ok = self._judge(tmp_path, "Kandidat A vo", "length")
        assert judged_ok is False, "a truncated verdict must schedule a re-judge"
        assert text == "Kandidat A voll", "must fall back to a whole candidate"

    def test_complete_verdict_is_accepted(self, tmp_path):
        text, judged_ok = self._judge(tmp_path, "Kandidat B voll", "stop")
        assert judged_ok is True
        assert text == "Kandidat B voll"
