
import os
import logging

from logging.handlers import RotatingFileHandler
from pathlib import Path


# ==========================================
# CONFIGURACIÓN DE RUTAS
# ==========================================

AGENT_DIR = Path(__file__).resolve().parent

PROGRAM_DATA = Path(
    os.environ.get(
        "PROGRAMDATA",
        str(AGENT_DIR)
    )
)

LABMONITOR_DIR = PROGRAM_DATA / "LabMonitor"

LOG_DIR = LABMONITOR_DIR / "logs"

LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "labmonitor.log"


# ==========================================
# CONFIGURACIÓN DEL LOGGER
# ==========================================

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
