
import requests

from config import SERVER_URL, ENROLLMENT_KEY

from agent import (
    obtener_hostname,
    obtener_mac,
    obtener_ip,
    obtener_sistema_operativo,
    obtener_uuid,
    obtener_numero_serie
)


def registrar_computadora():

    computadora = {
        "hostname": obtener_hostname(),
        "mac_address": obtener_mac(),
        "serial_number": obtener_numero_serie(),
        "machine_uuid": obtener_uuid(),
        "ip_address": obtener_ip(),
        "operating_system": obtener_sistema_operativo()
    }

    print("\n===== REGISTRO LABMONITOR =====")
    print("Computadora:", computadora["hostname"])
    print("MAC:", computadora["mac_address"])

    try:
        respuesta = requests.post(
            f"{SERVER_URL}/computers/register",
            json=computadora,
            headers={
                "X-Enrollment-Key": ENROLLMENT_KEY
            },
            timeout=10
        )

        if respuesta.status_code == 201:
            datos = respuesta.json()

            print("\nRegistro exitoso")
            print("ID:", datos["computer_id"])
            print("Hostname:", datos["hostname"])

        elif respuesta.status_code == 409:
            print("\nEsta computadora ya está registrada.")
            print(respuesta.json())

        else:
            print("\nError del servidor")
            print("Código HTTP:", respuesta.status_code)
            print(respuesta.text)

    except requests.RequestException as error:
        print("\nNo se pudo conectar con LabMonitor:")
        print(error)


if __name__ == "__main__":
    registrar_computadora()
