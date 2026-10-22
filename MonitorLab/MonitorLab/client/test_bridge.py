
import json

import win32file

PIPE_NAME = r"\\.\pipe\LabMonitorStudent"

def probar_conexion():
    print("Conectando con LabMonitor Agent...")

    pipe = win32file.CreateFile(
        PIPE_NAME,
        win32file.GENERIC_READ | win32file.GENERIC_WRITE,
        0,
        None,
        win32file.OPEN_EXISTING,
        0,
        None
    )

    try:
        solicitud = {
            "action": "current",
            "student_token": ""
        }

        win32file.WriteFile(
            pipe,
            json.dumps(solicitud).encode("utf-8")
        )

        _, respuesta = win32file.ReadFile(pipe, 65536)

        print(
            "Respuesta del agente:",
            json.loads(respuesta.decode("utf-8"))
        )

    finally:
        win32file.CloseHandle(pipe)


if __name__ == "__main__":
    probar_conexion()
