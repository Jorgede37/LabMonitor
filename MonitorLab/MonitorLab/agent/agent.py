
import socket
import uuid
import platform

import psutil
import wmi


def obtener_hostname():
    return socket.gethostname()


def obtener_mac():
    mac = uuid.getnode()

    return ":".join(
        f"{(mac >> i) & 0xff:02X}"
        for i in range(40, -1, -8)
    )


def obtener_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 80))
            return s.getsockname()[0]
    except OSError:
        return "No disponible"


def obtener_sistema_operativo():
    return platform.platform()


def obtener_uuid():
    sistema = wmi.WMI()

    for equipo in sistema.Win32_ComputerSystemProduct():
        return equipo.UUID

    return None


def obtener_numero_serie():
    sistema = wmi.WMI()

    for bios in sistema.Win32_BIOS():
        return bios.SerialNumber

    return None


def obtener_ram():
    sistema = wmi.WMI()
    memorias = []

    for memoria in sistema.Win32_PhysicalMemory():
        memorias.append({
            "fabricante": memoria.Manufacturer,
            "capacidad_gb": round(
                int(memoria.Capacity) / (1024 ** 3), 2
            ),
            "numero_serie": memoria.SerialNumber
        })

    return memorias


def obtener_gpu():
    sistema = wmi.WMI()
    tarjetas = []

    for gpu in sistema.Win32_VideoController():
        tarjetas.append({
            "nombre": gpu.Name,
            "identificador": gpu.PNPDeviceID
        })

    return tarjetas


def mostrar_informacion():
    print("\n===== LABMONITOR AGENT =====\n")

    print("Hostname:", obtener_hostname())
    print("MAC:", obtener_mac())
    print("IP:", obtener_ip())
    print("Sistema operativo:", obtener_sistema_operativo())
    print("UUID:", obtener_uuid())
    print("Número de serie:", obtener_numero_serie())

    print("\n--- Memoria RAM ---")
    for memoria in obtener_ram():
        print(memoria)

    print("\n--- Tarjetas gráficas ---")
    for gpu in obtener_gpu():
        print(gpu)

    print("\n===== FIN DEL INVENTARIO =====")


if __name__ == "__main__":
    mostrar_informacion()
