"""Tests for pdf2anki.pdf2pic — pdf-to-image conversion."""
import os
import pytest
from unittest.mock import MagicMock, patch, call

from pdf2anki.pdf2pic import (
    parse_rectangle,
    _is_usable_image_file,
    find_acceptable_dpi,
    convert_pdf_to_images,
    create_recrop_pdf,
)


# ─────────────────────────────────────────────────────────────────────────────
# parse_rectangle
# ─────────────────────────────────────────────────────────────────────────────

class TestParseRectangle:
    def test_valid_string(self):
        assert parse_rectangle("10,20,100,200") == (10, 20, 100, 200)

    def test_zeros(self):
        assert parse_rectangle("0,0,0,0") == (0, 0, 0, 0)

    def test_too_few_coords_raises(self):
        with pytest.raises(ValueError):
            parse_rectangle("10,20,100")

    def test_too_many_coords_raises(self):
        with pytest.raises(ValueError):
            parse_rectangle("10,20,100,200,300")

    def test_non_integer_raises(self):
        with pytest.raises(ValueError):
            parse_rectangle("a,b,c,d")


# ─────────────────────────────────────────────────────────────────────────────
# _is_usable_image_file
# ─────────────────────────────────────────────────────────────────────────────

class TestIsUsableImageFile:
    def test_nonexistent_returns_false(self, tmp_path):
        assert _is_usable_image_file(str(tmp_path / "nope.png")) is False

    def test_empty_file_returns_false(self, tmp_path):
        f = tmp_path / "empty.png"
        f.write_bytes(b"")
        assert _is_usable_image_file(str(f)) is False

    def test_valid_png_returns_true(self, tmp_path):
        """Create a minimal valid 1x1 PNG."""
        from PIL import Image
        img_path = tmp_path / "valid.png"
        img = Image.new("RGB", (1, 1), color=(255, 0, 0))
        img.save(str(img_path), format="PNG")
        assert _is_usable_image_file(str(img_path)) is True

    def test_corrupt_bytes_returns_false(self, tmp_path):
        f = tmp_path / "bad.png"
        f.write_bytes(b"\x89PNG CORRUPT DATA")
        assert _is_usable_image_file(str(f)) is False


# ─────────────────────────────────────────────────────────────────────────────
# find_acceptable_dpi
# ─────────────────────────────────────────────────────────────────────────────

class TestFindAcceptableDpi:
    def _make_mock_page(self, size_kb):
        """Build a mock fitz page whose rendered pixmap produces size_kb on disk."""
        mock_pix = MagicMock()
        mock_pix.width = 100
        mock_pix.height = 100
        mock_pix.samples = b"\x00" * (100 * 100 * 3)

        mock_page = MagicMock()
        mock_page.get_pixmap.return_value = mock_pix
        return mock_page

    def test_returns_int(self, tmp_path):
        """find_acceptable_dpi always returns an integer."""
        mock_page = self._make_mock_page(760)
        output_path = str(tmp_path / "page.png")

        with patch("pdf2anki.pdf2pic.fitz") as mock_fitz, \
             patch("pdf2anki.pdf2pic.Image") as mock_image, \
             patch("pdf2anki.pdf2pic.os.path.getsize", return_value=760 * 1024), \
             patch("pdf2anki.pdf2pic.os.remove"):
            mock_fitz.Matrix.return_value = MagicMock()
            mock_img = MagicMock()
            mock_image.frombytes.return_value = mock_img

            result = find_acceptable_dpi(mock_page, output_path, 300)

        assert isinstance(result, int)
        assert result >= 1

    def test_dpi_bounded_by_initial(self, tmp_path):
        """Returned DPI must not exceed initial_dpi."""
        mock_page = self._make_mock_page(400)
        output_path = str(tmp_path / "page.png")

        with patch("pdf2anki.pdf2pic.fitz") as mock_fitz, \
             patch("pdf2anki.pdf2pic.Image") as mock_image, \
             patch("pdf2anki.pdf2pic.os.path.getsize", return_value=400 * 1024), \
             patch("pdf2anki.pdf2pic.os.remove"):
            mock_fitz.Matrix.return_value = MagicMock()
            mock_image.frombytes.return_value = MagicMock()

            result = find_acceptable_dpi(mock_page, output_path, 300)

        assert result <= 300


# ─────────────────────────────────────────────────────────────────────────────
# convert_pdf_to_images — no rectangles
# ─────────────────────────────────────────────────────────────────────────────

