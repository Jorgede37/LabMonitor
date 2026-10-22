
import os
from pathlib import Path

from dotenv import load_dotenv

AGENT_DIR = Path(__file__).resolve().parent

load_dotenv(AGENT_DIR / ".env")

SERVER_URL = os.getenv(
    "LABMONITOR_SERVER_URL",
    "http://127.0.0.1:8000"
)

ENROLLMENT_KEY = os.getenv("AGENT_ENROLLMENT_KEY")

if not ENROLLMENT_KEY:
    raise RuntimeError(
        "Falta AGENT_ENROLLMENT_KEY en agent/.env"
    )
