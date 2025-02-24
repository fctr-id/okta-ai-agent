import uvicorn
import os, sys
from pathlib import Path

if __name__ == "__main__":
    # Get the project root directory
    project_root = Path(__file__).parent
    
    # Add the project root to Python path
    sys.path.append(str(project_root))
    
    # Set environment variable for Python path
    os.environ["PYTHONPATH"] = str(project_root)
    
    uvicorn.run(
        "src.backend.app.main:app",
        host="127.0.0.1",
        port=8001,
        reload=False
    )