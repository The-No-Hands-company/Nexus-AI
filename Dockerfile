# Use official Python slim image
FROM python:3.12-slim

# Install system dependencies (git + basic tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Expose port (Railway will use $PORT)
EXPOSE 8000

# Start the app (respects $PORT from Railway)
CMD ["python", "main.py"]
