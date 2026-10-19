
import argparse
import ctypes
import getpass
import os
import subprocess
import sys
import tempfile

from pathlib import Path
from urllib.parse import urlsplit

import requests

import config

from config import CONFIG_DIR, CONFIG_FILE

from agent import (
    obtener_hostname,
    obtener_mac,
    obtener_ip,
    obtener_sistema_operativo,
    obtener_uuid,
    obtener_numero_serie,
)


CLIENT_CONFIG_FILE = CONFIG_DIR / "client.env"


# ==========================================
# PERMISOS DE ADMINISTRADOR
# ==========================================

def es_administrador():
    if os.name != "nt":
        return False

    try:
        return bool(
            ctypes.windll.shell32.IsUserAnAdmin()
        )
    except Exception:
        return False


# ==========================================
# EJECUTAR ICACLS
# ==========================================

def ejecutar_icacls(*argumentos):
    resultado = subprocess.run(
        ["icacls", *map(str, argumentos)],
        capture_output=True,
        text=True,
        check=False,
    )

    if resultado.returncode != 0:
        raise RuntimeError(
            "No fue posible configurar los "
            "permisos de seguridad de Windows."
        )


# ==========================================
# VALIDAR DIRECCION DEL SERVIDOR
# ==========================================

def validar_url_servidor(url):
    url = str(url or "").strip().rstrip("/")

    if not url:
        raise ValueError(
            "Debes proporcionar la direccion "
            "del servidor."
        )

    if any(
        caracter.isspace()
        for caracter in url
    ):
        raise ValueError(
            "La direccion del servidor "
            "contiene espacios."
        )

    partes = urlsplit(url)

    if partes.scheme not in ("http", "https"):
        raise ValueError(
            "La direccion debe comenzar con "
            "http:// o https://."
        )

    if (
        not partes.hostname
        or partes.username is not None
        or partes.password is not None
        or partes.path not in ("", "/")
        or partes.query
        or partes.fragment
    ):
        raise ValueError(
            "La direccion del servidor "
            "no tiene un formato valido."
        )

    try:
        puerto = partes.port
    except ValueError as error:
        raise ValueError(
            "El puerto del servidor no es valido."
        ) from error

    if puerto is not None and not (
        1 <= puerto <= 65535
    ):
        raise ValueError(
            "El puerto del servidor no es valido."
        )

    return url


# ==========================================
# PROTEGER ARCHIVO PRIVADO
# ==========================================

def proteger_archivo_privado(ruta):
    ejecutar_icacls(
        ruta,
        "/inheritance:r",
    )

    ejecutar_icacls(
        ruta,
        "/grant:r",
        "*S-1-5-18:F",
        "*S-1-5-32-544:F",
    )

    ejecutar_icacls(
        ruta,
        "/remove:g",
        "*S-1-5-32-545",
        "*S-1-5-11",
        "*S-1-1-0",
    )


# ==========================================
# PROTEGER ARCHIVO PUBLICO
# ==========================================

def proteger_archivo_publico(ruta):
    ejecutar_icacls(
        ruta,
        "/inheritance:r",
    )

    ejecutar_icacls(
        ruta,
        "/grant:r",
        "*S-1-5-18:F",
        "*S-1-5-32-544:F",
        "*S-1-5-11:R",
    )


# ==========================================
# PREPARAR DIRECTORIO
# ==========================================

def preparar_directorio():
    CONFIG_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    # SYSTEM y administradores pueden
    # administrar la carpeta.
    #
    # Los usuarios autenticados solamente
    # pueden recorrerla y leer archivos
    # que tengan permisos de lectura.
    ejecutar_icacls(
        CONFIG_DIR,
        "/inheritance:r",
    )

    ejecutar_icacls(
        CONFIG_DIR,
        "/grant:r",
        "*S-1-5-18:(OI)(CI)F",
        "*S-1-5-32-544:(OI)(CI)F",
        "*S-1-5-11:RX",
    )

    ejecutar_icacls(
        CONFIG_DIR,
        "/remove:g",
        "*S-1-5-32-545",
        "*S-1-1-0",
    )


