"""
This software is licensed under the terms specified in LICENSE,
authored by Martin Krause.

Usage is limited to:
- Students enrolled at accredited institutions
- Individuals with an annual income below 15,000€
- Personal desktop PC automation tasks

For commercial usage, including server deployments, please contact:
martinkrausemedia@gmail.com

Refer to the NOTICE file for dependencies and third-party libraries used.
"""
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

import argparse
from . import pdf2pic
from . import pic2text
from . import text2anki


def pdf_to_images(args):
    """
    Convert a PDF file into a sequence of images, saving each page as an individual image.
    """
    pdf2pic.convert_pdf_to_images(args.pdf_path, args.output_dir)


def images_to_text(args):
    """
    Perform OCR on a directory of images, extracting text and saving it to a file.
    """
    pic2text.convert_images_to_text(args.images_dir, args.output_file)


def text_to_anki(args):
    """
    Convert a text file into an Anki-compatible format, creating an Anki deck.
    """
    text2anki.convert_text_to_anki(args.text_file, args.anki_file)


def process_pdf_to_anki(args):
    """
    Full pipeline: Convert a PDF to images, then extract text, and finally create an Anki deck.
    """
    # Intermediate file paths
    output_text_file = 'temp_text.txt'
    pdf_to_images(args)
    images_to_text(argparse.Namespace(images_dir=args.output_dir, output_file=output_text_file))
    text_to_anki(argparse.Namespace(text_file=output_text_file, anki_file=args.anki_file))


def cli_invoke():
    parser = argparse.ArgumentParser(
        description="Convert PDFs to Anki flashcards through a multi-step pipeline involving image extraction, OCR, and Anki formatting."
    )

    subparsers = parser.add_subparsers(title="Commands", dest="command")

    # PDF to Images Command
    parser_pdf2pic = subparsers.add_parser(
        "pdf2pic",
        help="Convert PDF pages into individual images.",
        description="This command converts each page of a PDF into a separate PNG image."
    )
    parser_pdf2pic.add_argument("pdf_path", type=str, help="Path to the PDF file.")
    parser_pdf2pic.add_argument("output_dir", type=str, help="Directory to save the output images.")
    parser_pdf2pic.set_defaults(func=pdf_to_images)

    # Images to Text Command
    parser_pic2text = subparsers.add_parser(
        "pic2text",
        help="Extract text from images using OCR.",
        description="This command performs OCR on images in a directory and saves the extracted text to a file."
    )
    parser_pic2text.add_argument("images_dir", type=str, help="Directory containing images to be processed.")
    parser_pic2text.add_argument("output_file", type=str, help="File path to save extracted text.")
    parser_pic2text.set_defaults(func=images_to_text)

    # Text to Anki Command
    parser_text2anki = subparsers.add_parser(
        "text2anki",
        help="Convert extracted text into an Anki-compatible format.",
        description="This command takes a text file and formats its contents as Anki flashcards, outputting an Anki package file."
    )
    parser_text2anki.add_argument("text_file", type=str, help="Path to the text file with content for Anki cards.")
    parser_text2anki.add_argument("anki_file", type=str, help="Output path for the Anki package file.")
    parser_text2anki.set_defaults(func=text_to_anki)

    # Full Pipeline Command
    parser_process = subparsers.add_parser(
        "process",
        help="Run the entire pipeline: PDF to Images, Images to Text, and Text to Anki.",
        description="This command automates the full process of converting a PDF to Anki flashcards."
    )
    parser_process.add_argument("pdf_path", type=str, help="Path to the PDF file.")
    parser_process.add_argument("output_dir", type=str, help="Directory to save intermediate images.")
    parser_process.add_argument("anki_file", type=str, help="Output path for the final Anki package file.")
    parser_process.set_defaults(func=process_pdf_to_anki)

    args = parser.parse_args()

    if args.command:
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    cli_invoke()
