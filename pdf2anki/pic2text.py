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

Code partially from:
  https://pub.towardsai.net/enhance-ocr-with-llama-3-2-vision-using-ollama-0b15c7b8905c
"""

import os
import re
import requests
import json
import traceback
import base64
import io
from datetime import datetime
from PIL import Image
from dotenv import load_dotenv

# Load environment variables (e.g., OPENROUTER_API_KEY) from .env if present
load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# --------------------------------------------------------------------
# LOG FILE PATHS (can be customized in production)
OCR_LOG_FILE = "ocr.log"
JUDGE_DECISION_LOG_FILE = "decisionmaking.log"
# --------------------------------------------------------------------


def extract_page_number(filename):
    """
    Helper function to extract a page index from a filename
    with pattern 'page_<NUM>'. If not found, returns +inf
    for sorting.
    """
    match = re.search(r'page_(\d+)', filename)
    return int(match.group(1)) if match else float('inf')


def _image_to_base64(image_path):
    """
    Converts an image to a base64-encoded string for inclusion in OpenRouter calls.
    """
    with Image.open(image_path) as img:
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_bytes = buffered.getvalue()
    return base64.b64encode(img_bytes).decode("utf-8")


def _post_ocr_request(model_name, base64_image):
    """
    Posts an OCR request to the OpenRouter API using the specified model_name.
    Returns the text output if successful, or raises an exception on errors.
    This function logs request/response details in 'ocr.log'.
    """
    # For logging, time stamp and partial request info
    start_time = datetime.now()

    # We keep the prompt minimal as an example. Production usage might be more advanced.
    request_payload = {
        "model": model_name,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Read the content of the image word by word. Do not output anything else."
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{base64_image}"}
                }
            ]
        }]
    }

    # Try the request
    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            data=json.dumps(request_payload),
            timeout=60  # 1-minute timeout, adjustable
        )
        response.raise_for_status()
        response_data = response.json()

        # Extract the text from the response
        cleaned_text = response_data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        # Log error to OCR log
        with open(OCR_LOG_FILE, "a", encoding="utf-8") as lf:
            lf.write(
                f"\n[ERROR OCR CALL] {datetime.now().isoformat()}\n"
                f"Model: {model_name}\n"
                f"Exception: {str(exc)}\n"
                f"Traceback:\n{traceback.format_exc()}\n"
                "-----------------------------------------\n"
            )
        raise

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    # Log success to OCR log
    with open(OCR_LOG_FILE, "a", encoding="utf-8") as lf:
        lf.write(
            f"\n[OCR CALL] {start_time.isoformat()} => {end_time.isoformat()} ({duration:.2f}s)\n"
            f"Model: {model_name}\n"
            f"Request: <base64 image omitted>\n"
            f"Response (truncated to 120 chars): {cleaned_text[:120]!r}\n"
            "-----------------------------------------\n"
        )

    return cleaned_text


def _post_judge_request(
    judge_model,  # string
    model_outputs,  # list of text outputs from multiple calls (including repeats)
    image_name
):
    """
    Sends multiple candidate outputs to the judge model for a decision.
    For 'authoritative' mode, we supply a direct prompt that enumerates
    the possibilities and asks the judge to pick the best.

    Returns the chosen text from the judge or raises an exception on errors.
    Also logs the judge's final choice into 'decisionmaking.log'.
    """
    # Build the prompt enumerating each possible text
    # For example:
    # "You have these candidate OCR texts from multiple models (possibly repeated):
    # 1) ...
    # 2) ...
    # Please pick the best, and ONLY output that text."
    enumerations = []
    for idx, text_candidate in enumerate(model_outputs, start=1):
        enumerations.append(f"{idx}) {text_candidate}")

    # We combine them into a single string with newlines
    enumerations_str = "\n".join(enumerations)
    judge_prompt = (
        "You have these candidate OCR outputs:\n"
        f"{enumerations_str}\n\n"
        "Please pick the single best textual result (no explanation). Output ONLY the chosen text."
    )

    # For logging, capture start time
    start_time = datetime.now()

    # We try the judge request
    request_payload = {
        "model": judge_model,
        "messages": [{
            "role": "user",
            "content": judge_prompt
        }]
    }

    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            data=json.dumps(request_payload),
            timeout=60
        )
        response.raise_for_status()
        response_data = response.json()
        final_text = response_data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        # Log to decisionmaking.log that we failed
        with open(JUDGE_DECISION_LOG_FILE, "a", encoding="utf-8") as df:
            df.write(
                f"\n[Judge Decision ERROR] {datetime.now().isoformat()}\n"
                f"Image: {image_name}\n"
                f"Model Outputs: {model_outputs}\n"
                f"Exception: {str(exc)}\n"
                f"Traceback:\n{traceback.format_exc()}\n"
                "-------------------------------------\n"
            )
        raise

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    # Log judge's final decision
    with open(JUDGE_DECISION_LOG_FILE, "a", encoding="utf-8") as df:
        df.write(
            f"\n[Judge Decision] {start_time.isoformat()} => {end_time.isoformat()} ({duration:.2f}s)\n"
            f"Image: {image_name}\n"
            f"Model Outputs:\n"
        )
        for m_out in model_outputs:
            df.write(f"  - {m_out}\n")
        df.write(f"Judge Picked: {final_text}\n")
        df.write("-------------------------------------\n")

    return final_text


def convert_images_to_text(
    images_dir,
    output_file,
    models=None,
    judge_model=None,
    judge_mode="authoritative",
    ensemble_strategy=None,  # placeholder (ignored)
    trust_score=None,        # placeholder (ignored)
    repeat=1
):
    """
    Main driver function to perform OCR on a directory of images,
    saving the textual results to 'output_file'.

    Supports:
      - Single model usage (models=[...], len=1).
      - Multi-model usage (len(models) >= 2) requiring a judge_model for final output.
      - 'repeat' calls per model per image.
      - Logging of OCR calls and judge decisions.

    NOTE: The parameters 'ensemble_strategy' and 'trust_score' are currently
          placeholders and have no effect on the final result.
    """

    # Basic input validation
    if not models or len(models) == 0:
        raise ValueError(
            "No OCR model specified. Please provide at least one --model."
        )

    # If multiple models but no judge => error (as per docs)
    if len(models) > 1 and not judge_model:
        raise ValueError(
            "Multiple models supplied but no judge model was specified.\n"
            "This is not currently supported. Please provide --judge-model or reduce to a single --model."
        )

    # If judge mode is anything other than "authoritative", warn or raise
    # but per docs, we only handle "authoritative" right now.
    if judge_mode != "authoritative":
        raise NotImplementedError(
            f"Judge mode '{judge_mode}' not implemented. Only 'authoritative' is supported."
        )

    # Flatten the usage: single model or multi-model with a judge.
    # Prepare output file by clearing/creating it.
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("")

    processed_count = 0

    # Gather images
    image_files = [
        f for f in os.listdir(images_dir)
        if f.lower().endswith((".png", ".jpg", ".jpeg"))
    ]
    image_files.sort(key=extract_page_number)

    for image_name in image_files:
        image_path = os.path.join(images_dir, image_name)
        final_text = ""
        base64_image = None

        try:
            # Convert once to base64 for efficiency
            base64_image = _image_to_base64(image_path)

            # For each image, we'll gather the text from each model * repeat times
            all_candidates = []
            for model_name in models:
                for _ in range(repeat):
                    # Perform OCR call
                    ocr_text = _post_ocr_request(model_name, base64_image)
                    all_candidates.append(ocr_text)

            # Decide final output
            if len(models) == 1:
                # Single-model scenario => no judge, just take the last call's result
                # or we might combine them. The doc states it simply "comes direct to output".
                # We'll produce the *first* successful result. If you prefer the last or a join, you can adapt.
                final_text = all_candidates[-1] if all_candidates else ""
            else:
                # Multi-model scenario => must have judge model
                # all_candidates will contain multiple outputs from different models (and repeats)
                # judge_mode is "authoritative"
                final_text = _post_judge_request(judge_model, all_candidates, image_name)

            # Append final text to the output file
            with open(output_file, "a", encoding="utf-8") as f:
                if processed_count > 0:
                    f.write("\n\n")
                f.write(f"Image: {image_name}\n{final_text}")

            processed_count += 1
            print(f"Processed and saved {image_name}.")

        except Exception as e:
            print(f"Error processing {image_name}: {str(e)}")
            with open(output_file, "a", encoding="utf-8") as f:
                if processed_count > 0:
                    f.write("\n\n")
                f.write(f"Error processing {image_name}: {str(e)}\n{traceback.format_exc()}")
            # Continue to next image
            continue

    print(f"OCR results saved to {output_file}. Processed {processed_count} images.")
    return output_file
