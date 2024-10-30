# ds_autom8_cli

`ds_autom8_cli` is a Python CLI tool designed to automate various recurring tasks at the Datenstation, including managing tickets, generating and validating WLAN suggestions assisted by 
AI suggestions via ollama. The user can validate recommended answers to a given task.

## Features

- **Ticket Management**: Fetch, answer, and close KIX tickets.
- **WLAN Suggestions**: Generate and validate WLAN ticket suggestions based on incoming ticket information.
- **Command-Line Interface**: Use the tool directly from the command line.

## Installation

You can install the `ds_autom8_cli` package locally by cloning the repository and running:

```bash
pip install .
´´´

Command-Line Interface (CLI)


After installing the package, you can use the `dsautom8cli` commands in your terminal.
Basic Usage


Start the service to automatically generate WLAN suggestions:

bash
python -m ds_autom8_cli.generate_kix_wlan_suggestions



Validate the generated WLAN suggestions:

bash
python -m ds_autom8_cli.validate_suggestions


JSON Output


The JSON output contains the following fields:

- `ticketID`: The ID of the ticket.
- `suggestions`: A list of suggestions generated.
- `email`: The email of the person making the request.

Example JSON output:

json
{
  "ticketID": "12345",
  "suggestions": [
    {
      "count": 10,
      "daysValid": 30,
      "dateStart": "2024-08-01",
      "dateExpire": "2024-08-31",
      "email": "krause@luis-hiwi.uni-hannover.de"
    }
  ],
  "email": "krause@luis-hiwi.uni-hannover.de"
}



Development


If you want to contribute or make changes to this package, follow these steps:

1. Clone the repository:
    ```bash
    git clone https://gitlab.uni-hannover.de/mk2233/dsautom8cli.git
    cd dsautom8cli
    ```

2. Install the package in editable mode:
    ```bash
    pip install -e .
    ```

3. Run tests and make changes:
    - You can create tests to verify the functionality and make sure everything works as expected.

4. Submit a pull request:
    - Feel free to fork the repository and submit a pull request with your changes.
License


This project is licensed under the Custom Personal Use License v1.4 - see the LICENSE file for details.
Contact


If you have any questions or suggestions, please feel free to reach out to me at `krause@luis-hiwi.uni-hannover.de`.

---
Happy automating!
