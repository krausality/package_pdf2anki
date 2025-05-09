"""
This software is licensed under the terms specified in LICENSE.txt,
authored by Martin Krause.

Usage is limited to:
- Students enrolled at accredited institutions
- Individuals with an annual income below 15,000€
- Personal desktop PC automation tasks

For commercial usage, including server deployments, please contact:
martinkrausemedia@gmail.com

Refer to the NOTICE.txt file for dependencies and third-party libraries used.
"""

import pymupdf  # PyMuPDF also known as fitz
import fitz     # We'll use "fitz" for certain PDF-specific calls
from PIL import Image
import os
import sys
from typing import List, Tuple, Optional

def find_acceptable_dpi(
    page,
    output_path: str,
    initial_dpi: int,
    format_str: str = "PNG",
    verbose: bool = False # Add verbose parameter
) -> int:
    """
    Iteratively find a DPI that results in an image size between ~750KB and 800KB,
    starting with 'initial_dpi'. Uses a divide-and-conquer approach.
    """
    # No need for local imports if they are global

    lower_dpi = 50
    upper_dpi = initial_dpi
    acceptable_dpi = initial_dpi

    while lower_dpi <= upper_dpi:
        mid_dpi = (lower_dpi + upper_dpi) // 2
        if mid_dpi <= 0: # Avoid zero or negative DPI
             break
        zoom = mid_dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

        # Save temporarily to check size
        temp_path = output_path + ".temp"
        try:
            img.save(temp_path, format=format_str, dpi=(mid_dpi, mid_dpi))
            size_kb = os.path.getsize(temp_path) / 1024

            if verbose: # Check verbose flag before printing debug info
                print(f"[DEBUG] Tried {mid_dpi} dpi => {size_kb:.1f} KB")

            if 750 <= size_kb < 800:
                if verbose: # Check verbose flag
                    print(f"[DEBUG] Found acceptable size {size_kb:.1f} KB at {mid_dpi} dpi")
                acceptable_dpi = mid_dpi
                break
            elif size_kb >= 800:
                # reduce dpi
                upper_dpi = mid_dpi - 1
            else:
                # size < 750
                acceptable_dpi = mid_dpi  # might still be best so far
                lower_dpi = mid_dpi + 1
        finally:
             # Clean up temporary file
            if os.path.exists(temp_path):
                os.remove(temp_path)

    # Ensure acceptable_dpi is within reasonable bounds
    acceptable_dpi = max(lower_dpi if lower_dpi > 50 else 50, acceptable_dpi)
    acceptable_dpi = min(initial_dpi, acceptable_dpi)
    acceptable_dpi = max(1, acceptable_dpi) # Ensure DPI is at least 1

    return acceptable_dpi

