"""Elevated control of the Windows service, separate from the student pipe."""

import ctypes
import os
import sys
import time
from pathlib import Path
from ctypes import wintypes


SERVICE_STOP_TIMEOUT_MS = 60000
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102
ERROR_CANCELLED = 1223
SEE_MASK_NOCLOSEPROCESS = 0x00000040
SW_HIDE = 0


class SHELLEXECUTEINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIcon", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


def agente_executable():
    """Return the installed agent executable (or source-tree location)."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent.parent / "Agent"
    else:
        base = Path(__file__).resolve().parent.parent / "agent"
    executable = base / "LabMonitorAgent.exe"
    if not executable.is_file():
        raise FileNotFoundError(
            f"No se encontro el ejecutable del agente: {executable}"
        )
    return executable


def detener_servicio_elevado():
    """Run the service executable's stop verb through the UAC consent flow."""
    if os.name != "nt":
        raise OSError("El control del servicio solo esta disponible en Windows.")

    executable = agente_executable()
    info = SHELLEXECUTEINFO()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = str(executable)
    info.lpParameters = "stop"
    info.lpDirectory = str(executable.parent)
    info.nShow = SW_HIDE

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFO)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)
    ]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.get_last_error()
        if error == ERROR_CANCELLED:
            raise PermissionError("Se cancelo la solicitud de elevacion de Windows.")
        raise OSError(error, "No fue posible iniciar el control elevado del servicio.")

    try:
        result = kernel32.WaitForSingleObject(
            info.hProcess, SERVICE_STOP_TIMEOUT_MS
        )
        if result == WAIT_TIMEOUT:
            raise TimeoutError("Windows tardo demasiado en detener LabMonitorAgent.")
        if result != WAIT_OBJECT_0:
            raise OSError("No se pudo confirmar la detencion del servicio.")

        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(
            info.hProcess, ctypes.byref(exit_code)
        ):
            raise OSError(ctypes.get_last_error(), "No se pudo leer el resultado del servicio.")
        if exit_code.value != 0:
            raise OSError(
                exit_code.value,
                "El comando de Windows no pudo detener LabMonitorAgent. "
                "Comprueba que el servicio este instalado y en ejecucion."
            )
    finally:
        kernel32.CloseHandle(info.hProcess)

    _esperar_servicio_detenido()


def _esperar_servicio_detenido():
    """Wait until SCM reports STOPPED; sending ControlService is asynchronous."""
    try:
        import win32service
    except ImportError as error:
        raise RuntimeError("Falta el componente de Windows para consultar el servicio.") from error

    manager = win32service.OpenSCManager(
        None, None, win32service.SC_MANAGER_CONNECT
    )
    service = None
    try:
        service = win32service.OpenService(
            manager,
            "LabMonitorAgent",
            win32service.SERVICE_QUERY_STATUS
        )
        deadline = time.monotonic() + SERVICE_STOP_TIMEOUT_MS / 1000
        while time.monotonic() < deadline:
            status = win32service.QueryServiceStatus(service)
            if status[1] == win32service.SERVICE_STOPPED:
                return
            time.sleep(0.25)
        raise TimeoutError("LabMonitorAgent recibio la orden, pero no termino de detenerse.")
    finally:
        if service is not None:
            win32service.CloseServiceHandle(service)
        win32service.CloseServiceHandle(manager)
