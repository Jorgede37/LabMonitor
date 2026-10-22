
import json
import os
import sys
import threading

import win32api
import win32con
import win32file
import win32pipe
import win32security
import pywintypes

from configuration import consultar_configuracion_equipo

from session_manager import (
    iniciar_sesion_estudiante,
    consultar_sesion_estudiante,
    cerrar_sesion_estudiante,
    recuperar_cierres_pendientes,
    sincronizar_sesion_servidor,
    SessionManagerError,
)


# ==========================================
# CONFIGURACION
# ==========================================

PIPE_NAME = r"\\.\pipe\LabMonitorStudent"
BUFFER_SIZE = 65536
RECOVERY_INTERVAL = 30

session_lock = threading.RLock()
stop_event = threading.Event()


# ==========================================
# SEGURIDAD DEL NAMED PIPE
# ==========================================

def crear_atributos_seguridad():

    proceso = win32api.GetCurrentProcess()

    token = win32security.OpenProcessToken(
        proceso,
        win32security.TOKEN_QUERY
    )

    try:
        usuario_sid = win32security.GetTokenInformation(
            token,
            win32security.TokenUser
        )[0]

    finally:
        token.Close()

    system_sid = win32security.CreateWellKnownSid(
        win32security.WinLocalSystemSid,
        None
    )

    dacl = win32security.ACL()

    permisos = (
        win32con.GENERIC_READ
        | win32con.GENERIC_WRITE
    )

    dacl.AddAccessAllowedAce(
        win32security.ACL_REVISION,
        permisos,
        usuario_sid
    )

    dacl.AddAccessAllowedAce(
        win32security.ACL_REVISION,
        permisos,
        system_sid
    )

    descriptor = win32security.SECURITY_DESCRIPTOR()

    descriptor.SetSecurityDescriptorDacl(
        True,
        dacl,
        False
    )

    atributos = pywintypes.SECURITY_ATTRIBUTES()

    atributos.SECURITY_DESCRIPTOR = descriptor

    return atributos


# ==========================================
# RECUPERACION AUTOMATICA
# ==========================================

def ejecutar_recuperacion():

    try:

        with session_lock:
            resumen = recuperar_cierres_pendientes()

        total = resumen["total"]
        recuperadas = resumen["recuperadas"]
        errores = resumen["errores"]

        if total == 0:
            return

        print()

        print(
            "[RECUPERACION] Sesiones pendientes:",
            total
        )

        print(
            "[RECUPERACION] Recuperadas:",
            recuperadas
        )

        if errores:

            for error in errores:

                print(
                    "[RECUPERACION] Pendiente:",
                    error["session_id"],
                    "-",
                    error["error"]
                )

        else:

            print(
                "[RECUPERACION] "
                "Sincronizacion completada."
            )

        print()

    except Exception as error:

        print(
            "[RECUPERACION] Error inesperado:",
            type(error).__name__,
            str(error)
        )


def ciclo_recuperacion():

    print(
        "[RECUPERACION] Servicio iniciado."
    )

    while not stop_event.is_set():

        ejecutar_recuperacion()

        if stop_event.wait(RECOVERY_INTERVAL):
            break

    print(
        "[RECUPERACION] Servicio detenido."
    )


# ==========================================
# PROCESAR SOLICITUDES
# ==========================================

def procesar_solicitud(solicitud):

    if not isinstance(solicitud, dict):

        return {
            "ok": False,
            "error": "La solicitud debe ser un objeto JSON."
        }

    accion = solicitud.get("action")

    # ======================================
    # CONSULTAR CONFIGURACION DEL EQUIPO
    # ======================================

    if accion == "configuration":

        try:

            with session_lock:

                resultado = (
                    consultar_configuracion_equipo()
                )

            return {
                "ok": True,
                "data": resultado
            }

        except SessionManagerError as error:

            return {
                "ok": False,
                "error": str(error)
            }

        except Exception as error:

            print(
                "[ERROR] Consulta de configuracion:",
                type(error).__name__,
                str(error)
            )

            return {
                "ok": False,
                "error": (
                    "No fue posible consultar "
                    "la configuracion."
                )
            }

    # ======================================
    # OPERACIONES DE ESTUDIANTES
    # ======================================

    student_token = solicitud.get(
        "student_token"
    )

    if not isinstance(student_token, str):

        return {
            "ok": False,
            "error": "Falta el token del estudiante."
        }

    if not student_token.strip():

        return {
            "ok": False,
            "error": (
                "El token del estudiante "
                "esta vacio."
            )
        }

    try:

        with session_lock:

            if accion == "start":

                resultado = iniciar_sesion_estudiante(
                    student_token
                )

            elif accion == "current":

                resultado = consultar_sesion_estudiante(
                    student_token
                )

            elif accion == "end":

                resultado = cerrar_sesion_estudiante(
                    student_token
                )

            elif accion == "status":

                session_id = solicitud.get(
                    "session_id"
                )

                # Consulta SQL Server y, si la
                # sesion termino, sincroniza SQLite.
                resultado = (
                    sincronizar_sesion_servidor(
                        session_id
                    )
                )

            else:

                return {
                    "ok": False,
                    "error": "Operacion no permitida."
                }

        return {
            "ok": True,
            "data": resultado
        }

    except SessionManagerError as error:

        return {
            "ok": False,
            "error": str(error)
        }

    except Exception as error:

        print(
            "[ERROR] Fallo interno:",
            type(error).__name__,
            str(error)
        )

        return {
            "ok": False,
            "error": "Error interno del agente."
        }


