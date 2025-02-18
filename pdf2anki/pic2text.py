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
from typing import List, Tuple, Optional

# Load environment variables (e.g., OPENROUTER_API_KEY) from .env if present
load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# --------------------------------------------------------------------
# Default log basename patterns and extension (unique filenames will be created)
DEFAULT_OCR_LOG_BASENAME = "ocr"
DEFAULT_JUDGE_LOG_BASENAME = "decisionmaking"
LOG_EXTENSION = ".log"
# --------------------------------------------------------------------


def extract_page_number(filename: str) -> int:
    """
    Helper function to extract a page index from a filename
    with pattern 'page_<NUM>'. If not found, returns +inf for sorting.
    """
    match = re.search(r'page_(\d+)', filename)
    return int(match.group(1)) if match else float('inf')


def _image_to_base64(image_path: str) -> str:
    """
    Converts an image to a base64-encoded string for inclusion in OpenRouter calls.
    """
    with Image.open(image_path) as img:
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_bytes = buffered.getvalue()
    return base64.b64encode(img_bytes).decode("utf-8")


def _post_ocr_request(model_name: str, base64_image: str, ocr_log_file: str) -> str:
    """
    Posts an OCR request to the OpenRouter API using the specified model_name.
    Returns the text output if successful, or raises an exception on errors.
    Logs details in the provided ocr_log_file.
    """
    start_time = datetime.now()
    request_payload = {
        "model": model_name,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Read the content of the image word by word. If existing, also describe "
                        "graphics/figures/Infographic/embeddedimages verbosely and precisely - and their semantic "
                        "meaning in context to the written text. Do not output anything else. Use the "
                        "original language e.g. german. Avoid unnecessary translation to english."
                    )
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{base64_image}"}
                }
            ]
        }]
    }

    response_data = None
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
        with open(ocr_log_file, "a", encoding="utf-8") as lf:
            lf.write(
                f"\n[ERROR OCR CALL] {datetime.now().isoformat()}\n"
                f"Model: {model_name}\n"
                f"Exception: {str(exc)}\n"
                f"Traceback:\n{traceback.format_exc()}\n"
                f"Request (truncated): {str(request_payload)[:120]!r}\n"
                f"Response (not truncated): {str(response_data)!r}\n"
                "-----------------------------------------\n"
            )
        raise

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    with open(ocr_log_file, "a", encoding="utf-8") as lf:
        lf.write(
            f"\n[OCR CALL] {start_time.isoformat()} => {end_time.isoformat()} ({duration:.2f}s)\n"
            f"Model: {model_name}\n"
            f"Request: <base64 image omitted>\n"
            f"Response (truncated): {cleaned_text[:120]!r}\n"
            "-----------------------------------------\n"
        )

    return cleaned_text


def _post_judge_request(
    judge_model: str,
    model_outputs: List[str],
    image_name: str,
    model_info: List[Tuple[str, int]],  # list of (model_name, attempt_number)
    judge_decision_log_file: str,
    base64_image: Optional[str] = None,
    with_image: bool = False
) -> str:
    """
    Enhanced judge request with candidate formatting.
    Logs the judge decision in the provided judge_decision_log_file.
    """
    enumerations = []
    for idx, (text_candidate, (model, repeat)) in enumerate(zip(model_outputs, model_info), 1):
        enum = f"{idx}) [{model} : attempt {repeat}]\n"
        enum += "+" * 5 + f"[{model} : attempt {repeat}] START" + "+" * 5 + "\n"
        enum += text_candidate
        enum += "\n" + "-" * 5 + f"[{model} : attempt {repeat}] END" + "-" * 5 + "\n"
        enumerations.append(enum)
    
    enumerations_str = "\n\n".join(enumerations)

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

    main_prompt = (
        "Below are OCR outputs from different models or repeated attempts.\n"
        "Each is formatted as: [MODEL-NAME : attempt NUMBER]\n"
        "---\n\n"
        f"{enumerations_str}\n\n"
        "---\n"
        "Please select the single most accurate and most complete text result.\n"
        "Output ONLY the chosen text, without the model name or attempt number."
    )
    content_blocks.append({"type": "text", "text": main_prompt})

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
        with open(judge_decision_log_file, "a", encoding="utf-8") as df:
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

    with open(judge_decision_log_file, "a", encoding="utf-8") as df:
        df.write(
            f"\n[Judge Decision] {start_time.isoformat()} => {end_time.isoformat()} ({duration:.2f}s)\n"
            f"Image: {image_name}\n"
            "Decision Prompt:\n"
        )
        for block in content_blocks:
            if block["type"] == "text":
                df.write(f"{block['text']}\n")
        df.write("\n" + "+" * 10 + "JUDGE PICK START" + "+" * 10 + "\n")
        df.write(f"{final_text}\n")
        df.write("#" * 10 + "JUDGE PICK END" + "#" * 10 + "\n")

    return final_text


