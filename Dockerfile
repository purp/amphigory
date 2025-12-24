FROM debian:bookworm-slim

# Install base dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    python3.11 \
    python3-pip \
    python3.11-venv \
    handbrake-cli \
    && rm -rf /var/lib/apt/lists/*

# Note: MakeMKV is NOT installed in the container.
# Optical drive access is handled by the native macOS daemon.
# The daemon rips to shared storage, then HandBrakeCLI here transcodes.

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY config/ ./config/

# Create directories for data
RUN mkdir -p /data /media/ripped /media/plex/inbox /media/plex/data /wiki

ENV PYTHONPATH=/app/src
ENV AMPHIGORY_CONFIG=/config
ENV AMPHIGORY_DATA=/data

EXPOSE 6199

CMD ["uvicorn", "amphigory.main:app", "--host", "0.0.0.0", "--port", "6199"]
