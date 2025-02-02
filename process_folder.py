import os
import subprocess

# Base directory to process
base_dir = r"C:\Users\Maddin\Meine Ablage\Uni\IT_Secu\Finf\altklausuren_und_protokolle"
# Virtual environment path
venv_dir = r"C:\Users\Maddin\Meine Ablage\Github\package_pdf2anki"
venv_python = os.path.join(venv_dir, ".venv", "Scripts", "python.exe")

def run_command(pdf_file: str, output_txt_file: str, image_output_dir: str):
    """
    Runs the pdf2text command using the virtual environment's Python interpreter.
    """
    command = [
        venv_python, "-m", "pdf2anki", "pdf2text",
        pdf_file,
        image_output_dir,
        output_txt_file,
        "--model", "google/gemini-flash-1.5",
        "--repeat", "2",
        "--judge-model", "google/gemini-flash-1.5",
        "--judge-mode", "authoritative",
        "--judge-with-image"
    ]
    
    # Set the working directory to the venv directory
    cwd = venv_dir
    
    print(f"\n[INFO] Processing file: {pdf_file}")
    print("[DEBUG] Command:", " ".join(command))
    print(f"[DEBUG] Working directory: {cwd}")

    # Run the command with the specified working directory
    result = subprocess.run(command, capture_output=True, text=True, cwd=cwd)
    
    # Check and log results
    if result.returncode == 0:
        print(f"[INFO] Command succeeded for: {pdf_file}")
        if result.stdout:
            print("[DEBUG] STDOUT:\n", result.stdout)
    else:
        print(f"[ERROR] Command failed for: {pdf_file} (exit code: {result.returncode})")
        if result.stderr:
            print("[DEBUG] STDERR:\n", result.stderr)

def process_pdfs():
    """
    Iterates through each PDF file in base_dir, calling `run_command`
    for every valid PDF file.
    """
    for file in os.listdir(base_dir):
        if file.lower().endswith(".pdf"):  # Only process PDF files
            pdf_file_path = os.path.join(base_dir, file)
            
            # Define output paths
            base_name = os.path.splitext(file)[0]  # Get filename without extension
            output_txt_file = os.path.join(base_dir, f"{base_name}_transscript.txt")
            image_output_dir = os.path.join(base_dir, f"{base_name}_pics")  # Store images in "pics"
            
            # Ensure image output directory exists
            os.makedirs(image_output_dir, exist_ok=True)

            run_command(pdf_file_path, output_txt_file, image_output_dir)

# Entry point
if __name__ == "__main__":
    process_pdfs()
    print("\n[INFO] All PDF files in base directory processed sequentially.")
