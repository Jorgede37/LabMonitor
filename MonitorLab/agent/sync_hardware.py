
import requests

import config
from hardware import obtener_inventario


# ==========================================
# SINCRONIZAR INVENTARIO
# ==========================================

def sincronizar(inventario=None):

    if not config.AGENT_TOKEN:
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

    tipos_completos = inventario.get("complete_types", [])
    tipos_completos_set = set(tipos_completos)
    componentes = [
        componente
        for componente in inventario["components"]
        if componente["component_type"] in tipos_completos_set
    ]
    completo = inventario["complete"]
    errores = inventario["errors"]

    print("\n===== SINCRONIZACIÓN LABMONITOR =====")
    print("Componentes detectados:", len(componentes))
    print("Inventario completo:", completo)

    if not tipos_completos:

        print(
            "Sincronización cancelada: "
            "ninguna categoría se consultó correctamente."
        )

        for error in errores:
            print("ERROR:", error)

        return False

    try:

        respuesta = requests.post(
            f"{config.SERVER_URL}/agent/hardware/sync",
            json={
                "components": componentes,
                "complete": completo,
                "complete_types": tipos_completos
            },
            headers={
                "Authorization": f"Bearer {config.AGENT_TOKEN}"
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
