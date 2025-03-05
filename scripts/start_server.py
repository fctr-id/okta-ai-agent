import subprocess
import threading
import sys
import os
# Change to project root directory
os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def stream_output(stream, prefix):
    """Stream output from a pipe to stdout"""
    for line in iter(stream.readline, ""):
        if line:
            print(f"{prefix}: {line.strip()}")
    stream.close()

def run_command(command):
    """Run a shell command and print output from both stdout and stderr"""
    print(f"Executing: {command}")
    
    process = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1  # Line buffered
    )
    
    # Set up threads to stream both stdout and stderr
    stdout_thread = threading.Thread(target=stream_output, args=(process.stdout, "OUT"))
    stderr_thread = threading.Thread(target=stream_output, args=(process.stderr, "ERR"))
    
    # Set as daemon threads so they exit when main thread exits
    stdout_thread.daemon = True
    stderr_thread.daemon = True
    
    # Start the threads
    stdout_thread.start()
    stderr_thread.start()
    
    # Wait for the process to complete
    return_code = process.wait()
    
    # Give the threads a moment to finish printing any remaining output
    stdout_thread.join(1)
    stderr_thread.join(1)
    
    if return_code != 0:
        print(f"Command exited with return code {return_code}")
        return False
    
    return True

# Run the FastAPI server
print("Starting server...")
run_command("python -m uvicorn src.backend.app.main:app --reload --host 0.0.0.0 --port 8001 --log-level info")