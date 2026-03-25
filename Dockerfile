FROM python:3.12-slim

# Install git + basic tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Clone repo at build time (this runs once)
ARG GITHUB_REPO
ARG GH_TOKEN
RUN if [ -n "$GITHUB_REPO" ] && [ -n "$GH_TOKEN" ]; then \
      git clone https://${GH_TOKEN}@github.com/The-No-Hands-company/Claude-alt.git /repo; \
    else \
      echo "Warning: Missing GITHUB_REPO or GH_TOKEN at build time" && mkdir -p /repo; \
    fi

# Use the cloned repo
ENV REPO_DIR=/repo

EXPOSE 8000

CMD ["python", "main.py"]
