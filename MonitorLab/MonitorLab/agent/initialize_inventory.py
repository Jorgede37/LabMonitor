
from hardware import obtener_inventario

from local_database import (
    guardar_inventario_inicial,
    obtener_inventario_local
)


def inicializar():
    print("\n===== INICIALIZACIÓN LABMONITOR =====")

    inventario = obtener_inventario()

    if not inventario["complete"]:
        print("ERROR: Inventario WMI incompleto.")

        for error in inventario["errors"]:
            print("-", error)

        return

    componentes = inventario["components"]

    print("Componentes detectados:", len(componentes))

    resultado = guardar_inventario_inicial(componentes)

    if resultado:
        print("Inventario inicial guardado correctamente.")
    else:
        print("Se conserva el inventario existente.")

    almacenados = obtener_inventario_local()

    print("Componentes almacenados:", len(almacenados))


if __name__ == "__main__":
    inicializar()
