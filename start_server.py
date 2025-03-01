import subprocess

def run_command(command):
    """Run a shell command and print output"""
    print(f"Executing: {command}")
    
    process = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Stream output in real time
    while True:
        output = process.stdout.readline()
        if output == '' and process.poll() is not None:
            break
        if output:
            print(output.strip())
            
    # Get any remaining output
    stdout, stderr = process.communicate()
    
    if process.returncode != 0:
        print(f"Error executing command: {stderr}")
        return False
    
    return True

# Run the FastAPI server
print("Starting server...")
run_command("python -m uvicorn src.backend.app.main:app --reload --host 0.0.0.0 --port 8001")