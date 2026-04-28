import os

import uvicorn

from src.app import app


if __name__ == "__main__":
	port = int(os.getenv("PORT", "8000"))
	uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")
