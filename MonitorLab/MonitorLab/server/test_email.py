
from app.email_service import (
    enviar_correo,
    enviar_alerta_hardware
)


def main():
    print("=" * 45)
    print("LABMONITOR - PRUEBA DE CORREO")
    print("=" * 45)

    destinatario = input(
        "\nCorreo que recibirá la prueba: "
    ).strip()

    if not destinatario:
        print("Debes escribir un correo.")
        return

    try:
        print("\n[1/2] Enviando correo de prueba...")

        enviar_correo(
            destinatario=destinatario,
            asunto="LabMonitor - Prueba de correo",
            mensaje=(
                "Hola.\n\n"
                "Este es un correo de prueba enviado "
                "desde LabMonitor.\n\n"
                "El servicio SMTP funciona correctamente.\n\n"
                "Departamento de Sistemas UAD."
            )
        )

        print("Correo de prueba enviado.")

        print("\n[2/2] Enviando alerta de hardware...")

        enviar_alerta_hardware(
            computadora="LAB-A-PC-01",
            laboratorio="Laboratorio A",
            evento="DEVICE_DISCONNECTED",
            componente="Mouse USB",
            fecha="09/10/2026 08:30:00",
            estudiante="0923033030",
            destinatarios=[destinatario]
        )

        print("Alerta de hardware enviada.")

        print("\n" + "=" * 45)
        print("PRUEBA FINALIZADA CORRECTAMENTE")
        print("=" * 45)

        print(
            "\nRevisa la bandeja de entrada "
            "del correo destinatario."
        )

    except Exception as error:
        print("\nERROR DURANTE LA PRUEBA")
        print("Tipo:", type(error).__name__)
        print("Detalle:", str(error))


if __name__ == "__main__":
    main()
