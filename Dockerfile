FROM debian:bookworm-slim

# Install base dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    curl \
    gnupg \
    ca-certificates \
    git \
    build-essential \
    pkg-config \
    libc6-dev \
    libssl-dev \
    libexpat1-dev \
    libavcodec-dev \
    libgl1-mesa-dev \
    qtbase5-dev \
    zlib1g-dev \
    python3.11 \
    python3-pip \
    python3.11-venv \
    && rm -rf /var/lib/apt/lists/*

# Install libdvdcss for DVD decryption support
RUN apt-get update && apt-get install -y --no-install-recommends \
    libdvdcss2 \
    && rm -rf /var/lib/apt/lists/*

# Install MakeMKV from source
# Using latest version - check https://www.makemkv.com/download/ for updates
ENV MAKEMKV_VERSION=1.17.5
RUN wget https://www.makemkv.com/download/makemkv-bin-${MAKEMKV_VERSION}.tar.gz && \
    wget https://www.makemkv.com/download/makemkv-oss-${MAKEMKV_VERSION}.tar.gz && \
    tar xzf makemkv-bin-${MAKEMKV_VERSION}.tar.gz && \
    tar xzf makemkv-oss-${MAKEMKV_VERSION}.tar.gz && \
    cd makemkv-oss-${MAKEMKV_VERSION} && \
    ./configure && \
    make && \
    make install && \
    cd ../makemkv-bin-${MAKEMKV_VERSION} && \
    mkdir -p tmp && \
    echo "yes" | make install && \
    cd / && \
    rm -rf makemkv-* && \
    ldconfig

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
