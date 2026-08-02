"""Tests for `pdf2anki pdf2text --recursive`.

Covers the two things the flag actually changes:
  1. which PDFs are discovered (whole tree, minus our own artifact folders)
  2. where each PDF's output lands (next to the PDF, mirroring the source tree)

No PDFs are rendered and no API calls are made: the two heavy steps
(`pdf_to_images`, `_run_single_dir_ocr`) are patched out and only their
arguments are inspected.
"""
import argparse
import concurrent.futures
import pytest
from pathlib import Path
from unittest.mock import patch

import pdf2anki.core as core


def _tree(root: Path):
    """Build a folder layout shaped like a real lecture/exercise directory."""
    (root / "Vorlesungsfolien").mkdir(parents=True)
    (root / "Hausübungen" / "Hausübung_01").mkdir(parents=True)
    (root / "Hausübungen" / "Hausübung_02").mkdir(parents=True)
    # our own artifacts -- must never be treated as input
    (root / "pdf2pic" / "Kapitel-1").mkdir(parents=True)
    (root / "log_archive").mkdir(parents=True)

    created = [
        root / "Organisatorisches.pdf",
        root / "Vorlesungsfolien" / "Kapitel-1.pdf",
        root / "Hausübungen" / "Hausübung_01" / "HA01.pdf",
        root / "Hausübungen" / "Hausübung_02" / "HA02.pdf",
    ]
    decoys = [
        root / "pdf2pic" / "Kapitel-1" / "stale.pdf",
        root / "log_archive" / "old.pdf",
    ]
    for p in created + decoys:
        p.write_bytes(b"%PDF-1.4\n")
    return created, decoys


def _args(pdf_path, **over):
    base = dict(
        pdf_path=str(pdf_path), output_dir=None, rectangles=[], output_file=None,
        recursive=True, model=["m/x"], repeat=[1], judge_model=None,
        judge_mode="authoritative", ensemble_strategy=None, trust_score=None,
        judge_with_image=False, no_resume=False, max_page_attempts=40,
        max_concurrent_pages=1, max_image_kb=800, verbose=False,
    )
    base.update(over)
    return argparse.Namespace(**base)


@pytest.fixture
def run_capture(tmp_path, monkeypatch):
    """Run pdf_to_text with the heavy steps stubbed; return recorded call args."""
    seen = []

    def fake_images(args):
        seen.append(("images", Path(args.pdf_path), Path(args.output_dir)))

    def fake_ocr(args):
        seen.append(("ocr", Path(args.images_dir), Path(args.output_file)))

    def run(root, **over):
        monkeypatch.setattr(core, "pdf_to_images", fake_images)
        monkeypatch.setattr(core, "_run_single_dir_ocr", fake_ocr)
        monkeypatch.setattr(core, "load_config", lambda: {})
        monkeypatch.setattr(core, "_apply_ocr_presets_and_resolve_model", lambda a, c: None)
        # ProcessPoolExecutor would spawn fresh interpreters that don't see the
        # patches above; a thread pool exercises the same code path in-process.
        monkeypatch.setattr(core.concurrent.futures, "ProcessPoolExecutor",
                            concurrent.futures.ThreadPoolExecutor)
        core.pdf_to_text(_args(root, **over))
        return seen

    return run


class TestDiscovery:
    def test_recursive_finds_pdfs_at_every_depth(self, tmp_path, run_capture):
        created, _ = _tree(tmp_path)
        seen = run_capture(tmp_path)
        found = {p for kind, p, _ in seen if kind == "images"}
        assert found == set(created)

    def test_skips_own_artifact_folders(self, tmp_path, run_capture):
        _, decoys = _tree(tmp_path)
        seen = run_capture(tmp_path)
        found = {p for kind, p, _ in seen if kind == "images"}
        for d in decoys:
            assert d not in found, f"{d} must not be treated as input"

    def test_without_recursive_only_top_level(self, tmp_path, run_capture):
        created, _ = _tree(tmp_path)
        seen = run_capture(tmp_path, recursive=False)
        found = {p for kind, p, _ in seen if kind == "images"}
        assert found == {tmp_path / "Organisatorisches.pdf"}

    def test_empty_tree_returns_quietly(self, tmp_path, run_capture, capsys):
        seen = run_capture(tmp_path)
        assert seen == []
        assert "No PDF files found" in capsys.readouterr().out


class TestOutputLayout:
    def test_outputs_land_next_to_each_pdf(self, tmp_path, run_capture):
        created, _ = _tree(tmp_path)
        seen = run_capture(tmp_path)

        img_for = {p: out for kind, p, out in seen if kind == "images"}
        txt_for = {img: out for kind, img, out in seen if kind == "ocr"}

        for pdf in created:
            img_dir = img_for[pdf]
            assert img_dir == pdf.parent / "pdf2pic" / pdf.stem
            assert txt_for[img_dir] == pdf.parent / f"{pdf.stem}.txt"

    def test_layout_matches_manual_per_folder_run(self, tmp_path, run_capture):
        """Recursive output must be identical to `cd <dir> && pdf2text .`,
        otherwise previously processed folders would not resume."""
        created, _ = _tree(tmp_path)
        seen = run_capture(tmp_path)
        recursive_layout = {(p, out) for kind, p, out in seen if kind == "images"}

        seen.clear()
        sub = tmp_path / "Hausübungen" / "Hausübung_01"
        monkey_root = sub
        # non-recursive run *from inside* that folder, cwd-relative like the CLI
        import os
        prev = os.getcwd()
        try:
            os.chdir(sub)
            run_capture(monkey_root, recursive=False)
        finally:
            os.chdir(prev)
        manual = {(p, out) for kind, p, out in seen if kind == "images"}

        pdf = sub / "HA01.pdf"
        assert (pdf, sub / "pdf2pic" / "HA01") in recursive_layout
        assert any(out == sub / "pdf2pic" / "HA01" for _, out in manual)


class TestGuards:
    def test_recursive_with_explicit_output_dir_exits(self, tmp_path, run_capture):
        _tree(tmp_path)
        with pytest.raises(SystemExit) as exc:
            run_capture(tmp_path, output_dir=str(tmp_path / "imgs"))
        assert exc.value.code == 1

    def test_recursive_with_explicit_output_file_exits(self, tmp_path, run_capture):
        _tree(tmp_path)
        with pytest.raises(SystemExit) as exc:
            run_capture(tmp_path, output_file=str(tmp_path / "out.txt"))
        assert exc.value.code == 1

    def test_recursive_on_single_pdf_warns_and_ignores(self, tmp_path, run_capture, capsys):
        created, _ = _tree(tmp_path)
        seen = run_capture(created[0])
        assert "--recursive has no effect on a single PDF file" in capsys.readouterr().out
        assert len([1 for kind, *_ in seen if kind == "images"]) == 1
