
import json
import os
import threading

import win32con
import win32file
import win32pipe
import win32security
import pywintypes

import config
from assigned_access import cambiar_acceso_asignado
from configuration import consultar_configuracion_equipo
from register import registrar_computadora_con_administrador

from session_manager import (
    iniciar_sesion_estudiante,
    consultar_sesion_estudiante,
    cerrar_sesion_estudiante,
    registrar_actividad_estudiante,
    recuperar_cierres_pendientes,
    consultar_estado_sesion_estudiante,
    SessionManagerError,
)


# ==========================================
# CONFIGURACION
# ==========================================

PIPE_NAME = r"\\.\pipe\LabMonitorStudent"

BUFFER_SIZE = 65536
RECOVERY_INTERVAL = 30

MAX_CLIENTES = 16

session_lock = threading.RLock()

stop_event = threading.Event()

clientes_disponibles = threading.BoundedSemaphore(
    MAX_CLIENTES
)

hilos_clientes = set()
hilos_lock = threading.Lock()


# ==========================================
# SEGURIDAD DEL NAMED PIPE
# ==========================================

def crear_atributos_seguridad():
    """
    Permite conexiones locales de usuarios
    autenticados.

    El token privado del agente nunca se
    entrega mediante el Named Pipe.

    Las operaciones estudiantiles se validan
    mediante el servidor FastAPI.
    """

    system_sid = win32security.CreateWellKnownSid(
        win32security.WinLocalSystemSid,
        None
    )

    admins_sid = win32security.CreateWellKnownSid(
        win32security.WinBuiltinAdministratorsSid,
        None
    )

    usuarios_sid = win32security.CreateWellKnownSid(
        win32security.WinAuthenticatedUserSid,
        None
    )

    dacl = win32security.ACL()

    dacl.AddAccessAllowedAce(
        win32security.ACL_REVISION,
        win32con.GENERIC_ALL,
        system_sid
    )

    dacl.AddAccessAllowedAce(
        win32security.ACL_REVISION,
        win32con.GENERIC_ALL,
        admins_sid
    )

    permisos_cliente = (
    0x0001      # FILE_READ_DATA
    | 0x0002    # FILE_WRITE_DATA
    | 0x0100    # FILE_WRITE_ATTRIBUTES
    | 0x00100000  # SYNCHRONIZE
)

    dacl.AddAccessAllowedAce(
        win32security.ACL_REVISION,
        permisos_cliente,
        usuarios_sid
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

        print(
            "[RECUPERACION] Pendientes:",
            total
        )

        print(
            "[RECUPERACION] Recuperadas:",
            recuperadas
        )

        for error in errores:
            print(
                "[RECUPERACION] Error:",
                error["session_id"],
                error["error"]
            )

    except Exception as error:
        print(
            "[RECUPERACION] Error inesperado:",
            type(error).__name__,
            str(error)
        )


def ciclo_recuperacion():
    print("[RECUPERACION] Hilo iniciado.")

    while not stop_event.is_set():
        ejecutar_recuperacion()

        if stop_event.wait(RECOVERY_INTERVAL):
            break

    print("[RECUPERACION] Hilo detenido.")


# ==========================================
# VALIDACION DE SOLICITUDES
# ==========================================

def obtener_token_estudiante(solicitud):
    token = solicitud.get("student_token")

    if (
        not isinstance(token, str)
        or not token.strip()
    ):
        raise SessionManagerError(
            "Falta el token del estudiante."
        )

    return token


def procesar_solicitud(solicitud):
    if not isinstance(solicitud, dict):
        return {
            "ok": False,
            "error": (
                "La solicitud debe ser "
                "un objeto JSON."
            )
        }

    accion = solicitud.get("action")

    try:
        # ----------------------------------
        # CONFIGURACION DE LA COMPUTADORA
        # ----------------------------------

        if accion == "configuration":
            with session_lock:
                resultado = (
                    consultar_configuracion_equipo()
                )

            return {
                "ok": True,
                "data": resultado
            }

        if accion == "register":
            if config.AGENT_TOKEN:
                raise SessionManagerError(
                    "El agente ya esta registrado. No se repetira el registro."
                )
            admin_token = solicitud.get("admin_token")
            server_url = solicitud.get("server_url")
            if not isinstance(admin_token, str) or not admin_token.strip():
                raise SessionManagerError(
                    "Inicia sesion como administrador de LabMonitor para registrar este equipo."
                )
            if (
                not isinstance(server_url, str)
                or server_url.rstrip("/") != config.SERVER_URL
            ):
                raise SessionManagerError(
                    "La direccion del servidor no coincide con la configuracion de instalacion."
                )

            with session_lock:
                try:
                    resultado = registrar_computadora_con_administrador(
                        config.SERVER_URL,
                        admin_token
                    )
                except (RuntimeError, ValueError) as error:
                    raise SessionManagerError(str(error)) from error

            return {
                "ok": True,
                "data": resultado
            }

        if accion == "assigned-access":
            admin_token = solicitud.get("admin_token")
            operation = solicitud.get("operation")
            windows_account = solicitud.get("windows_account")
            try:
                with session_lock:
                    resultado = cambiar_acceso_asignado(
                        operation,
                        windows_account,
                        admin_token
                    )
            except (RuntimeError, ValueError) as error:
                raise SessionManagerError(str(error)) from error

            return {
                "ok": True,
                "data": resultado
            }

        # ----------------------------------
        # OPERACIONES PERMITIDAS
        # ----------------------------------

        acciones_permitidas = {
            "start",
            "current",
            "end",
            "status",
            "activity"
        }

        if accion not in acciones_permitidas:
            return {
                "ok": False,
                "error": "Operación no permitida."
            }

        student_token = obtener_token_estudiante(
            solicitud
        )

        # ----------------------------------
        # OPERACIONES DEL ESTUDIANTE
        # ----------------------------------

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

                resultado = (
                    consultar_estado_sesion_estudiante(
                        student_token,
                        session_id
                    )
                )

            elif accion == "activity":
                resultado = registrar_actividad_estudiante(
                    student_token,
                    solicitud.get("session_id")
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
            "[ERROR] Solicitud:",
            type(error).__name__,
            str(error)
        )

        return {
            "ok": False,
            "error": "Error interno del agente."
        }


# ==========================================
# COMUNICACION
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
                "JSON inválido."
            )
        }

    except pywintypes.error as error:
        if not stop_event.is_set():
            print(
                "[ERROR] Comunicación local:",
                error.winerror
            )
        return

    except Exception as error:
        if not stop_event.is_set():
            print(
                "[ERROR] Cliente:",
                type(error).__name__,
                str(error)
            )
        return

    if stop_event.is_set():
        return

    try:
        enviar_respuesta(
            pipe,
            respuesta
        )

    except pywintypes.error as error:
        if not stop_event.is_set():
            print(
                "[ERROR] Envío de respuesta:",
                error.winerror
            )


