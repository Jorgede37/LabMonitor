import os
import re
import subprocess
from pathlib import Path

import requests

import config


IS_WINDOWS = os.name == "nt"
WINDOWS_ACCOUNT_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,20}$")


def _get_installation_paths():
    if config.FROZEN:
        install_directory = config.AGENT_DIR.parent
    else:
        install_directory = Path(__file__).resolve().parents[1]

    script_directory = (
        install_directory / "Tools"
        if config.FROZEN
        else install_directory / "installer"
    )
    return (
        script_directory / "ConfigureAssignedAccess.ps1",
        install_directory / "Student" / "LabMonitorStudent.exe",
    )


def _verify_administrator(server_url, admin_token):
    try:
        response = requests.get(
            f"{server_url.rstrip('/')}/admin/laboratories",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=10,
        )
        response.raise_for_status()
    except requests.HTTPError as error:
        status_code = (
            error.response.status_code
            if error.response is not None
            else None
        )
        if status_code in (401, 403):
            raise RuntimeError(
                "La sesión administrativa expiró o no tiene permisos."
            ) from error
        raise RuntimeError(
            "No fue posible confirmar los permisos administrativos "
            f"(HTTP {status_code or 'desconocido'})."
        ) from error
    except requests.RequestException as error:
        raise RuntimeError(
            "No fue posible validar la sesión administrativa con el servidor."
        ) from error


def _verify_windows_edition():
    if not IS_WINDOWS:
        return

    powershell_path = (
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    try:
        result = subprocess.run(
            [
                str(powershell_path),
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "(Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion').EditionID",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(
            "No fue posible comprobar la edición de Windows para el modo quiosco."
        ) from error

    if result.returncode != 0:
        raise RuntimeError(
            "Windows no permitió comprobar si la edición admite el modo quiosco."
        )

    edition = result.stdout.strip()
    if "Professional" not in edition:
        raise RuntimeError(
            "El modo quiosco de LabMonitor requiere Windows Pro. "
            f"Esta computadora tiene la edición {edition or 'no identificada'}."
        )


def cambiar_acceso_asignado(operation, windows_account, admin_token):
    if not IS_WINDOWS:
        raise RuntimeError(
            "El modo quiosco solo se puede configurar en Windows."
        )

    if operation not in ("Apply", "Remove"):
        raise ValueError("La operación de Acceso asignado no es válida.")

    if (
        not isinstance(windows_account, str)
        or not WINDOWS_ACCOUNT_PATTERN.fullmatch(windows_account)
        or windows_account in (".", "..")
    ):
        raise ValueError(
            "No se pudo identificar una cuenta local de Windows válida "
            "para este equipo."
        )

    if not isinstance(admin_token, str) or not admin_token.strip():
        raise RuntimeError(
            "Inicia sesión como administrador de LabMonitor para cambiar "
            "el modo quiosco."
        )

    _verify_windows_edition()

    server_url = config.SERVER_URL.rstrip("/")
    _verify_administrator(server_url, admin_token)

    script_path, student_executable = _get_installation_paths()
    if not script_path.is_file():
        raise RuntimeError(
            "No se encontró la herramienta de Acceso asignado de LabMonitor."
        )

    command = [
        str(
            Path(os.environ.get("SystemRoot", r"C:\Windows"))
            / "System32"
            / "WindowsPowerShell"
            / "v1.0"
            / "powershell.exe"
        ),
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        "-RunAsSystem",
        "-Operation",
        operation,
        "-StudentAccount",
        windows_account,
    ]

    if operation == "Apply":
        if not student_executable.is_file():
            raise RuntimeError(
                "No se encontró LabMonitor Student. Reinstala la aplicación "
                "antes de activar el modo quiosco."
            )
        command.extend(
            ("-StudentExePath", str(student_executable))
        )

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            "Windows tardó demasiado en cambiar el modo quiosco. "
            "Comprueba el estado desde la cuenta administradora de Windows."
        ) from error
    except OSError as error:
        raise RuntimeError(
            "No fue posible iniciar la herramienta de configuración "
            "de Windows."
        ) from error

    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        if detail:
            detail = detail[-1000:]
            raise RuntimeError(
                f"Windows no pudo cambiar el modo quiosco: {detail}"
            )
        raise RuntimeError(
            "Windows no pudo cambiar el modo quiosco. "
            f"Código de salida: {result.returncode}."
        )

    return {
        "operation": operation,
        "windows_account": windows_account,
        "message": (
            "Acceso asignado de LabMonitor quedó activado para la cuenta "
            "actual. Se aplicará al próximo inicio de sesión de Windows."
            if operation == "Apply"
            else "Se retiró el Acceso asignado de LabMonitor."
        ),
    }
