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

from .core import cli_invoke

from PIL import Image
import base64
import io
import ollama

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

def convert(image_path='image.png'):
    # Example usage
    #image_path = 'image.png'  # Replace with your image path
    base64_image = _image_to_base64(image_path)

    # Use Ollama to clean and structure the OCR output
    response = ollama.chat(
        model="x/llama3.2-vision:latest",
        messages=[{
        "role": "user",
        "content": "The image is a slide from a presentation. Output should be in this format - <Textual content>: <Text>,<Visual content>: <Visual description>. Do not output anything else",
        "images": [base64_image]
        }],
    )
    # Extract cleaned text
    cleaned_text = response['message']['content'].strip()
    print(cleaned_text)
    return cleaned_text

if __name__ == "__main__":
    cli_invoke()