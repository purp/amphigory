FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    ca-certificates \
    libdvdcss2 \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install MakeMKV
# Note: This is a placeholder - actual MakeMKV installation is more complex
# and may require building from source or using a pre-built package
RUN echo "MakeMKV installation placeholder - see docs for actual setup"

# Install HandBrakeCLI
RUN apt-get update && apt-get install -y --no-install-recommends \
    handbrake-cli \
    && rm -rf /var/lib/apt/lists/*

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

EXPOSE 8080

CMD ["uvicorn", "amphigory.main:app", "--host", "0.0.0.0", "--port", "8080"]
