
import jwt

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException
)
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.agent_auth import autenticar_agente
from app.database import engine
from app.security import (
    SECRET_KEY,
    ALGORITHM,
    EXPIRE_MINUTES,
    crear_token
)


# ==========================================
# CONFIGURACIÓN
# ==========================================

router = APIRouter(
    prefix="/sessions",
    tags=["Sesiones de estudiantes"]
)


# ==========================================
# MODELOS
# ==========================================

class FinalizarSesionRequest(BaseModel):
    session_id: int = Field(gt=0)


class RegistrarActividadRequest(BaseModel):
    session_id: int = Field(gt=0)


class RecuperarSesionRequest(BaseModel):
    session_id: int = Field(gt=0)
    action: str = Field(
        pattern="^(check|close)$"
    )
    reason: str | None = Field(
        default=None,
        pattern="^pending_close$"
    )


# ==========================================
# UTILIDADES
# ==========================================

def fecha_iso(fecha):
    if fecha is None:
        return None

    return fecha.isoformat() + "Z"


# ==========================================
# AUTENTICAR ESTUDIANTE
# ==========================================

def autenticar_estudiante(
    x_student_token: str | None = Header(
        default=None,
        alias="X-Student-Token"
    )
):
    if not x_student_token:
        raise HTTPException(
            status_code=401,
            detail="Falta el token del estudiante"
        )

    try:
        payload = jwt.decode(
            x_student_token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={
                "require": ["sub", "exp", "iat"]
            }
        )

        user_id = int(payload["sub"])

        if user_id <= 0:
            raise ValueError("ID inválido")

    except (
        jwt.PyJWTError,
        ValueError,
        TypeError,
        KeyError
    ):
        raise HTTPException(
            status_code=401,
            detail="Token de estudiante inválido o expirado"
        )

    with engine.connect() as connection:
        usuario = connection.execute(
            text("""
                SELECT
                    id,
                    username,
                    full_name,
                    role,
                    is_active
                FROM dbo.users
                WHERE id = :user_id
            """),
            {"user_id": user_id}
        ).mappings().first()

    if (
        usuario is None
        or not usuario["is_active"]
        or usuario["role"] != "student"
    ):
        raise HTTPException(
            status_code=403,
            detail="El usuario no es un estudiante activo"
        )

    return dict(usuario)


# ==========================================
# INICIAR SESIÓN
# ==========================================

@router.post("/start")
def iniciar_sesion(
    estudiante: dict = Depends(autenticar_estudiante),
    agente: dict = Depends(autenticar_agente)
):
    try:
        with engine.begin() as connection:
            sesion = connection.execute(
                text("""
                    INSERT INTO dbo.sessions (
                        user_id,
                        computer_id,
                        login_at,
                        logout_at,
                        last_activity_at
                    )
                    OUTPUT
                        INSERTED.id,
                        INSERTED.login_at
                    VALUES (
                        :user_id,
                        :computer_id,
                        SYSUTCDATETIME(),
                        NULL,
                        SYSUTCDATETIME()
                    )
                """),
                {
                    "user_id": estudiante["id"],
                    "computer_id": agente["computer_id"]
                }
            ).mappings().first()

    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=(
                "El estudiante ya tiene una sesión "
                "activa o la computadora está ocupada"
            )
        )

    return {
        "message": "Sesión iniciada correctamente",
        "session_id": sesion["id"],
        "student": {
            "id": estudiante["id"],
            "username": estudiante["username"],
            "full_name": estudiante["full_name"]
        },
        "computer": {
            "id": agente["computer_id"],
            "hostname": agente["hostname"]
        },
        "login_at": fecha_iso(sesion["login_at"])
    }


# ==========================================
# CONSULTAR SESIÓN ACTIVA
# ==========================================

@router.get("/current")
def consultar_sesion(
    estudiante: dict = Depends(autenticar_estudiante),
    agente: dict = Depends(autenticar_agente)
):
    with engine.connect() as connection:
        sesion = connection.execute(
            text("""
                SELECT
                    id,
                    user_id,
                    computer_id,
                    login_at
                FROM dbo.sessions
                WHERE user_id = :user_id
                  AND computer_id = :computer_id
                  AND logout_at IS NULL
            """),
            {
                "user_id": estudiante["id"],
                "computer_id": agente["computer_id"]
            }
        ).mappings().first()

    if sesion is None:
        return {
            "active": False,
            "session": None
        }

    return {
        "active": True,
        "session": {
            "id": sesion["id"],
            "user_id": sesion["user_id"],
            "computer_id": sesion["computer_id"],
            "login_at": fecha_iso(sesion["login_at"])
        }
    }


# ==========================================
# FINALIZAR SESIÓN NORMAL
# ==========================================

@router.post("/end")
def finalizar_sesion(
    datos: FinalizarSesionRequest,
    estudiante: dict = Depends(autenticar_estudiante),
    agente: dict = Depends(autenticar_agente)
):
    with engine.begin() as connection:
        sesion = connection.execute(
            text("""
                UPDATE dbo.sessions
                SET logout_at = SYSUTCDATETIME(),
                    close_reason = 'manual'
                OUTPUT
                    INSERTED.id,
                    INSERTED.logout_at,
                    INSERTED.close_reason
                WHERE id = :session_id
                  AND user_id = :user_id
                  AND computer_id = :computer_id
                  AND logout_at IS NULL
            """),
            {
                "session_id": datos.session_id,
                "user_id": estudiante["id"],
                "computer_id": agente["computer_id"]
            }
        ).mappings().first()

    if sesion is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "No existe una sesión activa "
                "con esos datos"
            )
        )

    return {
        "message": "Sesión finalizada correctamente",
        "session_id": sesion["id"],
        "logout_at": fecha_iso(sesion["logout_at"]),
        "close_reason": sesion["close_reason"]
    }


