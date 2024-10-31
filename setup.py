from setuptools import setup, find_packages
from pathlib import Path

# Read the contents of your README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

setup(
    name="pdf2anki",
    version="0.1.0",
    description="A CLI tool for converting PDFs into Anki flashcards.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Martin Krause",
    author_email="martinkrausemedia@gmail.com",
    license="Custom Personal Use License v1.4",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: Other/Proprietary License",
        "Operating System :: OS Independent",
        "Topic :: Utilities",
        "Intended Audience :: Education",
    ],
    url="https://your-repo-url/pdf2anki",
    python_requires="~=3.11.0",
    install_requires=[
        "ollama>=0.3.3",
        "pdf2image>=1.16.3",
        "Pillow>=9.1.0",
        "genanki~=0.13.1"
    ],
    packages=find_packages(),
    entry_points={
        "console_scripts": [
            "pdf2anki=pdf2anki.core:cli_invoke",
        ],
    },
)