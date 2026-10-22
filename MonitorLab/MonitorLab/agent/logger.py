
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


AGENT_DIR = Path(__file__).resolve().parent
LOG_DIR = AGENT_DIR / "logs"

LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "labmonitor.log"


def configurar_logger():
    logger = logging.getLogger("LabMonitor")
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    formato = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    archivo = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8"
    )

    archivo.setFormatter(formato)
    logger.addHandler(archivo)

    return logger


logger = configurar_logger()
