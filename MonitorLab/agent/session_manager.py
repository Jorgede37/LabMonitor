
import requests

import config

from local_database import (
    guardar_sesion_local,
    obtener_sesion_local_activa,
    obtener_sesiones_locales_abiertas,
    obtener_cierres_pendientes,
    marcar_cierre_pendiente,
    confirmar_cierre_local,
    token_autoriza_cierre_offline,
    actualizar_huellas_token_locales,
)


# ==========================================
# ERRORES DEL ADMINISTRADOR DE SESIONES
# ==========================================

class SessionManagerError(Exception):
    pass


class ServerConnectionError(SessionManagerError):
    pass


# ==========================================
# COMUNICACION CON FASTAPI
# ==========================================

def solicitar_servidor(
    metodo,
    endpoint,
    student_token=None,
    datos=None
):
    if not config.AGENT_TOKEN:
        raise SessionManagerError(
            "El agente no tiene configurado AGENT_TOKEN."
        )

    encabezados = {
        "Authorization": f"Bearer {config.AGENT_TOKEN}"
    }

    if student_token:
        encabezados["X-Student-Token"] = student_token

    try:
        respuesta = requests.request(
            method=metodo,
            url=f"{config.SERVER_URL}{endpoint}",
            headers=encabezados,
            json=datos,
            timeout=10
        )

    except requests.RequestException as error:
        raise ServerConnectionError(
            "No fue posible conectar con el servidor."
        ) from error

    try:
        resultado = respuesta.json()

    except ValueError as error:
        raise SessionManagerError(
            "El servidor devolvió una respuesta inválida."
        ) from error

    if not respuesta.ok:
        detalle = (
            resultado.get("detail", "La operación fue rechazada.")
            if isinstance(resultado, dict)
            else "La operación fue rechazada."
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
# RECONCILIAR SESIONES LOCALES
# ==========================================

def recuperar_cierres_pendientes():
    """
    Reconcilia sesiones locales abiertas con el servidor.

    Una sesión activa en ambos lados permanece abierta. Una
    sesión local pendiente puede cerrarse mediante la operación
    idempotente autorizada por el agente; las sesiones que el
    servidor ya cerró se confirman localmente.
    """

    sesiones = obtener_sesiones_locales_abiertas()

    resumen = {
        "total": len(sesiones),
        "recuperadas": 0,
        "errores": []
    }

    for sesion in sesiones:
        session_id = sesion["server_session_id"]

        try:
            estado = consultar_recuperacion(session_id)

            if estado["active"]:
                if sesion["status"] != "pending_close":
                    continue

                resultado = solicitar_servidor(
                    metodo="POST",
                    endpoint="/sessions/recover",
                    datos={
                        "session_id": session_id,
                        "action": "close",
                        "reason": "pending_close"
                    }
                )

                logout_at = resultado["logout_at"]
                close_reason = resultado.get(
                    "close_reason",
                    "pending_close"
                )

            else:
                logout_at = estado["logout_at"]
                close_reason = estado.get("close_reason")

            if not logout_at:
                raise SessionManagerError(
                    "No se recibió fecha de cierre."
                )

            confirmar_cierre_local(
                server_session_id=session_id,
                logout_at=logout_at,
                close_reason=close_reason
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
# INICIAR SESION DEL ESTUDIANTE
# ==========================================

def iniciar_sesion_estudiante(student_token):
    if not isinstance(student_token, str) or not student_token.strip():
        raise SessionManagerError(
            "Falta el token del estudiante."
        )

    # Recuperar cierres anteriores antes de
    # intentar iniciar una nueva sesión.
    resumen = recuperar_cierres_pendientes()

    if resumen["errores"]:
        raise SessionManagerError(
            "No fue posible reconciliar una sesión local con "
            "el servidor. Verifica la conexión e inténtalo "
            "nuevamente."
        )

    sesion_existente = obtener_sesion_local_activa()

    if sesion_existente:
        raise SessionManagerError(
            "Esta computadora ya tiene una sesión "
            "local activa o pendiente de cierre."
        )

    # FastAPI valida el JWT del estudiante y
    # la identidad de esta computadora.
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
            login_at=resultado["login_at"],
            student_token=student_token
        )

    except Exception as error:
        raise SessionManagerError(
            "SQL Server registró la sesión, "
            "pero SQLite no pudo guardarla."
        ) from error

    return resultado


# ==========================================
# REGISTRAR ACTIVIDAD INTERACTIVA
# ==========================================

def registrar_actividad_estudiante(
    student_token,
    session_id
):
    if not isinstance(student_token, str) or not student_token.strip():
        raise SessionManagerError(
            "Falta el token del estudiante."
        )

    if (
        not isinstance(session_id, int)
        or isinstance(session_id, bool)
        or session_id <= 0
    ):
        raise SessionManagerError(
            "ID de sesión inválido."
        )

    sesion = obtener_sesion_local_activa()

    if (
        sesion is None
        or sesion["status"] != "active"
        or sesion["server_session_id"] != session_id
    ):
        raise SessionManagerError(
            "La sesión no está activa en esta computadora."
        )

    resultado = solicitar_servidor(
        metodo="POST",
        endpoint="/sessions/activity",
        student_token=student_token,
        datos={"session_id": session_id}
    )

    token_renovado = resultado.get("access_token")
    if isinstance(token_renovado, str) and token_renovado.strip():
        try:
            actualizar_huellas_token_locales(
                server_session_id=session_id,
                token_presentado=student_token,
                token_renovado=token_renovado
            )
        except (RuntimeError, OSError) as error:
            raise SessionManagerError(
                "La actividad se registró, pero no se pudo guardar "
                "la autorización local de cierre."
            ) from error

    return resultado


# ==========================================
# CONSULTAR SESION DEL ESTUDIANTE
# ==========================================

def consultar_sesion_estudiante(student_token):
    if not isinstance(student_token, str) or not student_token.strip():
        raise SessionManagerError(
            "Falta el token del estudiante."
        )

    return solicitar_servidor(
        metodo="GET",
        endpoint="/sessions/current",
        student_token=student_token
    )


# ==========================================
# VALIDAR IDENTIDAD DEL ESTUDIANTE
# ==========================================

def validar_identidad_local(student_token, sesion):
    """
    Comprueba mediante FastAPI que:

    1. El JWT del estudiante es válido.
    2. El estudiante tiene una sesión activa.
    3. La sesión pertenece a esta computadora.
    4. La sesión coincide con la guardada en SQLite.

    No decodifica JWT sin verificar su firma.
    """

    if not isinstance(student_token, str) or not student_token.strip():
        raise SessionManagerError(
            "Falta el token del estudiante."
        )

    if not isinstance(sesion, dict):
        raise SessionManagerError(
            "La sesión local es inválida."
        )

    resultado = consultar_sesion_estudiante(student_token)

    if not isinstance(resultado, dict):
        raise SessionManagerError(
            "El servidor devolvió una respuesta inválida."
        )

    if resultado.get("active") is not True:
        raise SessionManagerError(
            "El estudiante no tiene una sesión activa autorizada."
        )

    sesion_servidor = resultado.get("session")

    if not isinstance(sesion_servidor, dict):
        raise SessionManagerError(
            "No se recibió la sesión del estudiante."
        )

    if (
        sesion_servidor.get("id") != sesion["server_session_id"]
        or sesion_servidor.get("user_id") != sesion["user_id"]
        or sesion_servidor.get("computer_id") != sesion["computer_id"]
    ):
        raise SessionManagerError(
            "La sesión no corresponde al estudiante autenticado."
        )

    return sesion_servidor


# ==========================================
# CERRAR SESION DEL ESTUDIANTE
# ==========================================

def cerrar_sesion_estudiante(student_token):
    """
    Cierra únicamente la sesión del estudiante
    autorizado por FastAPI.

    Si el cierre ya está pendiente, no permite
    que el cliente active una recuperación directa.
    """

    if not isinstance(student_token, str) or not student_token.strip():
        raise SessionManagerError(
            "Falta el token del estudiante."
        )

    sesion = obtener_sesion_local_activa()

    if not sesion:
        raise SessionManagerError(
            "No existe una sesión local activa."
        )

    if sesion["status"] == "pending_close":
        raise SessionManagerError(
            "Esta sesión ya tiene un cierre pendiente. "
            "El servicio intentará recuperarlo automáticamente."
        )

    session_id = sesion["server_session_id"]

    try:
        # Verify the student while the server is reachable before
        # persisting a close intent.
        validar_identidad_local(student_token, sesion)

        marcar_cierre_pendiente(session_id)

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
            logout_at=resultado["logout_at"],
            close_reason=resultado.get("close_reason", "manual")
        )

        return resultado

    except ServerConnectionError as error:
        if not token_autoriza_cierre_offline(sesion, student_token):
            raise SessionManagerError(
                "No se pudo validar el cierre sin conexión. "
                "Conéctate al servidor e inténtalo de nuevo."
            ) from error

        marcar_cierre_pendiente(session_id)
        return {
            "session_id": session_id,
            "status": "pending_close"
        }

    except SessionManagerError as error:
        raise SessionManagerError(
            "No fue posible confirmar el cierre. "
            "La sesión quedó pendiente y el servicio "
            "intentará recuperarla automáticamente."
        ) from error


