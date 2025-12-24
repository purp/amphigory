# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm

# Build arg for git SHA (set at build time)
ARG GIT_SHA=dev
ENV GIT_SHA=${GIT_SHA}

# Install HandBrakeCLI (only non-Python dependency)
RUN apt-get update && apt-get install -y --no-install-recommends \
    handbrake-cli \
    && rm -rf /var/lib/apt/lists/*

# Note: MakeMKV is NOT installed in the container.
# Optical drive access is handled by the native macOS daemon.
# The daemon rips to shared storage, then HandBrakeCLI here transcodes.

WORKDIR /app

# Install Python dependencies (with BuildKit cache)
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

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