# ==========================================
# ESCRITURA ATOMICA
# ==========================================

def escribir_archivo(
    destino,
    contenido,
    privado
):
    temporal = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=CONFIG_DIR,
            prefix="labmonitor_",
            suffix=".tmp",
            delete=False,
        ) as archivo:
            temporal = Path(archivo.name)
            archivo.write(contenido)

        if privado:
            proteger_archivo_privado(temporal)
        else:
            proteger_archivo_publico(temporal)

        os.replace(
            temporal,
            destino
        )

    finally:
        if (
            temporal is not None
            and temporal.exists()
        ):
            temporal.unlink()


# ==========================================
# GUARDAR CONFIGURACION
# ==========================================

def guardar_configuracion(
    url_servidor,
    token
):
    preparar_directorio()

    contenido_agente = (
        f"LABMONITOR_SERVER_URL={url_servidor}\n"
        f"SERVER_URL={url_servidor}\n"
        f"AGENT_TOKEN={token}\n"
    )

    contenido_cliente = (
        f"LABMONITOR_SERVER_URL={url_servidor}\n"
    )

    # Primero se prepara la configuracion
    # publica del cliente.
    escribir_archivo(
        CLIENT_CONFIG_FILE,
        contenido_cliente,
        privado=False
    )

    # Finalmente se guarda el token privado.
    escribir_archivo(
        CONFIG_FILE,
        contenido_agente,
        privado=True
    )
    config.actualizar_credenciales(
        url_servidor,
        token
    )


def registrar_computadora_con_administrador(
    url_servidor,
    token_administrador
):
    if not token_administrador:
        raise ValueError(
            "Se requiere una sesion de administrador de LabMonitor."
        )
    if config.AGENT_TOKEN:
        raise RuntimeError(
            "El agente ya tiene credenciales. Usa la recuperacion de credenciales."
        )

    url_servidor = validar_url_servidor(url_servidor)
    try:
        respuesta = requests.post(
            f"{url_servidor}/computers/register-admin",
            json=obtener_datos_computadora(),
            headers={
                "Authorization": f"Bearer {token_administrador}"
            },
            timeout=15,
        )
    except requests.RequestException as error:
        raise RuntimeError(
            "No fue posible conectar con el servidor para registrar el equipo."
        ) from error
    try:
        datos = respuesta.json()
    except ValueError as error:
        raise RuntimeError(
            "El servidor devolvio una respuesta invalida al registrar el equipo."
        ) from error

    if not respuesta.ok:
        detalle = (
            datos.get("detail")
            if isinstance(datos, dict)
            else None
        )
        raise RuntimeError(
            detalle or f"El servidor rechazo el registro (HTTP {respuesta.status_code})."
        )

    computer_id = datos.get("computer_id")
    agent_token = datos.get("agent_token")
    if not isinstance(computer_id, int) or not agent_token:
        raise RuntimeError(
            "El servidor no devolvio las credenciales completas del agente."
        )

    try:
        guardar_configuracion(
            url_servidor,
            agent_token
        )
    except (OSError, RuntimeError) as error:
        raise RuntimeError(
            "El equipo se registró en el servidor, pero el agente no pudo guardar "
            "su credencial local. Reintenta la configuracion administrativa."
        ) from error

    return {
        "computer_id": computer_id,
        "hostname": datos.get("hostname"),
    }


# ==========================================
# DATOS DEL HARDWARE
# ==========================================

def obtener_datos_computadora():
    return {
        "hostname": obtener_hostname(),
        "mac_address": obtener_mac(),
        "serial_number": obtener_numero_serie(),
        "machine_uuid": obtener_uuid(),
        "ip_address": obtener_ip(),
        "operating_system": obtener_sistema_operativo(),
    }


# ==========================================
# REGISTRAR COMPUTADORA
# ==========================================