# ==========================================
# SINCRONIZAR SESION CON SQL SERVER
# ==========================================

def sincronizar_sesion_servidor(session_id):
    """
    Consulta si SQL Server sigue considerando
    activa la sesión local.

    Si el servidor la cerró, actualiza SQLite.

    Si no hay conexión, conserva el estado local.

    Esta función debe utilizarse internamente
    o después de autorizar al estudiante.
    """

    if (
        not isinstance(session_id, int)
        or isinstance(session_id, bool)
        or session_id <= 0
    ):
        raise SessionManagerError(
            "ID de sesión inválido."
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
# CONSULTAR ESTADO AUTORIZADO
# ==========================================

def consultar_estado_sesion_estudiante(
    student_token,
    session_id
):
    """
    Permite consultar el estado de una sesión
    desde el cliente estudiantil.

    Comprueba la identidad mediante FastAPI
    antes de acceder al estado local.
    """

    if (
        not isinstance(session_id, int)
        or isinstance(session_id, bool)
        or session_id <= 0
    ):
        raise SessionManagerError(
            "ID de sesión inválido."
        )

    if not isinstance(student_token, str) or not student_token.strip():
        raise SessionManagerError(
            "Falta el token del estudiante."
        )

    # FastAPI valida el JWT y devuelve únicamente
    # la sesión activa del estudiante en este equipo.
    resultado = consultar_sesion_estudiante(student_token)

    if not isinstance(resultado, dict):
        raise SessionManagerError(
            "Respuesta inválida del servidor."
        )

    sesion_servidor = resultado.get("session")

    if resultado.get("active") is True:
        if not isinstance(sesion_servidor, dict):
            raise SessionManagerError(
                "La sesión recibida es inválida."
            )

        if sesion_servidor.get("id") != session_id:
            raise SessionManagerError(
                "No tienes autorización para consultar esta sesión."
            )

    else:
        # El servidor indica que el estudiante
        # ya no tiene una sesión activa.
        #
        # No exponemos información sobre sesiones
        # ajenas ni ejecutamos recuperaciones.
        return {
            "session_id": session_id,
            "status": "not_active"
        }

    return sincronizar_sesion_servidor(session_id)


# ==========================================
# PRUEBA DE CONFIGURACION
# ==========================================

if __name__ == "__main__":

    print("=" * 45)
    print("LabMonitor - Session Manager")
    print("=" * 45)

    print("Servidor:", config.SERVER_URL)

    print(
        "Token de agente configurado:",
        bool(config.AGENT_TOKEN)
    )

    sesion = obtener_sesion_local_activa()

    if sesion:
        print(
            "Sesión local:",
            sesion["server_session_id"],
            sesion["status"]
        )
    else:
        print("No existe una sesión local activa.")

    pendientes = obtener_cierres_pendientes()

    print("Cierres pendientes:", len(pendientes))
