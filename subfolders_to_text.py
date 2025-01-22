import os
import subprocess

# Base directory to process
base_dir = r"C:\Users\Maddin\Meine Ablage\Uni\Theo_Philo_WiSe24_25\Vorlesung_Einführung_in_die_theoretische_Philosophie\totext"
# Virtual environment path
venv_dir = r"C:\Users\Maddin\Meine Ablage\Github\package_pdf2anki"
venv_python = os.path.join(venv_dir, ".venv", "Scripts", "python.exe")

def run_command(subfolder_path: str, output_file_path: str):
    """
    Runs the pic2text command using the virtual environment's Python interpreter
    """
    command = [
        venv_python, "-m", "pdf2anki", "pic2text",
        subfolder_path,
        output_file_path,
        "--model", "google/gemini-pro-1.5",
        "--repeat", "3",
        "--judge-model", "google/gemini-pro-1.5",
        "--judge-mode", "authoritative",
        "--judge-with-image"
    ]
    
    # Set the working directory to the venv directory
    cwd = venv_dir
    
    print(f"\n[INFO] Processing folder: {subfolder_path}")
    print("[DEBUG] Command:", " ".join(command))
    print(f"[DEBUG] Working directory: {cwd}")

    # Run the command with the specified working directory
    result = subprocess.run(command, capture_output=True, text=True, cwd=cwd)
    
    # Check and log results
    if result.returncode == 0:
        print(f"[INFO] Command succeeded for: {subfolder_path}")
        if result.stdout:
            print("[DEBUG] STDOUT:\n", result.stdout)
    else:
        print(f"[ERROR] Command failed for: {subfolder_path} (exit code: {result.returncode})")
        if result.stderr:
            print("[DEBUG] STDERR:\n", result.stderr)

def process_subfolders():
    """
    Iterates through each subdirectory of base_dir, calling `run_command`
    for every valid subfolder.
    """
    for subfolder in os.listdir(base_dir):
        subfolder_path = os.path.join(base_dir, subfolder)
        if os.path.isdir(subfolder_path):
            output_file_path = os.path.join(subfolder_path, "output.txt")
            run_command(subfolder_path, output_file_path)

# Entry point
if __name__ == "__main__":
    process_subfolders()
    print("\n[INFO] All subfolders processed sequentially.")

