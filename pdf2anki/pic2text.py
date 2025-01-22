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
    model_info=None,  # new: list of (model_name, repeat_num) for each output
    base64_image=None,
    with_image=False
):
    """
    Enhanced judge request with better candidate formatting.
    model_info tracks which model and repeat number produced each output.
    """
    # Build enhanced enumerations with source information
    enumerations = []
    for idx, (text_candidate, (model, repeat)) in enumerate(zip(model_outputs, model_info), 1):
        # Format: NUM) [MODEL-NAME : REPEAT-NUM] Text...
        enum = f"{idx}) [{model} : attempt {repeat}]\n{text_candidate}"
        enumerations.append(enum)
    
    enumerations_str = "\n\n".join(enumerations)  # Double-space between candidates

    content_blocks = []
    if with_image and base64_image:
        content_blocks.append({
            "type": "text",
            "text": "Here is the reference image to help you judge correctness."
        })
        content_blocks.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{base64_image}"}
        })

    # Enhanced judge prompt
    main_prompt = (
        "Below are OCR outputs from different models or repeated attempts.\n"
        "Each is formatted as: [MODEL-NAME : attempt NUMBER]\n"
        "---\n\n"
        f"{enumerations_str}\n\n"
        "---\n"
        "Please select the single most accurate and complete text result.\n"
        "Output ONLY the chosen text, without the model name or attempt number."
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
            "Decision Propmpt:\n"
        )
        for block in content_blocks:
            if block["type"] == "text":
                df.write(f"{block['text']}\n")

        df.write("+++++++++++++++++++++++++++\n")
        df.write(f"Judge Picked: {final_text}\n")
        df.write("###########################\n")

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
    model_repeats=None,  # list of tuples (modelName, repeatCount)
    judge_model=None,
    judge_mode="authoritative",
    ensemble_strategy=None,
    trust_score=None,
    judge_with_image=False
):
    """Main driver function to perform OCR on a directory of images."""
    
    if not model_repeats:
        raise ValueError("No OCR model specified. Provide at least one model.")
        
    # Extract just the model names for counting distinct models
    distinct_models = list(set(model for model, _ in model_repeats))
    
    if len(distinct_models) > 1 and not judge_model:
        raise ValueError(
            "Multiple models supplied but no judge model specified.\n"
            "Provide --judge-model or reduce to a single model."
        )

    # Count total calls across all models
    total_calls = sum(repeat_count for _, repeat_count in model_repeats)
    
    # If single model with multiple repeats, we need a judge
    if len(distinct_models) == 1 and total_calls > 1 and not judge_model:
        raise ValueError(
            "Single model with multiple repeats requires a judge model.\n"
            "Please provide --judge-model to select best result from repeated calls."
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

    async def _parallel_ocr(model_repeats_list, base64_img):
        """
        Create OCR tasks based on (model, repeat) pairs.
        Returns results in order of completion.
        """
        loop = asyncio.get_event_loop()
        tasks = []
        model_info = []  # Track which model/repeat produced which result
        
        # Create one task per model per repeat count
        for model_name, repeat_count in model_repeats_list:
            for repeat_num in range(repeat_count):
                tasks.append(
                    loop.run_in_executor(None, _post_ocr_request, model_name, base64_img)
                )
                model_info.append((model_name, repeat_num + 1))
        
        results = await asyncio.gather(*tasks)
        return results, model_info

    for image_name in image_files:
        image_path = os.path.join(images_dir, image_name)
        final_text = ""
        base64_image = None

        try:
            # Convert once to base64 for efficiency
            base64_image = _image_to_base64(image_path)

            # Get all OCR results in parallel
            all_candidates, candidate_info = asyncio.run(_parallel_ocr(model_repeats, base64_image))

            # single-call single-model scenario
            if len(distinct_models) == 1 and total_calls == 1:
                # True single-call scenario: just use the one result
                final_text = all_candidates[0] if all_candidates else ""
            else:
                # Multiple results (either from different models or repeats)
                # => use judge to pick the best one
                final_text = _post_judge_request(
                    judge_model=judge_model,
                    model_outputs=all_candidates,
                    model_info=candidate_info,  # Pass source info to judge
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