def convert_pdf_to_images(
    pdf_path: str,
    output_dir: str,
    target_dpi: int = 300,
    rectangles: Optional[List[Tuple[int, int, int, int]]] = None,
    verbose: bool = False # Add verbose parameter here
) -> List[str]:
    """
    Convert each page of a PDF to a full-page image at 'target_dpi'.
    
    If 'rectangles' are specified, each rectangle is given in 300-dpi coordinates.
    For maximum cropping quality:
      1) We first create a 300-dpi full-page image as before.
      2) We convert the rectangle coordinates to percentages relative to
         this 300-dpi image's width/height.
      3) We then re-render that same PDF page at high resolution (capped at 2400 dpi)
         and crop at those same percentages to achieve maximum detail.
      4) We save each cropped image at the same high dpi (up to 2400).
      5) Finally, we assemble all cropped images into 'recrop.pdf'.

    Args:
        pdf_path: Path to the PDF file
        output_dir: Directory to store the generated images
        target_dpi: The DPI for the main page images, defaults to 300
        rectangles: Optional list of (left, top, right, bottom) tuples in 300-dpi coordinates
    
    Returns:
        List[str]: Paths to all generated images (full-page + cropped)
    """

    # Extract the base name of the PDF file
    pdf_base_name = os.path.splitext(os.path.basename(pdf_path))[0]  # e.g., "example"

    os.makedirs(output_dir, exist_ok=True)
    images = []         # paths to all generated images
    cropped_images = [] # paths to only the cropped images

    # We'll treat rectangle coords as 300-dpi-based. If user has rectangles,
    # we do a second pass at up to 2400 dpi for maximum detail.
    # e.g. if the user asked for target_dpi=600, we can still go up to 2400 for cropping.
    # If user asked for target_dpi=1200, we keep 1200 for the full page,
    # but for cropping we do min(2400, 1200) -> 1200. 
    # Or if user asked for 72 (very low), we still do 2400 for the cropping.
    hi_dpi = max(target_dpi, 300)  # at least 300
    if rectangles:
        hi_dpi = min(1200, max(300, target_dpi * 10))
        # ^ For demonstration, we pick 'target_dpi * 10' just as an example factor.
        #   Or simply: hi_dpi = 2400  # always, if rectangles exist

    with pymupdf.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf, start=1):
            # ======================
            # 1) Render at target_dpi for the full-page image
            # ======================
            zoom_300 = target_dpi / 72.0
            mat_300 = fitz.Matrix(zoom_300, zoom_300)
            pix_300 = page.get_pixmap(matrix=mat_300, alpha=False)
            img_300 = Image.frombytes("RGB", (pix_300.width, pix_300.height), pix_300.samples)

            # Save the main full-page image
            img_path = os.path.join(output_dir, f"page_{page_num}.png")

            # If rectangles are provided, skip the regular page save
            if not rectangles:            
                # ======================
                # Use the new helper to find acceptable dpi
                # ======================
                # Pass verbose flag to the helper function
                chosen_dpi = find_acceptable_dpi(page, img_path, target_dpi, "PNG", verbose=verbose)
                zoom_chosen = chosen_dpi / 72.0
                mat_chosen = fitz.Matrix(zoom_chosen, zoom_chosen)
                pix_chosen = page.get_pixmap(matrix=mat_chosen, alpha=False)
                img_chosen = Image.frombytes("RGB", (pix_chosen.width, pix_chosen.height), pix_chosen.samples)
                img_chosen.save(img_path, format="PNG", dpi=(chosen_dpi, chosen_dpi))
                # Use standard print for final save message
                print(f"Saved page {page_num} at final {chosen_dpi} dpi: {img_path}")
                images.append(img_path)

            # If no rectangles, skip cropping
            if not rectangles:
                continue

            # ======================
            # 2) Convert each rect to fractional coords
            #    relative to 300-dpi image dimension
            # ======================
            width_300, height_300 = img_300.size
            fractional_rects = []
            for (left_300, top_300, right_300, bottom_300) in rectangles:
                frac_left   = left_300 / width_300
                frac_top    = top_300 / height_300
                frac_right  = right_300 / width_300
                frac_bottom = bottom_300 / height_300

                # clamp fractions in [0.0, 1.0] just to be safe
                frac_left   = max(0.0, min(frac_left, 1.0))
                frac_top    = max(0.0, min(frac_top, 1.0))
                frac_right  = max(0.0, min(frac_right, 1.0))
                frac_bottom = max(0.0, min(frac_bottom, 1.0))

                fractional_rects.append((frac_left, frac_top, frac_right, frac_bottom))

            # ======================
            # 3) Render at hi_dpi for maximum quality
            # ======================
            zoom_hi = hi_dpi / 72.0
            mat_hi = fitz.Matrix(zoom_hi, zoom_hi)
            pix_hi = page.get_pixmap(matrix=mat_hi, alpha=False)
            img_hi = Image.frombytes("RGB", (pix_hi.width, pix_hi.height), pix_hi.samples)

            # ======================
            # 4) Crop each fractional rect from the hi-res image
            #    and save at hi_dpi
            # ======================
            hi_w, hi_h = img_hi.size

            for i, (fl, ft, fr, fb) in enumerate(fractional_rects, start=1):
                # scale fractional coords to hi-res pixel coords
                left_px   = int(round(fl * hi_w))
                top_px    = int(round(ft * hi_h))
                right_px  = int(round(fr * hi_w))
                bottom_px = int(round(fb * hi_h))

                cropped = img_hi.crop((left_px, top_px, right_px, bottom_px))
                cropped_path = os.path.join(output_dir, f"page_{page_num}_crop_{i}.jpg")
                
                # Save with hi_dpi
                cropped.save(cropped_path, format="JPEG", quality=100, dpi=(hi_dpi, hi_dpi))
                print(f"  Cropped rectangle {i} saved at {hi_dpi} dpi: {cropped_path}")

                images.append(cropped_path)
                cropped_images.append(cropped_path)

    # ======================
    # 5) Create "recrop.pdf" if we have any cropped images
    # ======================
    if cropped_images:
        create_recrop_pdf(cropped_images, output_dir, pdf_base_name)
        print(f"Created {pdf_base_name}_recrop.pdf from all cropped images.\n")

    return images


