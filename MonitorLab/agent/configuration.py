
from session_manager import (
    solicitar_servidor,
    SessionManagerError,
)
import config
from agent import obtener_hostname


def consultar_configuracion_equipo():
    """
    Consulta la configuración de esta computadora
    utilizando la identidad autenticada del agente.

    No requiere token de estudiante.
    No modifica la configuración.
    """

    if not config.AGENT_TOKEN:
        hostname = obtener_hostname()
        return {
            "computer_id": None,
            "hostname": hostname,
            "display_name": hostname,
            "laboratory_id": None,
            "laboratory_name": None,
            "configured": False,
        }

    resultado = solicitar_servidor(
        metodo="GET",
        endpoint="/agent/configuration"
    )

    campos_requeridos = {
        "computer_id",
        "hostname",
        "display_name",
        "laboratory_id",
        "laboratory_name",
        "configured"
    }

    if not isinstance(resultado, dict):
        raise SessionManagerError(
            "El servidor devolvió una configuración inválida."
        )

    if not campos_requeridos.issubset(resultado):
        raise SessionManagerError(
            "La respuesta de configuración está incompleta."
        )

    if not isinstance(resultado["configured"], bool):
        raise SessionManagerError(
            "El estado de configuración es inválido."
        )

    return resultado
