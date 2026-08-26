"""
Logging setup for the tech-briefing pipeline.
Call setupLogging() once from main.py at startup.
All other modules get the logger via: log = logging.getLogger("tech_briefing")

Writes to both stdout (for docker compose output) and logs/pipeline.log (append).
Each run is clearly separated by a header line so you can scroll the log and
immediately see where one Monday's run ends and the next begins.
"""

import logging
import os
import datetime

from src.config import IS_LAMBDA

# Lambda's filesystem is read-only outside /tmp, so the relative "logs/" dir used
# locally doesn't exist there -- this is the exact crash that was happening before
# (OSError: Read-only file system: 'logs'). /tmp is per-invocation and not persisted
# across cold starts, which is fine here: readLogTail() only needs the current run's
# log for a failure alert, not history across runs.
LOG_PATH = "/tmp/pipeline.log" if IS_LAMBDA else os.path.join("logs", "pipeline.log")

# Matches the tag style used in print() calls previously -- keeps grep-ability
LOG_FORMAT  = "%(asctime)s [%(levelname)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setupLogging():
    """
    Configures the tech_briefing logger with console and file handlers.
    Safe to call multiple times -- skips setup if handlers already exist.
    @returns logging.Logger
    """
    logger = logging.getLogger("tech_briefing")

    # Guard against duplicate handlers if setupLogging() is somehow called twice
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # Console handler -- docker compose run shows this in the terminal
    consoleHandler = logging.StreamHandler()
    consoleHandler.setFormatter(formatter)
    logger.addHandler(consoleHandler)

    # File handler -- appends to data/pipeline.log; created on first run
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    fileHandler = logging.FileHandler(LOG_PATH, mode="a", encoding="utf-8")
    fileHandler.setFormatter(formatter)
    logger.addHandler(fileHandler)

    # Write a clear run separator so individual runs are easy to find in the log
    runStart = datetime.datetime.now().strftime(DATE_FORMAT)
    separator = f"\n{'=' * 60}\n  Pipeline run started: {runStart}\n{'=' * 60}"
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(separator + "\n")

    return logger


def readLogTail(lineCount=50):
    """
    Reads the last N lines of the log file for inclusion in failure alert emails.
    @param lineCount (int) - number of lines to return, must be > 0
    @returns (str) last N lines of the log, or a message if the log is unavailable
    @throws ValueError if lineCount is not positive
    """
    if lineCount <= 0:
        raise ValueError(f"lineCount must be positive, got {lineCount}")

    if not os.path.exists(LOG_PATH):
        return "(log file not yet created)"

    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return "".join(lines[-lineCount:])
    except OSError as e:
        return f"(could not read log file: {e})"
