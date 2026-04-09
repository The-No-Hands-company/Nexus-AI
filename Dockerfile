# Nexus AI — Dockerized for Nexus Systems Ecosystem
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir "PyJWT>=2.8.0"

COPY . .


EXPOSE 8000
CMD ["python", "main.py"]
