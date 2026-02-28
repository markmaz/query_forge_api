import logging
import os

from dotenv import load_dotenv


def configure_logging():
    load_dotenv()
    log_file = os.getenv("LOG_FILE", "default_log")
    level_name = str(os.getenv("LOG_LEVEL", "INFO")).strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        level=level,
        handlers=[logging.FileHandler(log_file, mode="a", encoding="utf-8"), logging.StreamHandler()],
        force=True,
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.info("Global logging configured at level=%s", logging.getLevelName(level))
