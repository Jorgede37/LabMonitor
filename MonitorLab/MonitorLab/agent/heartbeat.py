import ctypes
import os
import threading

from pathlib import Path
from ctypes import wintypes

import requests
from dotenv import load_dotenv

from logger import logger


# ==========================================
# CONFIGURACION
# ==========================================

AGENT_DIR = Path(__file__).resolve().parent

load_dotenv(
    dotenv_path=AGENT_DIR / ".env"
)

INTERVALO_HEARTBEAT = 5


# ==========================================
# DETECTAR INACTIVIDAD DE WINDOWS
# ==========================================

class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD)
    ]


def obtener_inactividad_segundos():

    informacion = LASTINPUTINFO()
    informacion.cbSize = ctypes.sizeof(
        LASTINPUTINFO
    )

    resultado = ctypes.windll.user32.GetLastInputInfo(
        ctypes.byref(informacion)
    )

    if not resultado:
        raise OSError(
            "No se pudo consultar la actividad de Windows"
        )

    # GetTickCount64 evita problemas de desbordamiento
    # del contador de tiempo de Windows.

    tiempo_actual = (
        ctypes.windll.kernel32.GetTickCount64
    )

    tiempo_actual.restype = ctypes.c_ulonglong

    ticks_actuales = tiempo_actual()

    # dwTime utiliza un contador de 32 bits.
    # Calculamos la diferencia respetando ese formato.

    ticks_inactividad = (
        (ticks_actuales & 0xFFFFFFFF)
        - informacion.dwTime
    ) & 0xFFFFFFFF

    return ticks_inactividad // 1000


# ==========================================
# HEARTBEAT
# ==========================================

def iniciar_heartbeat(
    detener: threading.Event
):

    url = os.getenv(
        "LABMONITOR_SERVER_URL", ""
    ).rstrip("/")

    token = os.getenv(
        "AGENT_TOKEN", ""
    )

    if not url or not token:

        logger.error(
            "Heartbeat: faltan variables de configuracion"
        )

        return

    logger.info(
        "Heartbeat iniciado"
    )

    while not detener.is_set():

        try:

            inactividad = (
                obtener_inactividad_segundos()
            )

            respuesta = requests.post(
                f"{url}/agent/heartbeat",
                headers={
                    "Authorization": f"Bearer {token}"
                },
                json={
                    "idle_seconds": inactividad
                },
                timeout=10
            )

            respuesta.raise_for_status()

            logger.info(
                "Heartbeat enviado. "
                "Inactividad: %s segundos",
                inactividad
            )

        except requests.RequestException as error:

            logger.warning(
                "No se pudo enviar heartbeat: %s",
                error
            )

        except (OSError, AttributeError) as error:

            logger.error(
                "No se pudo detectar actividad: %s",
                error
            )

            # No enviamos una actividad inventada.
            # El Worker utilizara el timeout
            # de perdida de comunicacion.

        detener.wait(
            INTERVALO_HEARTBEAT
        )

    logger.info(
        "Heartbeat detenido"
    )