
import requests

import config
from local_database import (
    obtener_pendientes,
    marcar_enviado
)


# ==========================================
# SINCRONIZAR EVENTOS PENDIENTES
# ==========================================

def sincronizar_eventos():

    print("\n===== SINCRONIZACIÓN DE EVENTOS =====")

    if not config.AGENT_TOKEN:
        print("ERROR: Falta AGENT_TOKEN")
        return False

    pendientes = obtener_pendientes()

    print("Eventos pendientes:", len(pendientes))

    if not pendientes:
        print("No hay eventos por enviar.")
        return True

    # Enviar en lotes de máximo 100 eventos
    for inicio in range(0, len(pendientes), 100):

        lote = pendientes[inicio:inicio + 100]

        eventos = []

        for evento in lote:
            eventos.append({
                "event_uuid": evento["event_uuid"],
                "component_type": evento["component_type"],
                "hardware_identifier": evento[
                    "hardware_identifier"
                ],
                "event_type": evento["event_type"],
                "previous_value": evento["previous_value"],
                "new_value": evento["new_value"],
                "detected_at": evento["detected_at"]
            })

        try:
            respuesta = requests.post(
                f"{config.SERVER_URL}/agent/events/sync",
                json={"events": eventos},
                headers={
                    "Authorization": f"Bearer {config.AGENT_TOKEN}"
                },
                timeout=30
            )

        except requests.RequestException as error:
            print("Error de conexión:", error)
            return False

        print("Código HTTP:", respuesta.status_code)
        print("Respuesta:", respuesta.text)

        if respuesta.status_code != 200:
            print("El servidor rechazó el lote.")
            return False

        try:
            datos = respuesta.json()

            confirmados = set(
                datos.get("accepted", [])
                + datos.get("duplicates", [])
            )

            enviados = {
                evento["event_uuid"]
                for evento in lote
            }

            # Solo aceptar confirmaciones de este lote
            if confirmados != enviados:
                print(
                    "ERROR: Confirmación incompleta "
                    "o inesperada del servidor."
                )
                return False

            for event_uuid in confirmados:
                marcar_enviado(event_uuid)

            print(
                "Eventos confirmados:",
                len(confirmados)
            )

        except (ValueError, TypeError, KeyError) as error:
            print("Error procesando respuesta:", error)
            return False

    print("\nSincronización de eventos finalizada.")
    return True


if __name__ == "__main__":
    sincronizar_eventos()
