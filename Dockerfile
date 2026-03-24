FROM python:3.11-slim

# Install git
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy files
COPY . .

# Install Python deps
RUN pip install --no-cache-dir -r requirements.txt

# Start server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
