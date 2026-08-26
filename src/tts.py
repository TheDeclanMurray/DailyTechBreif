"""
Text-to-speech conversion using piper-tts and ffmpeg.

Pipeline:
  1. piper generates a WAV at natural speed (pitch is preserved this way)
  2. ffmpeg speeds up the audio using the atempo filter, which adjusts tempo
     without raising pitch -- the same technique podcast apps use for 1.5x playback

Both binaries are installed in the Docker image at build time.
"""

import os
import sys
import logging
import subprocess
import tempfile

from src.config import TTS_VOICE, TTS_SPEED, TTS_MODEL_DIR, TTS_OUTPUT_PATH

log = logging.getLogger("tech_briefing")

PIPER_BINARY  = "/usr/local/bin/piper"
# The Lambda-base Dockerfile installs a static ffmpeg build to /usr/local/bin (no dnf
# package available on Amazon Linux 2023 -- see docs/DECISIONS.md) instead of apt-get's
# /usr/bin/ffmpeg on the old python:3.12-slim base. Confirmed via a real Lambda
# invocation 2026-08-26 that the old path doesn't exist on the new image.
FFMPEG_BINARY = "/usr/local/bin/ffmpeg"

# atempo must be between 0.5 and 2.0 -- ffmpeg hard limit
ATEMPO_MIN = 0.5
ATEMPO_MAX = 2.0


def _modelPath():
    """
    Returns the path to the .onnx voice model file.
    @returns (str) absolute path to the model file
    """
    return os.path.join(TTS_MODEL_DIR, f"{TTS_VOICE}.onnx")


def _validateDependencies():
    """
    Checks that piper, ffmpeg, and the voice model are all present.
    @throws SystemExit if any dependency is missing
    """
    if not os.path.exists(PIPER_BINARY):
        log.error("piper binary not found at '%s'. Rebuild the Docker image.", PIPER_BINARY)
        sys.exit(1)

    if not os.path.exists(FFMPEG_BINARY):
        log.error("ffmpeg not found at '%s'. Rebuild the Docker image.", FFMPEG_BINARY)
        sys.exit(1)

    modelFile = _modelPath()
    if not os.path.exists(modelFile):
        log.error(
            "Voice model not found at '%s'. TTS_VOICE='%s' must match a model baked into "
            "the image. Rebuild the Docker image or correct TTS_VOICE in .env.",
            modelFile, TTS_VOICE,
        )
        sys.exit(1)


def _validateSpeed(speed):
    """
    Validates that the atempo speed value is within ffmpeg's supported range.
    @param speed (float) - playback speed multiplier
    @throws ValueError if speed is outside 0.5 -- 2.0
    """
    if not (ATEMPO_MIN <= speed <= ATEMPO_MAX):
        raise ValueError(
            f"TTS_SPEED must be between {ATEMPO_MIN} and {ATEMPO_MAX}, got {speed}. "
            f"For speeds above 2.0 contact the developer to chain atempo filters."
        )


def convertToMp3(text):
    """
    Converts a text string to a pitch-corrected MP3 using piper-tts and ffmpeg.
    Piper generates speech at natural speed; ffmpeg applies tempo adjustment
    without altering pitch. Writes result to TTS_OUTPUT_PATH (data/briefing.mp3).
    @param text (str) - briefing script to convert, must be non-empty
    @returns (str) path to the output MP3 file
    @throws ValueError if text is empty or TTS_SPEED is out of range
    @throws SystemExit if piper or ffmpeg fail
    """
    if not text or not text.strip():
        raise ValueError("text must not be empty")

    _validateSpeed(TTS_SPEED)
    _validateDependencies()

    modelFile = _modelPath()
    os.makedirs(os.path.dirname(TTS_OUTPUT_PATH), exist_ok=True)

    log.info("TTS voice: '%s' | speed: %sx (pitch-corrected via ffmpeg atempo)", TTS_VOICE, TTS_SPEED)
    log.info("Input text: %s characters", f"{len(text):,}")

    # Step 1: piper reads text from stdin, writes WAV at natural speed (1.0).
    # We intentionally do NOT pass --length-scale -- pitch correction only works
    # cleanly when piper generates at its natural rate and ffmpeg handles speed.
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmpWav:
        tmpWavPath = tmpWav.name

    try:
        piperCmd = [
            PIPER_BINARY,
            "--model",       modelFile,
            "--output-file", tmpWavPath,
        ]

        piperResult = subprocess.run(
            piperCmd,
            input=text.encode("utf-8"),
            capture_output=True,
        )

        if piperResult.returncode != 0:
            errMsg = piperResult.stderr.decode("utf-8", errors="replace")
            log.error("piper failed (exit %d):\n%s", piperResult.returncode, errMsg)
            sys.exit(1)

        log.info("WAV generated (%s bytes). Applying %sx tempo...", f"{os.path.getsize(tmpWavPath):,}", TTS_SPEED)

        # Step 2: ffmpeg speeds up audio without changing pitch.
        # atempo=1.5 means 1.5x speed -- valid range 0.5 to 2.0.
        # -q:a 2 is ~190kbps VBR -- good quality for voice.
        ffmpegCmd = [
            FFMPEG_BINARY,
            "-y",
            "-i",           tmpWavPath,
            "-filter:a",    f"atempo={TTS_SPEED}",
            "-q:a",         "2",
            TTS_OUTPUT_PATH,
        ]

        ffmpegResult = subprocess.run(
            ffmpegCmd,
            capture_output=True,
        )

        if ffmpegResult.returncode != 0:
            errMsg = ffmpegResult.stderr.decode("utf-8", errors="replace")
            log.error("ffmpeg failed (exit %d):\n%s", ffmpegResult.returncode, errMsg)
            sys.exit(1)

    finally:
        # Always clean up the temp WAV
        if os.path.exists(tmpWavPath):
            os.remove(tmpWavPath)

    mp3Size = os.path.getsize(TTS_OUTPUT_PATH)
    log.info("MP3 written to '%s' (%s bytes / %d KB).", TTS_OUTPUT_PATH, f"{mp3Size:,}", mp3Size // 1024)
    return TTS_OUTPUT_PATH