def create_recrop_pdf(
    cropped_paths: List[str],
    output_dir: str,
    pdf_base_name: str
) -> None:
    """
    Create '{pdf_base_name}_recrop.pdf' from the given list of cropped image paths,
    placing each on a separate A4 page. Automatically choose landscape
    if the image is wider than tall, else portrait.

    Args:
        cropped_paths: List of paths to cropped image files
        output_dir: Directory to save the recrop PDF
        pdf_base_name: Base name for the output PDF file
    """
    pdf_doc = fitz.open()  # new, empty PDF
    A4_PORTRAIT = (595, 842)   # width, height in points
    A4_LANDSCAPE = (842, 595)  # width, height in points

    for cropped_path in cropped_paths:
        with Image.open(cropped_path) as im:
            w, h = im.size
            # Choose orientation
            if w > h:
                page = pdf_doc.new_page(width=A4_LANDSCAPE[0], height=A4_LANDSCAPE[1])
                target_width, target_height = A4_LANDSCAPE
            else:
                page = pdf_doc.new_page(width=A4_PORTRAIT[0], height=A4_PORTRAIT[1])
                target_width, target_height = A4_PORTRAIT

            # Scale image so it fits within the page
            scale = min(target_width / w, target_height / h)
            new_w = w * scale
            new_h = h * scale

            # Center it on the page
            x0 = (target_width - new_w) / 2
            y0 = (target_height - new_h) / 2
            x1 = x0 + new_w
            y1 = y0 + new_h

            # Insert the image
            page.insert_image(fitz.Rect(x0, y0, x1, y1), filename=cropped_path)

    recrop_pdf_path = os.path.join(output_dir, f"{pdf_base_name}_recrop.pdf")
    pdf_doc.save(recrop_pdf_path)
    pdf_doc.close()


def parse_rectangle(rect_str: str) -> Tuple[int, int, int, int]:
    """
    Parse a rectangle string "left,top,right,bottom" into a tuple of ints.
    These coords are assumed to be based on 300 dpi space.

    Args:
        rect_str: String in format "left,top,right,bottom"
    
    Returns:
        Tuple[int, int, int, int]: (left, top, right, bottom) coordinates
        
    Raises:
        ValueError: If string format is invalid
    """
    coords = rect_str.split(",")
    if len(coords) != 4:
        raise ValueError(
            f"Invalid rectangle definition '{rect_str}'. "
            "Expected format: 'left,top,right,bottom'."
        )
    left, top, right, bottom = map(int, coords)
    return (left, top, right, bottom)


if __name__ == "__main__":
    """
    Usage:
      python pdf2pic.py [pdf_path] [output_dir]
      python pdf2pic.py [pdf_path] [output_dir] "left,top,right,bottom" [...]
    
    You may specify up to four rectangles, each as a comma-separated string
    denoting (left,top,right,bottom) in 300 dpi coordinates.

    - A full-page PNG is created for each page at 'target_dpi' (default=300).
    - If rectangles are specified, those coords are converted to percentages
      relative to a 300-dpi render, and a second pass is made at up to 2400 dpi
      for maximum cropping fidelity. Then a 'recrop.pdf' is created from all
      cropped images, placing each on its own page in either portrait or
      landscape orientation.
    """
    if len(sys.argv) < 3:
        print("Usage: python pdf2pic.py [pdf_path] [output_dir] [rect1] [rect2] [rect3] [rect4]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    output_dir = sys.argv[2]

    # Parse up to 4 rectangle arguments (if present)
    rectangles = []
    if len(sys.argv) > 3:
        for arg in sys.argv[3:7]:  # up to 4 additional args
            rectangles.append(parse_rectangle(arg))

    convert_pdf_to_images(
        pdf_path,
        output_dir,
        target_dpi=300,  # or set any default you like
        rectangles=rectangles
    )
