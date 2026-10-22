
import os
import requests
import jwt

from pathlib import Path
from dotenv import load_dotenv

from local_database import (
    guardar_sesion_local,
    obtener_sesion_local_activa,
    obtener_cierres_pendientes,
    marcar_cierre_pendiente,
    confirmar_cierre_local,
)


# ==========================================
# CONFIGURACION
# ==========================================

AGENT_DIR = Path(__file__).resolve().parent

load_dotenv(AGENT_DIR / ".env")

SERVER_URL = os.getenv(
    "SERVER_URL",
    "http://127.0.0.1:8000"
).rstrip("/")

AGENT_TOKEN = os.getenv("AGENT_TOKEN")


class SessionManagerError(Exception):
    """Error controlado de gestion de sesiones."""


# ==========================================
# COMUNICACION CON FASTAPI
# ==========================================

def solicitar_servidor(
    metodo,
    endpoint,
    student_token=None,
    datos=None
):
    if not AGENT_TOKEN:
        raise SessionManagerError(
            "El agente no tiene configurado AGENT_TOKEN."
        )

    encabezados = {
        "Authorization": f"Bearer {AGENT_TOKEN}"
    }

    if student_token:
        encabezados["X-Student-Token"] = student_token

    try:
        respuesta = requests.request(
            method=metodo,
            url=f"{SERVER_URL}{endpoint}",
            headers=encabezados,
            json=datos,
            timeout=10
        )

    except requests.RequestException as error:
        raise SessionManagerError(
            "No fue posible conectar con el servidor."
        ) from error

    try:
        resultado = respuesta.json()

    except ValueError as error:
        raise SessionManagerError(
            "El servidor devolvio una respuesta invalida."
        ) from error

    if not respuesta.ok:
        detalle = resultado.get(
            "detail",
            "La operacion fue rechazada."
        )

        raise SessionManagerError(
            f"Error HTTP {respuesta.status_code}: {detalle}"
        )

    return resultado


# ==========================================
# CONSULTAR RECUPERACION
# ==========================================

def consultar_recuperacion(session_id):

    return solicitar_servidor(
        metodo="POST",
        endpoint="/sessions/recover",
        datos={
            "session_id": session_id,
            "action": "check"
        }
    )


# ==========================================
# RECUPERAR CIERRES PENDIENTES
# ==========================================

def recuperar_cierres_pendientes():

    pendientes = obtener_cierres_pendientes()

    resumen = {
        "total": len(pendientes),
        "recuperadas": 0,
        "errores": []
    }

    for sesion in pendientes:

        session_id = sesion["server_session_id"]

        try:
            estado = consultar_recuperacion(session_id)

            if estado["active"]:

                resultado = solicitar_servidor(
                    metodo="POST",
                    endpoint="/sessions/recover",
                    datos={
                        "session_id": session_id,
                        "action": "close"
                    }
                )

                logout_at = resultado["logout_at"]

            else:
                logout_at = estado["logout_at"]

            if not logout_at:
                raise SessionManagerError(
                    "No se recibio fecha de cierre."
                )

            confirmar_cierre_local(
                server_session_id=session_id,
                logout_at=logout_at
            )

            resumen["recuperadas"] += 1

        except (
            SessionManagerError,
            KeyError,
            TypeError,
            ValueError
        ) as error:

            resumen["errores"].append({
                "session_id": session_id,
                "error": str(error)
            })

    return resumen


# ==========================================
# INICIAR SESION
# ==========================================

def iniciar_sesion_estudiante(student_token):

    if not student_token:
        raise SessionManagerError(
            "Falta el token del estudiante."
        )

    recuperar_cierres_pendientes()

    sesion_existente = obtener_sesion_local_activa()

    if sesion_existente:
        raise SessionManagerError(
            "Esta computadora ya tiene una sesion "
            "local activa o pendiente de cierre."
        )

    resultado = solicitar_servidor(
        metodo="POST",
        endpoint="/sessions/start",
        student_token=student_token
    )

    try:
        guardar_sesion_local(
            server_session_id=resultado["session_id"],
            user_id=resultado["student"]["id"],
            computer_id=resultado["computer"]["id"],
            student_id=resultado["student"]["username"],
            login_at=resultado["login_at"]
        )

    except Exception as error:
        raise SessionManagerError(
            "SQL Server registro la sesion, "
            "pero SQLite no pudo guardarla."
        ) from error

    return resultado


# ==========================================
# CONSULTAR SESION DEL ESTUDIANTE
# ==========================================

def consultar_sesion_estudiante(student_token):

    if not student_token:
        raise SessionManagerError(
            "Falta el token del estudiante."
        )

    return solicitar_servidor(
        metodo="GET",
        endpoint="/sessions/current",
        student_token=student_token
    )


