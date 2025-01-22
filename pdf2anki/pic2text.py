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
import shutil
from datetime import datetime
from PIL import Image
from dotenv import load_dotenv
import asyncio

# Load environment variables (e.g., OPENROUTER_API_KEY) from .env if present
load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# --------------------------------------------------------------------
# LOG FILE PATHS (adjust as needed in production)
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

    request_payload = {
        "model": model_name,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Read the content of the image word by word, if exitsting, also precisly describe graphics/figures/Infographic and their semantic meaning in context to the written text. Do not output anything else. Use the original language e.g. german. Avoid unnecessary translation to english."
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{base64_image}"}
                }
            ]
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
            timeout=60  # 1-minute timeout, adjustable
        )
        response.raise_for_status()
        response_data = response.json()
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
    judge_model,
    model_outputs,
    image_name,
    base64_image=None,
    with_image=False
):
    """
    Sends multiple candidate outputs to the judge model for a decision.
    If 'with_image' is True and 'base64_image' is provided, the judge also
    receives the reference image.
    
    For 'authoritative' mode, we supply a direct prompt enumerating all candidate outputs.
    Returns the chosen text from the judge or raises an exception on errors.
    Logs the judge's final choice into 'decisionmaking.log'.
    """

    # Build the enumerations listing each candidate text
    enumerations = []
    for idx, text_candidate in enumerate(model_outputs, start=1):
        enumerations.append(f"{idx}) {text_candidate}")
    enumerations_str = "\n".join(enumerations)

    # We create a minimal text prompt in a single user message
    # Possibly also include the image as a separate item if requested.
    content_blocks = []

    # If user wants to feed the image, insert the image reference first.
    if with_image and base64_image:
        content_blocks.append({
            "type": "text",
            "text": "Here is the reference image to help you judge correctness."
        })
        content_blocks.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{base64_image}"}
        })

    # Now the actual text prompt enumerating the model outputs
    main_prompt = (
        "You have these candidate OCR outputs:\n"
        f"{enumerations_str}\n\n"
        "Please pick the single best textual result. Output ONLY that text, with no explanation."
    )
    content_blocks.append({"type": "text", "text": main_prompt})

    # Prepare the request payload
    request_payload = {
        "model": judge_model,
        "messages": [{
            "role": "user",
            "content": content_blocks
        }]
    }

    start_time = datetime.now()

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
            "Model Outputs:\n"
        )
        for m_out in model_outputs:
            df.write(f"  - {m_out}\n")
        df.write(f"Judge Picked: {final_text}\n")
        df.write("-------------------------------------\n")

    return final_text


def _archive_old_logs(output_file):
    # Determine archive folder path
    archive_folder = os.path.join(os.path.dirname(output_file), "log_archive")
    os.makedirs(archive_folder, exist_ok=True)

    # For each log file, move it if it exists
    for log_file in (OCR_LOG_FILE, JUDGE_DECISION_LOG_FILE):
        if os.path.exists(log_file):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archived_name = f"{os.path.splitext(log_file)[0]}_{timestamp}.log"
            shutil.move(log_file, os.path.join(archive_folder, archived_name))


def convert_images_to_text(
    images_dir,
    output_file,
    models=None,
    judge_model=None,
    judge_mode="authoritative",
    ensemble_strategy=None,  # placeholder (ignored)
    trust_score=None,        # placeholder (ignored)
    repeat=1,
    judge_with_image=False
):
    """
    Main driver function to perform OCR on a directory of images,
    saving the textual results to 'output_file'.

    Supports:
      - Single model usage (models=[...], len=1).
      - Multi-model usage (len(models) >= 2) requiring a judge_model for final output.
      - 'repeat' calls per model per image.
      - Logging of OCR calls and judge decisions.
      - Optionally feed the judge the base64-encoded image, if 'judge_with_image' is True.

    NOTE: The parameters 'ensemble_strategy' and 'trust_score' are currently
          placeholders and have no effect on the final result.
    """

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

    # If judge mode is anything other than "authoritative", raise
    if judge_mode != "authoritative":
        raise NotImplementedError(
            f"Judge mode '{judge_mode}' not implemented. Only 'authoritative' is supported."
        )

    # Prepare or clear the output file
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("")

    processed_count = 0

    # Gather images
    image_files = [
        f for f in os.listdir(images_dir)
        if f.lower().endswith((".png", ".jpg", ".jpeg"))
    ]
    image_files.sort(key=extract_page_number)

    # Define a helper function that uses asyncio to collect OCR text in parallel
    async def _parallel_ocr(models, repeat, base64_img):
        """
        This async function creates tasks for each model OCR call, allowing them
        to run in parallel. That way, multiple OCR requests don't block each other.
        An undergrad compsci newbie can note that 'run_in_executor' runs sync calls
        in a separate thread, letting us concurrently wait for each to finish.
        """
        loop = asyncio.get_event_loop()  # Access the current event loop responsible for scheduling async tasks
        tasks = []
        # We enqueue one task per (model, repeat) pair
        for m_name in models:
            for _ in range(repeat):
                # run_in_executor schedules _post_ocr_request on a thread so it won't freeze our main loop
                tasks.append(loop.run_in_executor(None, _post_ocr_request, m_name, base64_img))

        # gather(...) waits for all tasks to finish concurrently and returns their results in a list
        results = await asyncio.gather(*tasks)
        return results

    for image_name in image_files:
        image_path = os.path.join(images_dir, image_name)
        final_text = ""
        base64_image = None

        try:
            # Convert once to base64 for efficiency
            base64_image = _image_to_base64(image_path)

            # Gather OCR text in parallel by running our async helper within a single image pass
            # The rest of the logic (like judging) remains sequential.
            all_candidates = asyncio.run(_parallel_ocr(models, repeat, base64_image))

            # Decide final output
            if len(models) == 1: # and repeat(?) = 1
                # Single-model scenario => no judge, just use the last OCR result
                final_text = all_candidates[-1] if all_candidates else ""
            else:
                # Multi-model scenario => must have judge model
                final_text = _post_judge_request(
                    judge_model=judge_model,
                    model_outputs=all_candidates,
                    image_name=image_name,
                    base64_image=base64_image if judge_with_image else None,
                    with_image=judge_with_image
                )

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
            continue

    _archive_old_logs(output_file)
    print(f"OCR results saved to {output_file}. Processed {processed_count} images.")
    return output_file
