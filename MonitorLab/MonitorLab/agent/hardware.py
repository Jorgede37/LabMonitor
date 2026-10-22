
import wmi


TIPOS_HARDWARE = (
    "ram",
    "gpu",
    "storage",
    "mouse",
    "keyboard",
    "network"
)


class ErrorInventarioHardware(Exception):
    pass


def limpiar_texto(valor):
    if valor is None:
        return None

    texto = str(valor).strip()
    return texto or None


def crear_componente(
    tipo,
    fabricante,
    modelo,
    serie,
    identificador
):
    identificador = limpiar_texto(identificador)

    if not identificador:
        raise ErrorInventarioHardware(
            f"Componente {tipo} sin identificador"
        )

    return {
        "component_type": tipo,
        "manufacturer": limpiar_texto(fabricante),
        "model": limpiar_texto(modelo),
        "serial_number": limpiar_texto(serie),
        "hardware_identifier": identificador
    }


def obtener_inventario():
    sistema = wmi.WMI()

    componentes = []
    errores = []
    cantidades = {}

    # =====================================
    # MEMORIA RAM
    # =====================================
    try:
        memorias = sistema.Win32_PhysicalMemory()

        for ram in memorias:
            numero_serie = limpiar_texto(ram.SerialNumber)
            capacidad = int(ram.Capacity)

            identificador = (
                f"RAM:{numero_serie}"
                if numero_serie
                and numero_serie.lower() not in (
                    "unknown", "none", "00000000"
                )
                else f"SLOT:{ram.Tag}"
            )

            componentes.append(
                crear_componente(
                    "ram",
                    ram.Manufacturer,
                    f"{capacidad // (1024**3)} GB",
                    numero_serie,
                    identificador
                )
            )

        cantidades["ram"] = len(memorias)

    except Exception as error:
        errores.append(f"RAM: {error}")

    # =====================================
    # TARJETAS GRAFICAS
    # =====================================
    try:
        graficas = sistema.Win32_VideoController()

        for gpu in graficas:
            componentes.append(
                crear_componente(
                    "gpu",
                    None,
                    gpu.Name,
                    None,
                    gpu.PNPDeviceID
                )
            )

        cantidades["gpu"] = len(graficas)

    except Exception as error:
        errores.append(f"GPU: {error}")

    # =====================================
    # ALMACENAMIENTO
    # =====================================
    try:
        discos = sistema.Win32_DiskDrive()

        for disco in discos:
            componentes.append(
                crear_componente(
                    "storage",
                    disco.Manufacturer,
                    disco.Model,
                    disco.SerialNumber,
                    disco.PNPDeviceID
                )
            )

        cantidades["storage"] = len(discos)

    except Exception as error:
        errores.append(f"Almacenamiento: {error}")

    # =====================================
    # MOUSE
    # =====================================
    try:
        ratones = sistema.Win32_PointingDevice()

        for mouse in ratones:
            componentes.append(
                crear_componente(
                    "mouse",
                    mouse.Manufacturer,
                    mouse.Name,
                    None,
                    mouse.PNPDeviceID
                )
            )

        cantidades["mouse"] = len(ratones)

    except Exception as error:
        errores.append(f"Mouse: {error}")

    # =====================================
    # TECLADOS
    # =====================================
    try:
        teclados = sistema.Win32_Keyboard()

        for teclado in teclados:
            componentes.append(
                crear_componente(
                    "keyboard",
                    None,
                    teclado.Name,
                    None,
                    teclado.PNPDeviceID
                )
            )

        cantidades["keyboard"] = len(teclados)

    except Exception as error:
        errores.append(f"Teclado: {error}")

    # =====================================
    # ADAPTADORES DE RED
    # =====================================
    try:
        adaptadores = sistema.Win32_NetworkAdapter()

        redes = [
            red for red in adaptadores
            if red.PhysicalAdapter and red.MACAddress
        ]

        for red in redes:
            componentes.append(
                crear_componente(
                    "network",
                    red.Manufacturer,
                    red.Name,
                    None,
                    red.PNPDeviceID
                )
            )

        cantidades["network"] = len(redes)

    except Exception as error:
        errores.append(f"Red: {error}")

    # =====================================
    # VALIDACION DEL INVENTARIO
    # =====================================
    tipos_obligatorios = (
        "ram",
        "gpu",
        "storage",
        "keyboard"
    )

    for tipo in tipos_obligatorios:
        if cantidades.get(tipo, 0) == 0:
            errores.append(
                f"No se detectaron componentes: {tipo}"
            )

    identificadores = set()

    for componente in componentes:
        clave = (
            componente["component_type"],
            componente["hardware_identifier"]
        )

        if clave in identificadores:
            errores.append(
                f"Identificador duplicado: {clave}"
            )

        identificadores.add(clave)

    completo = len(errores) == 0

    return {
        "components": componentes,
        "complete": completo,
        "errors": errores,
        "counts": cantidades
    }


# Mantener compatibilidad con otros archivos
def obtener_componentes():
    inventario = obtener_inventario()
    return inventario["components"]


if __name__ == "__main__":
    inventario = obtener_inventario()

    print("\n===== INVENTARIO DE HARDWARE =====")

    for componente in inventario["components"]:
        print("\n------------------------")
        print("Tipo:", componente["component_type"])
        print("Fabricante:", componente["manufacturer"])
        print("Modelo:", componente["model"])
        print("Serie:", componente["serial_number"])
        print(
            "Identificador:",
            componente["hardware_identifier"]
        )

    print(
        "\nTotal de componentes:",
        len(inventario["components"])
    )

    print(
        "Inventario completo:",
        inventario["complete"]
    )

    print("Componentes por tipo:", inventario["counts"])

    if inventario["errors"]:
        print("\nERRORES DETECTADOS:")

        for error in inventario["errors"]:
            print("-", error)
