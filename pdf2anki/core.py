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

import sys

from .validate_suggestions import validate_forever
from .generate_kix_wlan_suggestions import generate_forever

def cli_invoke():
    if len(sys.argv) != 2:
        print("Usage: python cli.py [generate|validate]")
        sys.exit(1)
    
    command = sys.argv[1]

    if command == "generate":
        generate_forever(debug=True)
    elif command == "validate":
        validate_forever(debug=True)
    else:
        print("Unknown command. Use 'generate' or 'validate'.")
        sys.exit(1)

if __name__ == "__main__":
    cli_invoke()