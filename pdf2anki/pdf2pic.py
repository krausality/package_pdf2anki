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


def convert_pdf_to_images(pdf_path, output_dir, target_dpi=200):
    os.makedirs(output_dir, exist_ok=True)
    images = []
    
    with pymupdf.open(pdf_path) as pdf:
        zoom = target_dpi / 72  # Calculate zoom factor based on target DPI
        mat = pymupdf.Matrix(zoom, zoom)  # Create transformation matrix
        
        for page_num in range(len(pdf)):
            page = pdf.load_page(page_num)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            img_path = os.path.join(output_dir, f"page_{page_num + 1}.png")
            img.save(img_path, format="PNG", dpi=(target_dpi, target_dpi))
            print(f"Saved high-res page {page_num + 1} as PNG at {target_dpi} DPI")
            images.append(img_path)
    
    return images

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Usage: python pdf2pic.py [pdf_path] [output_dir]")
        sys.exit(1)
    pdf_path = sys.argv[1]
    output_dir = sys.argv[2]
    convert_pdf_to_images(pdf_path, output_dir)
