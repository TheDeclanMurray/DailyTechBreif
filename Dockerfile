FROM python:3.12-slim

# --- System dependencies ---
# ffmpeg: WAV -> MP3 conversion
# wget + tar: used to download and unpack piper binary
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    ffmpeg \
    wget \
    tar \
    libespeak-ng1 \
    && rm -rf /var/lib/apt/lists/*

# --- Install piper-tts binary and its bundled shared libraries ---
# The tarball ships the piper binary AND several .so files it depends on
# (libpiper_phonemize, libonnxruntime, etc). We keep them all together in
# /usr/local/lib/piper and add that directory to the dynamic linker path.
# Adjust the version tag here if a newer release is available:
# https://github.com/rhasspy/piper/releases
ARG PIPER_VERSION=2023.11.14-2
RUN wget -q "https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}/piper_linux_x86_64.tar.gz" \
    -O /tmp/piper.tar.gz \
    && tar -xzf /tmp/piper.tar.gz -C /tmp \
    && mv /tmp/piper /usr/local/lib/piper \
    && chmod +x /usr/local/lib/piper/piper \
    && ln -s /usr/local/lib/piper/piper /usr/local/bin/piper \
    && echo "/usr/local/lib/piper" > /etc/ld.so.conf.d/piper.conf \
    && ldconfig \
    && rm -f /tmp/piper.tar.gz

# --- Download voice model ---
# The model is baked into the image so the container runs fully offline.
# To change voices, update TTS_VOICE in .env AND update the model name here,
# then rebuild the image with: docker compose build
ARG TTS_VOICE=en_GB-jenny_dioco-medium
RUN mkdir -p /app/models \
    && wget -q "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/jenny_dioco/medium/${TTS_VOICE}.onnx" \
        -O "/app/models/${TTS_VOICE}.onnx" \
    && wget -q "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/jenny_dioco/medium/${TTS_VOICE}.onnx.json" \
        -O "/app/models/${TTS_VOICE}.onnx.json"

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# --- Python dependencies ---
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Application source ---
COPY src/ ./src/

# data/ is mounted at runtime — credentials, token, and output MP3 live there.
CMD ["python", "-m", "src.main"]
