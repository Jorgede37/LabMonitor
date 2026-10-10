
from local_database import (
    inicializar_base,
    guardar_evento,
    obtener_pendientes,
    marcar_enviado
)


def probar_base_local():
    print("\n===== PRUEBA SQLITE LABMONITOR =====")

    inicializar_base()

    # Crear un evento ficticio de prueba
    identificador = guardar_evento(
        component_type="mouse",
        hardware_identifier="MOUSE_TEST_001",
        event_type="DEVICE_DISCONNECTED",
        previous_value="active",
        new_value="removed"
    )

    print("\nEvento de prueba guardado")
    print("UUID:", identificador)

    # Consultar eventos pendientes
    pendientes = obtener_pendientes()

    print("\nEventos pendientes:", len(pendientes))

    for evento in pendientes:
        print(
            evento["event_type"],
            "|",
            evento["hardware_identifier"],
            "|",
            evento["detected_at"]
        )

    # Marcar únicamente nuestro evento de prueba
    marcar_enviado(identificador)

    pendientes = obtener_pendientes()

    print("\nPendientes después de marcar:", len(pendientes))


if __name__ == "__main__":
    probar_base_local()
