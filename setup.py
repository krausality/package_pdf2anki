from setuptools import setup, find_packages
from pathlib import Path

# Read the contents of your README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

setup(
    name="ds_autom8_cli",
    version="0.5.0",
    description="A CLI tool for automating various data station tasks including ticket management.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Martin Krause",
    author_email="krause@luis-hiwi.uni-hannover.de",
    license="Custom Personal Use License v1.4",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: Other/Proprietary License",
        "Operating System :: OS Independent",
        "Topic :: Utilities",
        "Intended Audience :: Developers"
    ],
    url="https://gitlab.uni-hannover.de/mk2233/ds_autom8_cli",
    python_requires="~=3.11.0",
    install_requires=[
        "requests~=2.32.0",
        "selenium==4.17.2",
        "urllib3~=2.1.0",
        "ollama~=0.3.0",
        "kix_api>=0.6",
        "nats_ticket_manager>=0.8.4"
    ],
    packages=find_packages(),
    entry_points={
        "console_scripts": [
            "ds_autom8_cli=ds_autom8_cli.core:cli_invoke",
        ],
    },
)