# ==========================================
# ENVIAR RESPUESTA
# ==========================================

def enviar_respuesta(pipe, respuesta):

    contenido = json.dumps(
        respuesta,
        ensure_ascii=False
    ).encode("utf-8")

    win32file.WriteFile(
        pipe,
        contenido
    )

    win32file.FlushFileBuffers(
        pipe
    )


# ==========================================
# ATENDER CLIENTE
# ==========================================

def atender_cliente(pipe):

    try:

        _, contenido = win32file.ReadFile(
            pipe,
            BUFFER_SIZE
        )

        solicitud = json.loads(
            contenido.decode("utf-8")
        )

        respuesta = procesar_solicitud(
            solicitud
        )

    except (
        json.JSONDecodeError,
        UnicodeDecodeError
    ):

        respuesta = {
            "ok": False,
            "error": (
                "La solicitud contiene "
                "JSON invalido."
            )
        }

    except pywintypes.error as error:

        print(
            "[ERROR] Comunicacion local:",
            error.winerror
        )

        return

    enviar_respuesta(
        pipe,
        respuesta
    )


# ==========================================
# SERVIDOR NAMED PIPE
# ==========================================

def iniciar_puente():

    print("=" * 45)
    print("LabMonitor - Puente local")
    print("=" * 45)

    print(
        "Pipe:",
        PIPE_NAME
    )

    print(
        "Modo: pruebas locales"
    )

    print(
        "Recuperacion automatica:",
        f"cada {RECOVERY_INTERVAL} segundos"
    )

    print()

    atributos = (
        crear_atributos_seguridad()
    )

    hilo_recuperacion = threading.Thread(
        target=ciclo_recuperacion,
        name="LabMonitorRecovery",
        daemon=True
    )

    hilo_recuperacion.start()

    print(
        "Esperando solicitudes..."
    )

    print()

    while True:

        pipe = None

        try:

            pipe = win32pipe.CreateNamedPipe(
                PIPE_NAME,
                win32pipe.PIPE_ACCESS_DUPLEX,
                (
                    win32pipe.PIPE_TYPE_MESSAGE
                    | win32pipe.PIPE_READMODE_MESSAGE
                    | win32pipe.PIPE_WAIT
                    | win32pipe.PIPE_REJECT_REMOTE_CLIENTS
                ),
                1,
                BUFFER_SIZE,
                BUFFER_SIZE,
                0,
                atributos
            )

            try:

                win32pipe.ConnectNamedPipe(
                    pipe,
                    None
                )

            except pywintypes.error as error:

                if error.winerror != 535:
                    raise

            atender_cliente(
                pipe
            )

        except pywintypes.error as error:

            print(
                "[ERROR] Named Pipe:",
                error.winerror,
                error.strerror
            )

        except Exception as error:

            print(
                "[ERROR] Puente local:",
                type(error).__name__,
                str(error)
            )

        finally:

            if pipe is not None:

                try:

                    win32pipe.DisconnectNamedPipe(
                        pipe
                    )

                except pywintypes.error:
                    pass

                win32file.CloseHandle(
                    pipe
                )


# ==========================================
# INICIO
# ==========================================

if __name__ == "__main__":

    if os.name != "nt":

        sys.exit(
            "LabMonitor Local Bridge "
            "requiere Windows."
        )

    try:

        iniciar_puente()

    except KeyboardInterrupt:

        stop_event.set()

        print()

        print(
            "Puente local detenido."
        )