# ==========================================
# VALIDAR IDENTIDAD LOCAL
# ==========================================

def validar_identidad_local(student_token, sesion):
    """
    Comprueba la identidad declarada en el JWT.

    IMPORTANTE:
    Esta comprobacion no valida la firma del
    JWT. No debe utilizarse como autorizacion
    definitiva para cerrar sesiones.
    """

    if not student_token:
        raise SessionManagerError(
            "Falta el token del estudiante."
        )

    try:
        payload = jwt.decode(
            student_token,
            options={
                "verify_signature": False,
                "verify_exp": False
            },
            algorithms=["HS256"]
        )

        user_id = int(payload["sub"])

    except (
        jwt.PyJWTError,
        KeyError,
        TypeError,
        ValueError
    ) as error:
        raise SessionManagerError(
            "No fue posible identificar al estudiante."
        ) from error

    if user_id != sesion["user_id"]:
        raise SessionManagerError(
            "El token no corresponde al estudiante "
            "de la sesion local."
        )


# ==========================================
# CERRAR SESION
# ==========================================

def cerrar_sesion_estudiante(student_token):

    sesion = obtener_sesion_local_activa()

    if not sesion:
        raise SessionManagerError(
            "No existe una sesion local activa."
        )

    session_id = sesion["server_session_id"]

    if sesion["status"] == "pending_close":

        resumen = recuperar_cierres_pendientes()

        if resumen["errores"]:
            raise SessionManagerError(
                "El cierre sigue pendiente. "
                "Se requiere conexion con el servidor."
            )

        return {
            "message": "Sesion recuperada y finalizada",
            "session_id": session_id
        }

    validar_identidad_local(
        student_token,
        sesion
    )

    marcar_cierre_pendiente(session_id)

    try:
        resultado = solicitar_servidor(
            metodo="POST",
            endpoint="/sessions/end",
            student_token=student_token,
            datos={
                "session_id": session_id
            }
        )

        confirmar_cierre_local(
            server_session_id=session_id,
            logout_at=resultado["logout_at"]
        )

        return resultado

    except SessionManagerError:

        resumen = recuperar_cierres_pendientes()

        if resumen["errores"]:
            raise SessionManagerError(
                "No fue posible confirmar el cierre. "
                "La sesion quedo pendiente en SQLite."
            )

        return {
            "message": "Sesion recuperada y finalizada",
            "session_id": session_id
        }


# ==========================================
# SINCRONIZAR SESION CON SQL SERVER
# ==========================================

def sincronizar_sesion_servidor(session_id):
    """
    Comprueba si SQL Server sigue considerando
    activa la sesion.

    Si el servidor la cerro, actualiza SQLite.

    Si no hay conexion, conserva el estado local.
    """

    if (
        not isinstance(session_id, int)
        or isinstance(session_id, bool)
        or session_id <= 0
    ):
        raise SessionManagerError(
            "ID de sesion invalido."
        )

    sesion = obtener_sesion_local_activa()

    if sesion is None:
        return {
            "session_id": session_id,
            "status": "not_active"
        }

    if sesion["server_session_id"] != session_id:
        return {
            "session_id": session_id,
            "status": "different_session"
        }

    if sesion["status"] == "pending_close":
        return {
            "session_id": session_id,
            "status": "pending_close"
        }

    try:
        estado = consultar_recuperacion(session_id)

    except SessionManagerError:
        return {
            "session_id": session_id,
            "status": "unknown"
        }

    if estado.get("active") is True:
        return {
            "session_id": session_id,
            "status": "active"
        }

    if estado.get("active") is not False:
        return {
            "session_id": session_id,
            "status": "unknown"
        }

    logout_at = estado.get("logout_at")

    if not logout_at:
        return {
            "session_id": session_id,
            "status": "unknown"
        }

    confirmar_cierre_local(
        server_session_id=session_id,
        logout_at=logout_at
    )

    return {
        "session_id": session_id,
        "status": "not_active"
    }


# ==========================================
# PRUEBA DE CONFIGURACION
# ==========================================

if __name__ == "__main__":

    print("=" * 45)
    print("LabMonitor - Session Manager")
    print("=" * 45)

    print("Servidor:", SERVER_URL)
    print(
        "Token de agente configurado:",
        bool(AGENT_TOKEN)
    )

    sesion = obtener_sesion_local_activa()

    if sesion:
        print(
            "Sesion local:",
            sesion["server_session_id"],
            sesion["status"]
        )
    else:
        print("No existe una sesion local activa.")

    pendientes = obtener_cierres_pendientes()

    print("Cierres pendientes:", len(pendientes))
