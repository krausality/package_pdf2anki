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

import pymupdf  # PyMuPDF
from PIL import Image
import os
import sys


def convert_pdf_to_images(pdf_path, output_dir, target_dpi=300, rectangles=None):
    """
    Convert each page of a PDF to a full-page image.
    Optionally crop up to 4 rectangular regions per page.
    
    :param pdf_path: Path to the PDF file.
    :param output_dir: Output directory for the resulting images.
    :param target_dpi: Desired DPI to render.
    :param rectangles: A list of tuples (left, top, right, bottom) in pixel coordinates.
                       Each rectangle will be saved as an additional cropped image file.
                       E.g. [(100, 150, 300, 400), (350, 450, 500, 600)]
    :return: A list of paths to the generated images.
    """
    os.makedirs(output_dir, exist_ok=True)
    images = []
    
    with pymupdf.open(pdf_path) as pdf:
        zoom = target_dpi / 72.0  # Calculate zoom factor based on target DPI
        mat = pymupdf.Matrix(zoom, zoom)  # Create transformation matrix
        
        for page_num in range(len(pdf)):
            page = pdf.load_page(page_num)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            # Save the full-page image
            img_path = os.path.join(output_dir, f"page_{page_num + 1}.png")
            img.save(img_path, format="PNG", dpi=(target_dpi, target_dpi))
            print(f"Saved high-res page {page_num + 1} as PNG at {target_dpi} DPI")
            images.append(img_path)
            
            # If rectangles are provided, crop them out and save
            if rectangles:
                for i, rect in enumerate(rectangles):
                    # rect is (left, top, right, bottom)
                    cropped = img.crop(rect)
                    cropped_path = os.path.join(
                        output_dir, f"page_{page_num + 1}_crop_{i + 1}.png"
                    )
                    cropped.save(cropped_path, format="PNG", dpi=(target_dpi, target_dpi))
                    print(f"  Cropped rectangle {i + 1} saved as {cropped_path}")
                    images.append(cropped_path)
    
    return images


def parse_rectangle(rect_str):
    """
    Parse a rectangle string in the format: "left,top,right,bottom"
    and return it as a tuple of integers: (left, top, right, bottom).
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
    denoting (left, top, right, bottom) in pixel coordinates of the rendered image.
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
    
    convert_pdf_to_images(pdf_path, output_dir, target_dpi=300, rectangles=rectangles)
