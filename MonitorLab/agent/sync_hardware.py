
import os

from pathlib import Path

import requests
from dotenv import load_dotenv

from config import SERVER_URL
from hardware import obtener_inventario


# ==========================================
# CONFIGURACIÓN
# ==========================================

AGENT_DIR = Path(__file__).resolve().parent

load_dotenv(AGENT_DIR / ".env")

AGENT_TOKEN = os.getenv("AGENT_TOKEN")


# ==========================================
# SINCRONIZAR INVENTARIO
# ==========================================

def sincronizar(inventario=None):

    if not AGENT_TOKEN:
        print("ERROR: Falta AGENT_TOKEN")
        return False

    # Reutilizar el inventario obtenido
    # por el monitor automático.
    if inventario is None:

        try:
            inventario = obtener_inventario()

        except Exception as error:
            print(
                "ERROR al obtener inventario:",
                error
            )
            return False

    componentes = inventario["components"]
    completo = inventario["complete"]
    errores = inventario["errors"]

    print("\n===== SINCRONIZACIÓN LABMONITOR =====")
    print("Componentes detectados:", len(componentes))
    print("Inventario completo:", completo)

    if not completo:

        print(
            "Sincronización cancelada: "
            "inventario incompleto."
        )

        for error in errores:
            print("ERROR:", error)

        return False

    try:

        respuesta = requests.post(
            f"{SERVER_URL}/agent/hardware/sync",
            json={
                "components": componentes,
                "complete": completo
            },
            headers={
                "Authorization": f"Bearer {AGENT_TOKEN}"
            },
            timeout=30
        )

        print("Código HTTP:", respuesta.status_code)
        print("Respuesta:", respuesta.text)

        return respuesta.status_code == 200

    except requests.RequestException as error:

        print("Error de conexión:", error)

        return False


# ==========================================
# EJECUCIÓN MANUAL
# ==========================================

if __name__ == "__main__":
    sincronizar()
