
import os
import sys

from pathlib import Path
from dotenv import load_dotenv


# ==========================================
# DETECTAR ENTORNO DE EJECUCION
# ==========================================

FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    # Carpeta donde se encuentra el ejecutable
    # generado mediante PyInstaller.
    AGENT_DIR = Path(sys.executable).resolve().parent
else:
    # Carpeta del proyecto durante el desarrollo.
    AGENT_DIR = Path(__file__).resolve().parent


# ==========================================
# CONFIGURACION PERSISTENTE
# ==========================================

PROGRAM_DATA = Path(
    os.environ.get(
        "PROGRAMDATA",
        str(AGENT_DIR)
    )
)

CONFIG_DIR = PROGRAM_DATA / "LabMonitor"
CONFIG_FILE = CONFIG_DIR / "agent.env"


# ==========================================
# CARGAR CONFIGURACION
# ==========================================

if not FROZEN:
    # Compatibilidad con desarrollo.
    # Nunca cargar el .env antiguo en el
    # ejecutable distribuido.
    LEGACY_CONFIG_FILE = AGENT_DIR / ".env"

    if LEGACY_CONFIG_FILE.is_file():
        load_dotenv(
            LEGACY_CONFIG_FILE,
            override=False
        )

# Configuración de cada computadora instalada.
if CONFIG_FILE.is_file():
    load_dotenv(
        CONFIG_FILE,
        override=True
    )


# ==========================================
# VARIABLES DEL AGENTE
# ==========================================

SERVER_URL = (
    os.getenv("LABMONITOR_SERVER_URL")
    or os.getenv("SERVER_URL")
    or "http://127.0.0.1:8000"
).rstrip("/")

ENROLLMENT_KEY = os.getenv(
    "AGENT_ENROLLMENT_KEY"
)

AGENT_TOKEN = os.getenv(
    "AGENT_TOKEN"
)

LOCAL_ADMIN_SECRET = os.getenv(
    "LABMONITOR_LOCAL_ADMIN_SECRET"
)


def actualizar_credenciales(url_servidor, token_agente):
    global SERVER_URL, AGENT_TOKEN

    SERVER_URL = url_servidor.rstrip("/")
    AGENT_TOKEN = token_agente
