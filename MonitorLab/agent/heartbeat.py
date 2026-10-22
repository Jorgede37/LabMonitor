
import threading

import requests

import config
from logger import logger


# ==========================================
# CONFIGURACION
# ==========================================

INTERVALO_HEARTBEAT = 5


def iniciar_heartbeat(
    detener: threading.Event
):

    logger.info(
        "Heartbeat iniciado"
    )

    while not detener.is_set():
        url = config.SERVER_URL
        token = config.AGENT_TOKEN

        if not url or not token:
            detener.wait(INTERVALO_HEARTBEAT)
            continue

        try:
            respuesta = requests.post(
                f"{url}/agent/heartbeat",
                headers={
                    "Authorization": f"Bearer {token}"
                },
                json={},
                timeout=10
            )

            respuesta.raise_for_status()

            logger.info(
                "Heartbeat del agente enviado."
            )

        except requests.RequestException as error:

            logger.warning(
                "No se pudo enviar heartbeat: %s",
                error
            )

        detener.wait(
            INTERVALO_HEARTBEAT
        )

    logger.info(
        "Heartbeat detenido"
    )