def cerrar_pipe(pipe):
    try:
        win32pipe.DisconnectNamedPipe(
            pipe
        )
    except pywintypes.error:
        pass

    try:
        win32file.CloseHandle(
            pipe
        )
    except pywintypes.error:
        pass


# ==========================================
# CLIENTES INDEPENDIENTES
# ==========================================

def ejecutar_cliente(pipe):
    try:
        atender_cliente(pipe)

    finally:
        cerrar_pipe(pipe)

        clientes_disponibles.release()

        with hilos_lock:
            hilos_clientes.discard(
                threading.current_thread()
            )


def iniciar_hilo_cliente(pipe):
    """
    Cada cliente se atiende independientemente.

    Un cliente que no envíe información no
    bloquea la aceptación de otros clientes.

    Los hilos son daemon para no impedir
    la salida del proceso durante la parada.
    """

    hilo = threading.Thread(
        target=ejecutar_cliente,
        args=(pipe,),
        name="LabMonitorPipeClient",
        daemon=True
    )

    with hilos_lock:
        hilos_clientes.add(hilo)

    try:
        hilo.start()

    except Exception:
        with hilos_lock:
            hilos_clientes.discard(hilo)

        clientes_disponibles.release()
        cerrar_pipe(pipe)
        raise


# ==========================================
# DESPERTAR PIPE AL DETENER
# ==========================================

