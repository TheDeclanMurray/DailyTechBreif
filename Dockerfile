# Lambda-compatible base: Amazon Linux 2023 + the Lambda Runtime Interface Client,
# replacing the python:3.12-slim base this image used before the AWS migration.
# This same image serves both local dev (via docker-compose.yml, which overrides the
# entrypoint/command below to run the pipeline as a plain script) and the deployed
# Lambda (which uses the Lambda-handler CMD as-is) -- one build, two invocation modes.
FROM public.ecr.aws/lambda/python:3.12

# --- System dependencies ---
# wget/tar/xz: download and unpack the piper and ffmpeg tarballs below.
# This base image uses dnf (microdnf under the hood), not apt-get -- Debian package
# names/availability don't carry over. Two things dropped from the old apt-get list:
#   - ffmpeg isn't in AL2023's default repos, so it's pulled as a static build instead
#     (see the ffmpeg step further down) rather than installed via dnf.
#   - libespeak-ng1 isn't installed via dnf either: the piper release tarball already
#     bundles libespeak-ng.so.1 alongside the piper binary, so no separate system
#     package is needed for it on either base image.
RUN dnf install -y wget tar gzip xz ca-certificates \
    && dnf clean all

# --- Install piper-tts binary and its bundled shared libraries ---
# Unchanged from the previous base image -- the tarball ships the piper binary AND
# every .so it depends on (libpiper_phonemize, libonnxruntime, libespeak-ng, etc), so
# nothing extra needs installing for piper itself regardless of the base OS.
# Adjust the version tag here if a newer release is available:
# https://github.com/rhasspy/piper/releases
ARG PIPER_VERSION=2023.11.14-2
RUN wget -q "https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}/piper_linux_x86_64.tar.gz" \
    -O /tmp/piper.tar.gz \
    && tar -xzf /tmp/piper.tar.gz -C /tmp \
    && mv /tmp/piper /usr/local/lib/piper \
    && chmod +x /usr/local/lib/piper/piper \
    && ln -s /usr/local/lib/piper/piper /usr/local/bin/piper \
    && rm -f /tmp/piper.tar.gz

# Point the dynamic linker at piper's bundled .so files via LD_LIBRARY_PATH instead of
# `ldconfig` -- this minimal Lambda base image doesn't ship the `ldconfig` binary
# (unlike python:3.12-slim, where it's part of glibc's default install), and an env
# var accomplishes the same thing without depending on it.
ENV LD_LIBRARY_PATH="/usr/local/lib/piper:${LD_LIBRARY_PATH}"

# --- Install a static ffmpeg build ---
# AL2023's default dnf repos don't carry ffmpeg (licensing), so a self-contained
# static binary (no shared-library dependencies of its own) is downloaded instead --
# the standard workaround for getting ffmpeg into a Lambda container image.
RUN wget -q "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz" \
    -O /tmp/ffmpeg.tar.xz \
    && mkdir -p /tmp/ffmpeg-extract \
    && tar -xJf /tmp/ffmpeg.tar.xz -C /tmp/ffmpeg-extract --strip-components=1 \
    && mv /tmp/ffmpeg-extract/ffmpeg /usr/local/bin/ffmpeg \
    && chmod +x /usr/local/bin/ffmpeg \
    && rm -rf /tmp/ffmpeg.tar.xz /tmp/ffmpeg-extract

# --- Download voice model ---
# The model is baked into the image so the container runs fully offline. Kept at a
# fixed absolute path independent of WORKDIR (below), since TTS_MODEL_DIR in
# src/config.py points here directly regardless of base image.
# To change voices, update TTS_VOICE in .env AND update the model name here,
# then rebuild the image with: docker compose build
ARG TTS_VOICE=en_GB-jenny_dioco-medium
RUN mkdir -p /app/models \
    && wget -q "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/jenny_dioco/medium/${TTS_VOICE}.onnx" \
        -O "/app/models/${TTS_VOICE}.onnx" \
    && wget -q "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/jenny_dioco/medium/${TTS_VOICE}.onnx.json" \
        -O "/app/models/${TTS_VOICE}.onnx.json"

ENV PYTHONUNBUFFERED=1

# The Lambda Python base image already expects the handler module under
# $LAMBDA_TASK_ROOT (/var/task) -- keep app code there instead of /app so the Lambda
# Runtime Interface Client can find src.lambda_handler.handler without extra config.
WORKDIR ${LAMBDA_TASK_ROOT}

# --- Python dependencies ---
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Application source ---
COPY src/ ./src/

# Lambda's Runtime Interface Client invokes this as module.function -- resolves to
# src/lambda_handler.py's handler(event, context). docker-compose.yml overrides both
# entrypoint and command for local dev, so this CMD only ever runs for real in Lambda.
CMD ["src.lambda_handler.handler"]