def registrar_computadora(
    url_servidor=None,
    clave=None
):
    if not es_administrador():
        print(
            "Debes ejecutar el registro "
            "como administrador de Windows."
        )
        return 1

    if CONFIG_FILE.exists():
        print(
            "Esta computadora ya tiene "
            "una configuracion de agente."
        )
        return 1

    print(
        "\n===== REGISTRO LABMONITOR ====="
    )

    if not url_servidor:
        url_servidor = input(
            f"Servidor [{config.SERVER_URL}]: "
        ).strip() or config.SERVER_URL

    try:
        url_servidor = validar_url_servidor(
            url_servidor
        )
    except ValueError as error:
        print(error)
        return 1

    print(
        "Servidor:",
        url_servidor
    )

    if clave is None:
        clave = getpass.getpass(
            "Clave de inscripcion: "
        )

    if not clave:
        print(
            "No se proporciono "
            "la clave de inscripcion."
        )
        return 1

    try:
        computadora = obtener_datos_computadora()

        print(
            "Computadora:",
            computadora["hostname"]
        )

        print(
            "MAC:",
            computadora["mac_address"]
        )

        respuesta = requests.post(
            (
                f"{url_servidor}"
                "/computers/register"
            ),
            json=computadora,
            headers={
                "X-Enrollment-Key": clave
            },
            timeout=15,
        )

        if respuesta.status_code == 409:
            print(
                "Esta computadora ya esta "
                "registrada en el servidor."
            )
            print(
                "Se requiere recuperacion "
                "autorizada de credenciales."
            )
            return 2

        if respuesta.status_code != 201:
            print(
                "Registro rechazado. "
                f"HTTP {respuesta.status_code}"
            )
            return 1

        datos = respuesta.json()

        token = datos.get(
            "agent_token"
        )

        if not token:
            print(
                "El servidor no devolvio "
                "el token del agente."
            )
            return 2

        guardar_configuracion(
            url_servidor,
            token
        )

        print(
            "\nRegistro completado correctamente."
        )

        print(
            "ID:",
            datos.get("computer_id")
        )

        print(
            "Hostname:",
            datos.get("hostname")
        )

        print(
            "Configuracion privada:",
            CONFIG_FILE
        )

        print(
            "Configuracion del cliente:",
            CLIENT_CONFIG_FILE
        )

        return 0

    except requests.RequestException as error:
        print(
            "No fue posible completar "
            "la comunicacion con el servidor."
        )

        print(
            type(error).__name__
        )

        print(
            "Si el servidor recibio el registro, "
            "puede requerirse recuperacion autorizada."
        )

        return 2

    except (
        OSError,
        RuntimeError,
        ValueError,
        KeyError,
        TypeError
    ) as error:
        print(
            "No se pudo completar "
            "la configuracion:"
        )

        print(error)

        print(
            "Si el servidor ya registro "
            "la computadora, no intentes "
            "registrarla nuevamente."
        )

        return 2


# ==========================================
# ARGUMENTOS DE LINEA DE COMANDOS
# ==========================================

def consumir_clave_inscripcion(ruta):
    """Read and immediately remove the installer-provided secret file."""
    archivo_clave = Path(ruta)
    try:
        clave = archivo_clave.read_text(encoding="utf-8-sig").strip()
    finally:
        try:
            archivo_clave.unlink(missing_ok=True)
        except OSError:
            pass
    if not clave:
        raise ValueError("No se proporciono la clave de inscripcion.")
    return clave


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Registro de computadoras LabMonitor"
        )
    )

    parser.add_argument(
        "--server",
        help=(
            "Direccion del servidor FastAPI"
        )
    )

    parser.add_argument(
        "--enrollment-key-file",
        help=(
            "Archivo temporal protegido con la clave de inscripcion "
            "(usado por el instalador)."
        )
    )

    argumentos = parser.parse_args()
    clave = None
    if argumentos.enrollment_key_file:
        try:
            clave = consumir_clave_inscripcion(
                argumentos.enrollment_key_file
            )
        except (OSError, ValueError) as error:
            print("No fue posible leer la clave de inscripcion.")
            print(error)
            return 1

    # La clave no se pasa por la linea de comandos; sin archivo,
    # se solicita de forma oculta como antes.
    return registrar_computadora(
        url_servidor=argumentos.server,
        clave=clave
    )


if __name__ == "__main__":
    sys.exit(main())