def despertar_pipe():
    """
    Realiza una conexión local para desbloquear
    ConnectNamedPipe durante la detención.

    No realiza operaciones estudiantiles.
    """

    pipe = None

    try:
        pipe = win32file.CreateFile(
            PIPE_NAME,
            win32con.GENERIC_READ
            | win32con.GENERIC_WRITE,
            0,
            None,
            win32con.OPEN_EXISTING,
            0,
            None
        )

        win32file.WriteFile(
            pipe,
            b'{"action":"__stop__"}'
        )

    except pywintypes.error:
        pass

    finally:
        if pipe is not None:
            try:
                win32file.CloseHandle(
                    pipe
                )
            except pywintypes.error:
                pass


def solicitar_detencion():
    stop_event.set()
    despertar_pipe()


def observar_detencion():
    stop_event.wait()
    despertar_pipe()


# ==========================================
# SERVIDOR NAMED PIPE
# ==========================================

def iniciar_puente(evento_detencion=None):
    """
    Inicia el puente local.

    evento_detencion permite compartir la
    señal de parada con windows_service.py.
    """

    global stop_event

    if os.name != "nt":
        raise RuntimeError(
            "LabMonitor Local Bridge requiere Windows."
        )

    if evento_detencion is not None:
        stop_event = evento_detencion

    if stop_event.is_set():
        return

    print("=" * 45)
    print("LabMonitor - Puente local")
    print("=" * 45)
    print("Pipe:", PIPE_NAME)
    print(
        "Recuperación:",
        RECOVERY_INTERVAL,
        "segundos"
    )

    atributos = crear_atributos_seguridad()

    hilo_recuperacion = threading.Thread(
        target=ciclo_recuperacion,
        name="LabMonitorRecovery",
        daemon=True
    )

    hilo_recuperacion.start()

    hilo_detencion = threading.Thread(
        target=observar_detencion,
        name="LabMonitorPipeStop",
        daemon=True
    )

    hilo_detencion.start()

    print("[PUENTE] Esperando solicitudes...")

    try:
        while not stop_event.is_set():
            pipe = None
            permiso_adquirido = False

            try:
                # Evitar crear conexiones ilimitadas.
                while not stop_event.is_set():
                    permiso_adquirido = (
                        clientes_disponibles.acquire(
                            timeout=0.5
                        )
                    )

                    if permiso_adquirido:
                        break

                if stop_event.is_set():
                    break

                pipe = win32pipe.CreateNamedPipe(
                    PIPE_NAME,
                    win32pipe.PIPE_ACCESS_DUPLEX,
                    (
                        win32pipe.PIPE_TYPE_MESSAGE
                        | win32pipe.PIPE_READMODE_MESSAGE
                        | win32pipe.PIPE_WAIT
                        | win32pipe.PIPE_REJECT_REMOTE_CLIENTS
                    ),
                    MAX_CLIENTES,
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
                    # ERROR_PIPE_CONNECTED
                    if error.winerror != 535:
                        raise

                if stop_event.is_set():
                    break

                # El hilo se hace responsable
                # del pipe y del semáforo.
                pipe_cliente = pipe
                pipe = None

                permiso_adquirido = False

                iniciar_hilo_cliente(
                    pipe_cliente
                )

            except pywintypes.error as error:
                if not stop_event.is_set():
                    print(
                        "[ERROR] Named Pipe:",
                        error.winerror,
                        error.strerror
                    )

            except Exception as error:
                if not stop_event.is_set():
                    print(
                        "[ERROR] Puente local:",
                        type(error).__name__,
                        str(error)
                    )

            finally:
                if pipe is not None:
                    cerrar_pipe(pipe)

                if permiso_adquirido:
                    clientes_disponibles.release()

    finally:
        stop_event.set()

        hilo_recuperacion.join(timeout=2)

        print("[PUENTE] Detenido.")


# ==========================================
# INICIO INDEPENDIENTE
# ==========================================

if __name__ == "__main__":
    try:
        iniciar_puente()

    except KeyboardInterrupt:
        solicitar_detencion()

        print(
            "[PUENTE] Detenido por el usuario."
        )
