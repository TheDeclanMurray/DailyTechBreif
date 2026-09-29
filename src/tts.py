"""
Text-to-speech conversion using piper-tts and ffmpeg.

Pipeline:
  1. piper reads text from stdin, writes raw PCM (s16le) to stdout
  2. ffmpeg reads that PCM from stdin, applies atempo speed adjustment,
     encodes to MP3 in memory -- pitch is preserved, the WAV is never held
     in memory alongside the MP3

Both binaries are installed in the Docker image at build time.
"""

import os
import sys
import logging
import subprocess

from src.config import TTS_VOICE, TTS_SPEED, TTS_MODEL_DIR

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

# Raw PCM format piper emits via --output-raw (headerless s16le).
# These values are model-specific -- en_GB-jenny_dioco-medium.onnx.json confirms
# sample_rate=22050; channels defaults to 1 (mono) when absent from the model config.
# Update if TTS_VOICE is changed to a model with different audio properties.
PIPER_SAMPLE_RATE = 22050
PIPER_CHANNELS    = 1


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
    without altering pitch. The MP3 is never written to disk -- ffmpeg streams it
    to stdout and this function returns the raw bytes, since the only consumer
    (mailer.sendBriefing) just attaches it to an email and discards it.
    @param text (str) - briefing script to convert, must be non-empty
    @returns (bytes) the MP3 file content
    @throws ValueError if text is empty or TTS_SPEED is out of range
    @throws SystemExit if piper or ffmpeg fail
    """
    if not text or not text.strip():
        raise ValueError("text must not be empty")

    _validateSpeed(TTS_SPEED)
    _validateDependencies()

    modelFile = _modelPath()

    log.info("TTS voice: '%s' | speed: %sx (pitch-corrected via ffmpeg atempo)", TTS_VOICE, TTS_SPEED)
    log.info("Input text: %s characters", f"{len(text):,}")

    # Pipe piper's raw PCM output directly into ffmpeg so the full WAV is never
    # held in memory alongside the encoded MP3.  piper --output-raw writes
    # headerless s16le PCM; ffmpeg reads it with explicit format hints since
    # there is no WAV header to sniff from.
    piperCmd = [
        PIPER_BINARY,
        "--model",        modelFile,
        "--output-raw",
    ]

    ffmpegCmd = [
        FFMPEG_BINARY,
        "-y",
        "-f",        "s16le",
        "-ar",       str(PIPER_SAMPLE_RATE),
        "-ac",       str(PIPER_CHANNELS),
        "-i",        "pipe:0",
        "-filter:a", f"atempo={TTS_SPEED}",
        "-q:a",      "2",
        "-f",        "mp3",
        "pipe:1",
    ]

    piperProc = subprocess.Popen(
        piperCmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    ffmpegProc = subprocess.Popen(
        ffmpegCmd,
        stdin=piperProc.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Close our reference to piper's stdout so ffmpeg holds the only open end;
    # ffmpeg will see EOF when piper exits naturally.
    piperProc.stdout.close()

    piperProc.stdin.write(text.encode("utf-8"))
    piperProc.stdin.close()

    mp3Bytes, ffmpegStderr = ffmpegProc.communicate()
    piperStderr = piperProc.stderr.read()

    if piperProc.wait() != 0:
        log.error("piper failed (exit %d):\n%s", piperProc.returncode, piperStderr.decode("utf-8", errors="replace"))
        sys.exit(1)

    if ffmpegProc.returncode != 0:
        log.error("ffmpeg failed (exit %d):\n%s", ffmpegProc.returncode, ffmpegStderr.decode("utf-8", errors="replace"))
        sys.exit(1)

    log.info("MP3 encoded in memory (%s bytes / %d KB).", f"{len(mp3Bytes):,}", len(mp3Bytes) // 1024)
    return mp3Bytes