def _archive_old_logs(output_file: str, log_files: List[str]) -> None:
    """
    Archives each log file (if it exists) by moving it into a 'log_archive'
    folder next to the output_file. Works correctly with unique log filenames.
    """
    archive_folder = os.path.join(os.path.dirname(output_file), "log_archive")
    os.makedirs(archive_folder, exist_ok=True)

    for log_file in log_files:
        if os.path.exists(log_file):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base = os.path.splitext(os.path.basename(log_file))[0]
            archived_name = f"{base}_{timestamp}{LOG_EXTENSION}"
            shutil.move(log_file, os.path.join(archive_folder, archived_name))


def convert_images_to_text(
    images_dir: str,
    output_file: str,
    model_repeats: List[Tuple[str, int]],  # list of tuples (modelName, repeatCount)
    judge_model: Optional[str] = None,
    judge_mode: str = "authoritative",
    ensemble_strategy: Optional[str] = None,
    trust_score: Optional[float] = None,
    judge_with_image: bool = False
) -> str:
    """Main driver function to perform OCR on a directory of images."""
    
    if not model_repeats:
        raise ValueError("No OCR model specified. Provide at least one model.")
        
    distinct_models = list(set(model for model, _ in model_repeats))
    total_calls = sum(repeat_count for _, repeat_count in model_repeats)
    
    if len(distinct_models) > 1 and not judge_model:
        raise ValueError(
            "Multiple models supplied but no judge model specified.\n"
            "Provide --judge-model or reduce to a single model."
        )
    if len(distinct_models) == 1 and total_calls > 1 and not judge_model:
        raise ValueError(
            "Single model with multiple repeats requires a judge model.\n"
            "Please provide --judge-model to select best result from repeated calls."
        )

    # Clear the output file.
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("")

    processed_count = 0

    # Determine the output directory.
    output_dir = os.path.dirname(os.path.abspath(output_file))
    # Get and sanitize the base name of the output file (without extension).
    # Replace any character that is not a letter, digit, or underscore with an underscore
    file_name = re.sub(r'\W+', '_', os.path.basename(output_file).split(".")[0])
    # Create a unique identifier for this instance (timestamp + process ID).
    instance_id = file_name + "_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(os.getpid())
    # Create unique log filenames.
    ocr_log_file = os.path.join(output_dir, f"{DEFAULT_OCR_LOG_BASENAME}_{instance_id}{LOG_EXTENSION}")
    judge_decision_log_file = os.path.join(output_dir, f"{DEFAULT_JUDGE_LOG_BASENAME}_{instance_id}{LOG_EXTENSION}")

    # Gather and sort image files.
    image_files = [
        f for f in os.listdir(images_dir)
        if f.lower().endswith((".png", ".jpg", ".jpeg"))
    ]
    image_files.sort(key=extract_page_number)

    async def _parallel_ocr(model_repeats_list: List[Tuple[str, int]], base64_img: str) -> Tuple[List[str], List[Tuple[str, int]]]:
        """
        Create OCR tasks based on (model, repeat) pairs.
        Returns results along with info on which model/attempt produced each result.
        """
        loop = asyncio.get_event_loop()
        tasks = []
        model_info = []  # To track (model_name, attempt_number)
        for model_name, repeat_count in model_repeats_list:
            for repeat_num in range(repeat_count):
                tasks.append(
                    loop.run_in_executor(None, _post_ocr_request, model_name, base64_img, ocr_log_file)
                )
                model_info.append((model_name, repeat_num + 1))
        results = await asyncio.gather(*tasks)
        return results, model_info

    for image_name in image_files:
        image_path = os.path.join(images_dir, image_name)
        final_text = ""
        base64_image = None

        try:
            base64_image = _image_to_base64(image_path)
            all_candidates, candidate_info = asyncio.run(_parallel_ocr(model_repeats, base64_image))

            if len(distinct_models) == 1 and total_calls == 1:
                final_text = all_candidates[0] if all_candidates else ""
            else:
                final_text = _post_judge_request(
                    judge_model=judge_model,
                    model_outputs=all_candidates,
                    model_info=candidate_info,
                    image_name=image_name,
                    judge_decision_log_file=judge_decision_log_file,
                    base64_image=base64_image if judge_with_image else None,
                    with_image=judge_with_image
                )

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

    _archive_old_logs(output_file, [ocr_log_file, judge_decision_log_file])
    print(f"OCR results saved to {output_file}. Processed {processed_count} images.")
    return output_file