class TestConvertPdfToImages:
    def _build_pdf_mock(self, num_pages=2):
        """Create a minimal mock pymupdf.open() context manager."""
        mock_pix = MagicMock()
        mock_pix.width = 100
        mock_pix.height = 100
        mock_pix.samples = b"\x00" * (100 * 100 * 3)

        mock_page = MagicMock()
        mock_page.get_pixmap.return_value = mock_pix

        mock_pdf = MagicMock()
        mock_pdf.__len__ = lambda self: num_pages
        mock_pdf.__iter__ = lambda self: iter([mock_page] * num_pages)
        mock_pdf.__enter__ = lambda self: self
        mock_pdf.__exit__ = MagicMock(return_value=False)
        return mock_pdf

    def test_creates_one_image_per_page(self, tmp_path):
        mock_pdf = self._build_pdf_mock(num_pages=3)

        with patch("pdf2anki.pdf2pic.pymupdf") as mock_pymupdf, \
             patch("pdf2anki.pdf2pic.fitz") as mock_fitz, \
             patch("pdf2anki.pdf2pic.Image") as mock_image, \
             patch("pdf2anki.pdf2pic.find_acceptable_dpi", return_value=150), \
             patch("pdf2anki.pdf2pic.os.path.getsize", return_value=760 * 1024):
            mock_pymupdf.open.return_value = mock_pdf
            mock_fitz.Matrix.return_value = MagicMock()
            mock_img = MagicMock()
            mock_image.frombytes.return_value = mock_img

            result = convert_pdf_to_images(
                pdf_path="fake.pdf",
                output_dir=str(tmp_path),
                target_dpi=150,
            )

        assert len(result) == 3
        for path in result:
            assert "page_" in path and path.endswith(".png")

    def test_resume_existing_skips_valid_images(self, tmp_path):
        """With resume_existing=True, already-valid images are reused."""
        from PIL import Image as PILImage

        # Pre-create a valid page_1.png
        valid_img = PILImage.new("RGB", (10, 10))
        valid_img.save(str(tmp_path / "page_1.png"))

        mock_pdf = self._build_pdf_mock(num_pages=1)

        with patch("pdf2anki.pdf2pic.pymupdf") as mock_pymupdf, \
             patch("pdf2anki.pdf2pic.fitz"), \
             patch("pdf2anki.pdf2pic.Image") as mock_image, \
             patch("pdf2anki.pdf2pic.find_acceptable_dpi", return_value=150):
            mock_pymupdf.open.return_value = mock_pdf
            mock_image.frombytes.return_value = MagicMock()

            result = convert_pdf_to_images(
                pdf_path="fake.pdf",
                output_dir=str(tmp_path),
                target_dpi=150,
                resume_existing=True,
            )

        assert len(result) == 1
        assert result[0].endswith("page_1.png")

    def test_output_dir_created_if_missing(self, tmp_path):
        new_dir = str(tmp_path / "subdir" / "images")
        mock_pdf = self._build_pdf_mock(num_pages=1)

        with patch("pdf2anki.pdf2pic.pymupdf") as mock_pymupdf, \
             patch("pdf2anki.pdf2pic.fitz"), \
             patch("pdf2anki.pdf2pic.Image") as mock_image, \
             patch("pdf2anki.pdf2pic.find_acceptable_dpi", return_value=72):
            mock_pymupdf.open.return_value = mock_pdf
            mock_image.frombytes.return_value = MagicMock()

            convert_pdf_to_images("fake.pdf", new_dir, target_dpi=72)

        assert os.path.isdir(new_dir)

    def test_with_rectangles_creates_crops(self, tmp_path):
        """When rectangles provided, crop files should be returned."""
        mock_pix = MagicMock()
        mock_pix.width = 300
        mock_pix.height = 400
        mock_pix.samples = b"\x00" * (300 * 400 * 3)

        mock_page = MagicMock()
        mock_page.get_pixmap.return_value = mock_pix

        mock_pdf = MagicMock()
        mock_pdf.__len__ = lambda self: 1
        mock_pdf.__iter__ = lambda self: iter([mock_page])
        mock_pdf.__enter__ = lambda self: self
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch("pdf2anki.pdf2pic.pymupdf") as mock_pymupdf, \
             patch("pdf2anki.pdf2pic.fitz") as mock_fitz, \
             patch("pdf2anki.pdf2pic.Image") as mock_image, \
             patch("pdf2anki.pdf2pic.create_recrop_pdf"):
            mock_pymupdf.open.return_value = mock_pdf
            mock_fitz.Matrix.return_value = MagicMock()
            mock_img = MagicMock()
            mock_img.size = (300, 400)
            mock_image.frombytes.return_value = mock_img
            mock_cropped = MagicMock()
            mock_img.crop.return_value = mock_cropped

            result = convert_pdf_to_images(
                pdf_path="fake.pdf",
                output_dir=str(tmp_path),
                target_dpi=300,
                rectangles=[(0, 0, 150, 200)],
            )

        assert len(result) == 1
        assert "crop" in result[0]


# ─────────────────────────────────────────────────────────────────────────────
# create_recrop_pdf
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateRecropPdf:
    def test_creates_pdf_from_crops(self, tmp_path):
        from PIL import Image as PILImage

        # Create a real portrait image
        img_path = tmp_path / "crop_1.jpg"
        PILImage.new("RGB", (100, 200)).save(str(img_path), format="JPEG")

        with patch("pdf2anki.pdf2pic.fitz") as mock_fitz:
            mock_doc = MagicMock()
            mock_fitz.open.return_value = mock_doc
            mock_page = MagicMock()
            mock_doc.new_page.return_value = mock_page

            create_recrop_pdf([str(img_path)], str(tmp_path), "mydoc")

        mock_doc.save.assert_called_once()

    def test_landscape_image_uses_landscape_page(self, tmp_path):
        from PIL import Image as PILImage

        img_path = tmp_path / "crop_wide.jpg"
        PILImage.new("RGB", (300, 100)).save(str(img_path), format="JPEG")  # wider than tall

        with patch("pdf2anki.pdf2pic.fitz") as mock_fitz:
            mock_doc = MagicMock()
            mock_fitz.open.return_value = mock_doc
            mock_page = MagicMock()
            mock_doc.new_page.return_value = mock_page

            create_recrop_pdf([str(img_path)], str(tmp_path), "mydoc")

        # Landscape: width=842, height=595
        mock_doc.new_page.assert_called_once_with(width=842, height=595)
