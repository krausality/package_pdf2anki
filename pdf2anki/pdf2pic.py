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

from pdf2image import convert_from_path
import os

def convert_pdf_to_images(pdf_path, output_dir):
    # Ensure the output directory exists
    os.makedirs(output_dir, exist_ok=True)
    # Convert PDF to images and save in output_dir
    images = convert_from_path(pdf_path)
    for i, image in enumerate(images):
        image_path = os.path.join(output_dir, f"page_{i+1}.png")
        image.save(image_path, 'PNG')
    print(f"Saved {len(images)} images to {output_dir}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Usage: python pdf2pic.py [pdf_path] [output_dir]")
        sys.exit(1)
    pdf_path = sys.argv[1]
    output_dir = sys.argv[2]
    convert_pdf_to_images(pdf_path, output_dir)
