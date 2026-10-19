
import hmac

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.database import engine
from app.security import (
    EXPIRE_MINUTES,
    verificar_contrasena,
    crear_token
)
from app.dependencies import obtener_usuario_actual
from app.email_verification import (
    emitir_codigo_verificacion,
    hash_codigo
)
from app.password_reset import (
    solicitar_recuperacion,
    restablecer_contrasena
)


router = APIRouter(
    prefix="/auth",
    tags=["Autenticación"]
)


class LoginRequest(BaseModel):
    username: str
    password: str


class ForgotPasswordRequest(BaseModel):
    identifier: str = Field(
        min_length=1,
        max_length=254
    )


class ResetPasswordRequest(BaseModel):
    token: str = Field(
        min_length=20,
        max_length=256
    )
    new_password: str = Field(
        min_length=8,
        max_length=128
    )


class VerificationCodeRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    code: str = Field(pattern=r"^[0-9]{6}$")


class ResendVerificationRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)


@router.post("/login")
def iniciar_sesion(datos: LoginRequest):

    with engine.connect() as connection:
        resultado = connection.execute(
            text("""
                SELECT
                    id,
                    username,
                    password_hash,
                    role,
                    full_name,
                    is_active,
                    email_verified
                FROM dbo.users
                WHERE username = :username
            """),
            {"username": datos.username}
        )

        usuario = resultado.mappings().first()

    if (
        usuario is None
        or not usuario["is_active"]
        or not verificar_contrasena(
            datos.password,
            usuario["password_hash"]
        )
    ):
        raise HTTPException(
            status_code=401,
            detail="Usuario o contraseña incorrectos"
        )

    if (
        usuario["role"] == "student"
        and not usuario["email_verified"]
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Verifica tu correo con el código de seguridad "
                "que recibiste antes de iniciar sesión."
            )
        )

    token = crear_token(usuario["id"])

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": EXPIRE_MINUTES * 60,
        "user": {
            "id": usuario["id"],
            "username": usuario["username"],
            "full_name": usuario["full_name"],
            "role": usuario["role"]
        }
    }


@router.post("/verify-email")
def verificar_correo(datos: VerificationCodeRequest):
    valido = False
    codigo_hash = hash_codigo(datos.code)

    with engine.begin() as connection:
        usuario = connection.execute(
            text("""
                SELECT
                    id,
                    email_verified,
                    email_verification_code_hash,
                    email_verification_attempts,
                    CASE
                        WHEN email_verification_expires_at >
                             SYSUTCDATETIME()
                        THEN 1 ELSE 0
                    END AS code_is_valid
                FROM dbo.users WITH (UPDLOCK, HOLDLOCK)
                WHERE username = :username
                  AND role = 'student'
                  AND is_active = 1
            """),
            {"username": datos.username}
        ).mappings().first()

        if usuario is not None and usuario["email_verified"]:
            valido = True
        elif (
            usuario is not None
            and usuario["email_verification_attempts"] < 5
        ):
            if (
                usuario["code_is_valid"]
                and usuario["email_verification_code_hash"]
                and hmac.compare_digest(
                    usuario["email_verification_code_hash"],
                    codigo_hash
                )
            ):
                connection.execute(
                    text("""
                        UPDATE dbo.users
                        SET email_verified = 1,
                            email_verification_code_hash = NULL,
                            email_verification_expires_at = NULL,
                            email_verification_attempts = 0
                        WHERE id = :user_id
                    """),
                    {"user_id": usuario["id"]}
                )
                valido = True
            else:
                connection.execute(
                    text("""
                        UPDATE dbo.users
                        SET email_verification_attempts =
                            email_verification_attempts + 1
                        WHERE id = :user_id
                    """),
                    {"user_id": usuario["id"]}
                )

    if not valido:
        raise HTTPException(
            status_code=400,
            detail="El código es incorrecto, venció o ya no es válido."
        )

    return {
        "message": (
            "Correo verificado. Ya puedes iniciar sesión en LabMonitor."
        )
    }


@router.post("/resend-verification")
def reenviar_codigo(datos: ResendVerificationRequest):
    with engine.begin() as connection:
        usuario = connection.execute(
            text("""
                SELECT id, full_name, email, email_verified,
                       email_verification_sent_at
                FROM dbo.users WITH (UPDLOCK, HOLDLOCK)
                WHERE username = :username
                  AND role = 'student'
                  AND is_active = 1
            """),
            {"username": datos.username}
        ).mappings().first()

        if (
            usuario is not None
            and not usuario["email_verified"]
            and usuario["email"]
        ):
            connection.execute(
                text("""
                    UPDATE dbo.users
                    SET email_verification_attempts = 0
                    WHERE id = :user_id
                      AND (
                          email_verification_sent_at IS NULL
                          OR email_verification_sent_at <=
                             DATEADD(SECOND, -60, SYSUTCDATETIME())
                      )
                """),
                {"user_id": usuario["id"]}
            )
            permitida = connection.execute(
                text("""
                    SELECT email_verification_sent_at
                    FROM dbo.users
                    WHERE id = :user_id
                      AND (
                          email_verification_sent_at IS NULL
                          OR email_verification_sent_at <=
                             DATEADD(SECOND, -60, SYSUTCDATETIME())
                      )
                """),
                {"user_id": usuario["id"]}
            ).first()
            if permitida is not None:
                emitir_codigo_verificacion(
                    connection,
                    usuario["id"],
                    usuario["email"],
                    usuario["full_name"]
                )

    return {
        "message": (
            "Si la cuenta está pendiente de verificación, "
            "se enviará un código al correo registrado. "
            "Espera un minuto antes de solicitar otro."
        )
    }


@router.post("/forgot-password")
def solicitar_cambio_contrasena(
    datos: ForgotPasswordRequest
):
    solicitar_recuperacion(datos.identifier)

    return {
        "message": (
            "Si existe una cuenta de estudiante "
            "asociada a esos datos, recibirás "
            "un correo con instrucciones."
        )
    }


@router.post("/reset-password")
def cambiar_contrasena(
    datos: ResetPasswordRequest
):
    correcto = restablecer_contrasena(
        token=datos.token,
        nueva_contrasena=datos.new_password
    )

    if not correcto:
        raise HTTPException(
            status_code=400,
            detail=(
                "El enlace de recuperación "
                "es inválido, ya fue utilizado "
                "o ha caducado."
            )
        )

    return {
        "message": (
            "Contraseña actualizada correctamente. "
            "Ya puedes iniciar sesión."
        )
    }


@router.post("/refresh")
def renovar_sesion(
    usuario: dict = Depends(obtener_usuario_actual)
):
    if usuario["role"] != "admin":
        raise HTTPException(
            status_code=403,
            detail="Acceso exclusivo para administradores"
        )
    return {
        "access_token": crear_token(usuario["id"]),
        "token_type": "bearer",
        "expires_in": EXPIRE_MINUTES * 60
    }
