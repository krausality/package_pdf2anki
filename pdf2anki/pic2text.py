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

#from .core import cli_invoke

from PIL import Image
import base64
import re  # Import regex module for extracting numbers
import io
import ollama
import os
import traceback
from collections import defaultdict

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

def extract_page_number(filename):
    """Extract the page number from a filename like 'page_x.ext'."""
    match = re.search(r'page_(\d+)', filename)
    return int(match.group(1)) if match else float('inf')  # If no number found, put at end

def convert_images_to_text(images_dir, output_file):
    # Clear the output file first to start fresh
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("")  # Create/clear the file
    
    processed_count = 0

    # Collect and sort image filenames based on the extracted page number
    image_files = [f for f in os.listdir(images_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    image_files.sort(key=extract_page_number)  # Sort using the page number

    for image_name in image_files:
        image_path = os.path.join(images_dir, image_name)
        
        try:
            # Convert image to Base64
            base64_image = _image_to_base64(image_path)
            
            """
            response=defaultdict(dict)
            response['message']['content'] = "Kuhl"
            """

            # Use Ollama to process OCR on the image
            response = ollama.chat(
                model="x/llama3.2-vision:11b",
                messages=[{
                    "role": "user",
                    "content": "The image is a slide from a presentation. Output should be in this format - : ,: . Do not output anything else",
                    "images": [base64_image]
                }],
            )
            
        
            
            # Extract and format the OCR result
            cleaned_text = response['message']['content'].strip()
            entry_text = f"Image: {image_name}\n{cleaned_text}"
            
            # Append the result to the file
            with open(output_file, 'a', encoding='utf-8') as f:
                if processed_count > 0:
                    f.write("\n\n")
                f.write(entry_text)
            
            processed_count += 1
            print(f"Processed and saved {image_name}.")
            
        # Inside the function
        except Exception as e:
            print(f"Error processing {image_name}: {str(e)}")
            with open(output_file, 'a', encoding='utf-8') as f:
                if processed_count > 0:
                    f.write("\n\n")
                # Write the traceback to the file for detailed error context
                f.write(f"Error processing {image_name}: {str(e)}\n{traceback.format_exc()}")
            continue
    
    print(f"OCR results saved to {output_file}. Processed {processed_count} images.")
    
    return output_file

# if __name__ == "__main__":
#     cli_invoke()