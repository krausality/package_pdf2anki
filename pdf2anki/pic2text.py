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

Code partially from https://pub.towardsai.net/enhance-ocr-with-llama-3-2-vision-using-ollama-0b15c7b8905c
"""

# Import the necessary secrets handling module
# https://www.geeksforgeeks.org/using-python-environment-variables-with-python-dotenv/
from dotenv import load_dotenv


#from .core import cli_invoke

import os
import re
from PIL import Image
import base64
import io
import requests
import json
import traceback

# Load environment variables from the .env file (if present)
load_dotenv()

# Access environment variables as if they came from the actual environment
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')


def extract_page_number(filename):
    match = re.search(r'page_(\d+)', filename)
    return int(match.group(1)) if match else float('inf')

def _image_to_base64(image_path):
    # Open the image file
    with Image.open(image_path) as img:
        # Create a BytesIO object to hold the image data
        buffered = io.BytesIO()
        # Save the image to the BytesIO object in a specific format (e.g., JPEG)
        img.save(buffered, format="PNG")
        # Get the byte data from the BytesIO object
        img_bytes = buffered.getvalue()
        # Encode the byte data to base64
        img_base64 = base64.b64encode(img_bytes).decode('utf-8')
        return img_base64

def convert_images_to_text(images_dir, output_file):
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("")

    processed_count = 0

    image_files = [f for f in os.listdir(images_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    image_files.sort(key=extract_page_number)

    for image_name in image_files:
        image_path = os.path.join(images_dir, image_name)
        
        try:
            base64_image = _image_to_base64(image_path)

            response = requests.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json"
                },
                data=json.dumps({
                    #"model": "openai/gpt-4o-2024-05-13",
                    "model": "meta-llama/llama-3.2-11b-vision-instruct",
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Read the content of the image word by word. Do not output anything else"},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
#                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}} #Todo option to use multiple images pictures?
                        ]
                    }]
                })
            )

            response.raise_for_status()
            response_data = response.json()
            cleaned_text = response_data['choices'][0]['message']['content'].strip()

            with open(output_file, 'a', encoding='utf-8') as f:
                if processed_count > 0:
                    f.write("\n\n")
                f.write(f"Image: {image_name}\n{cleaned_text}")

            processed_count += 1
            print(f"Processed and saved {image_name}.")

        except Exception as e:
            print(f"Error processing {image_name}: {str(e)}")
            with open(output_file, 'a', encoding='utf-8') as f:
                if processed_count > 0:
                    f.write("\n\n")
                f.write(f"Error processing {image_name}: {str(e)}\n{traceback.format_exc()}")
            continue

    print(f"OCR results saved to {output_file}. Processed {processed_count} images.")
    return output_file