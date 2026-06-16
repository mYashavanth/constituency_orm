import os
import logging
from pathlib import Path

# Base project directory
PROJECT_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_DIR / "logs"

# Ensure log directory exists
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "extraction.log"

# Define logging format
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8")
    ]
)

logger = logging.getLogger("electoral_roll_extractor")

logger.info(f"Logging initialized. Log file location: {LOG_FILE}")
