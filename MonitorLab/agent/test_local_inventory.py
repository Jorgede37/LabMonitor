
from local_database import (
    inicializar_inventario_local,
    obtener_inventario_local
)


def probar_inventario():
    print("\n===== INVENTARIO LOCAL LABMONITOR =====")

    inicializar_inventario_local()

    componentes = obtener_inventario_local()

    print("Tabla local_hardware creada correctamente")
    print("Componentes almacenados:", len(componentes))

    for componente in componentes:
        print(
            componente["component_type"],
            "|",
            componente["model"],
            "|",
            componente["status"]
        )


if __name__ == "__main__":
    probar_inventario()
