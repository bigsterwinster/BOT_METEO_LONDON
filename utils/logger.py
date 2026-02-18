import logging
import os

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "bot.log")

logger = logging.getLogger("polymarket_weather_bot")
logger.setLevel(logging.DEBUG)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_fmt = logging.Formatter("[%(asctime)s] %(levelname)s — %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
console_handler.setFormatter(console_fmt)

# File handler
file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setLevel(logging.DEBUG)
file_fmt = logging.Formatter("[%(asctime)s] %(levelname)s [%(module)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
file_handler.setFormatter(file_fmt)

logger.addHandler(console_handler)
logger.addHandler(file_handler)


def log(message: str, level: str = "info"):
    """Shortcut for logging a message at the given level."""
    getattr(logger, level, logger.info)(message)