# ==========================================
# REGISTRAR ACTIVIDAD INTERACTIVA
# ==========================================

@router.post("/activity")
def registrar_actividad(
    datos: RegistrarActividadRequest,
    estudiante: dict = Depends(autenticar_estudiante),
    agente: dict = Depends(autenticar_agente)
):
    with engine.begin() as connection:
        sesion = connection.execute(
            text("""
                UPDATE dbo.sessions
                SET last_activity_at = SYSUTCDATETIME()
                OUTPUT
                    INSERTED.id,
                    INSERTED.last_activity_at
                WHERE id = :session_id
                  AND user_id = :user_id
                  AND computer_id = :computer_id
                  AND logout_at IS NULL
            """),
            {
                "session_id": datos.session_id,
                "user_id": estudiante["id"],
                "computer_id": agente["computer_id"]
            }
        ).mappings().first()

    if sesion is None:
        raise HTTPException(
            status_code=409,
            detail="La sesión ya no está activa en esta computadora"
        )

    return {
        "session_id": sesion["id"],
        "last_activity_at": fecha_iso(
            sesion["last_activity_at"]
        ),
        "access_token": crear_token(estudiante["id"]),
        "expires_in": EXPIRE_MINUTES * 60
    }


# ==========================================
# RECUPERAR SESIÓN DEL AGENTE
# ==========================================

@router.post("/recover")
def recuperar_sesion(
    datos: RecuperarSesionRequest,
    agente: dict = Depends(autenticar_agente)
):
    """
    Permite consultar o cerrar una sesión
    de la computadora autenticada.

    No requiere JWT del estudiante.

    IMPORTANTE:
    El agente debe verificar localmente que
    existe una causa válida de recuperación
    antes de solicitar action='close'.
    """

    computer_id = agente["computer_id"]

    with engine.begin() as connection:

        sesion = connection.execute(
            text("""
                SELECT
                    id,
                    user_id,
                    computer_id,
                    login_at,
                    last_activity_at,
                    close_reason,
                    logout_at
                FROM dbo.sessions
                WHERE id = :session_id
                  AND computer_id = :computer_id
            """),
            {
                "session_id": datos.session_id,
                "computer_id": computer_id
            }
        ).mappings().first()

        if sesion is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "La sesión no existe o no pertenece "
                    "a esta computadora"
                )
            )

        if datos.action == "check":
            return {
                "session_id": sesion["id"],
                "user_id": sesion["user_id"],
                "computer_id": sesion["computer_id"],
                "active": sesion["logout_at"] is None,
                "login_at": fecha_iso(sesion["login_at"]),
                "logout_at": fecha_iso(sesion["logout_at"]),
                "last_activity_at": fecha_iso(
                    sesion["last_activity_at"]
                ),
                "close_reason": sesion["close_reason"]
            }

        if datos.reason != "pending_close":
            raise HTTPException(
                status_code=400,
                detail=(
                    "El cierre de recuperación requiere una "
                    "intención local pending_close."
                )
            )

        # Cierre idempotente:
        # si ya estaba cerrada, devolvemos su
        # fecha original sin modificarla.

        if sesion["logout_at"] is not None:
            return {
                "message": "La sesión ya estaba cerrada",
                "session_id": sesion["id"],
                "active": False,
                "logout_at": fecha_iso(sesion["logout_at"]),
                "close_reason": sesion["close_reason"]
            }

        cierre = connection.execute(
            text("""
                UPDATE dbo.sessions
                SET logout_at = SYSUTCDATETIME(),
                    close_reason = 'pending_close'
                OUTPUT
                    INSERTED.id,
                    INSERTED.logout_at,
                    INSERTED.close_reason
                WHERE id = :session_id
                  AND computer_id = :computer_id
                  AND logout_at IS NULL
            """),
            {
                "session_id": datos.session_id,
                "computer_id": computer_id
            }
        ).mappings().first()

        if cierre is None:
            # Otra solicitud pudo cerrar la sesión
            # simultáneamente. Consultamos el estado.
            actual = connection.execute(
                text("""
                    SELECT logout_at, close_reason
                    FROM dbo.sessions
                    WHERE id = :session_id
                      AND computer_id = :computer_id
                """),
                {
                    "session_id": datos.session_id,
                    "computer_id": computer_id
                }
            ).mappings().first()

            if actual is None or actual["logout_at"] is None:
                raise HTTPException(
                    status_code=409,
                    detail="No se pudo confirmar el cierre"
                )

            fecha_cierre = actual["logout_at"]
            motivo_cierre = actual["close_reason"]

        else:
            fecha_cierre = cierre["logout_at"]
            motivo_cierre = cierre["close_reason"]

    return {
        "message": "Sesión recuperada y finalizada",
        "session_id": datos.session_id,
        "active": False,
        "logout_at": fecha_iso(fecha_cierre),
        "close_reason": motivo_cierre
    }
