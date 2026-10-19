
import wmi


TIPOS_HARDWARE = (
    "cpu",
    "motherboard",
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
    tipos_completos = []

    # =====================================
    # PROCESADORES
    # =====================================
    try:
        procesadores = sistema.Win32_Processor()

        for procesador in procesadores:
            identificador = limpiar_texto(
                procesador.ProcessorId
            )

            if (
                not identificador
                or identificador.lower() in (
                    "unknown",
                    "none",
                    "00000000"
                )
            ):
                identificador = limpiar_texto(
                    procesador.DeviceID
                )

            componentes.append(
                crear_componente(
                    "cpu",
                    procesador.Manufacturer,
                    procesador.Name,
                    identificador,
                    f"CPU:{identificador}"
                    if identificador
                    else None
                )
            )

        cantidades["cpu"] = len(procesadores)
        tipos_completos.append("cpu")

    except Exception as error:
        errores.append(f"Procesador: {error}")

    # =====================================
    # TARJETA MADRE
    # =====================================
    try:
        tarjetas = sistema.Win32_BaseBoard()

        for indice, tarjeta in enumerate(tarjetas):
            fabricante = limpiar_texto(tarjeta.Manufacturer)
            modelo = limpiar_texto(tarjeta.Product)
            numero_serie = limpiar_texto(tarjeta.SerialNumber)

            if (
                not numero_serie
                or numero_serie.lower() in (
                    "unknown",
                    "none",
                    "00000000",
                    "to be filled by o.e.m.",
                    "default string"
                )
            ):
                identificador = (
                    f"BOARD:{fabricante or 'unknown'}:"
                    f"{modelo or indice}"
                )
            else:
                identificador = f"BOARD:{numero_serie}"

            componentes.append(
                crear_componente(
                    "motherboard",
                    fabricante,
                    modelo,
                    numero_serie,
                    identificador
                )
            )

        cantidades["motherboard"] = len(tarjetas)
        tipos_completos.append("motherboard")

    except Exception as error:
        errores.append(f"Tarjeta madre: {error}")

    # =====================================
    # MEMORIA RAM
    # =====================================
    try:
        memorias = sistema.Win32_PhysicalMemory()

        for ram in memorias:
            numero_serie = limpiar_texto(ram.SerialNumber)
            capacidad_bytes = limpiar_texto(ram.Capacity)
            try:
                capacidad = (
                    int(capacidad_bytes)
                    if capacidad_bytes is not None
                    else None
                )
            except ValueError:
                capacidad = None
                errores.append(
                    "RAM: capacidad no válida; "
                    "se conserva el componente sin capacidad."
                )

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
                    (
                        f"{capacidad // (1024**3)} GB"
                        if capacidad is not None
                        else None
                    ),
                    numero_serie,
                    identificador
                )
            )

        cantidades["ram"] = len(memorias)
        tipos_completos.append("ram")

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
        tipos_completos.append("gpu")

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
        tipos_completos.append("storage")

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
        tipos_completos.append("mouse")

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
        tipos_completos.append("keyboard")

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
        tipos_completos.append("network")

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
            if tipo in tipos_completos:
                tipos_completos.remove(tipo)

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
            if clave[0] in tipos_completos:
                tipos_completos.remove(clave[0])

        identificadores.add(clave)

    completo = (
        len(errores) == 0
        and len(tipos_completos) == len(TIPOS_HARDWARE)
    )

    return {
        "components": componentes,
        "complete": completo,
        "complete_types": tipos_completos,
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
