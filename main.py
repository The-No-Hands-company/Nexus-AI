import os
import sys

# Ensure the project root is on the Python path so that nostack and
# other top-level packages are importable regardless of how uvicorn
# spawns the worker process.
_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import uvicorn
from src.app import app


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")
