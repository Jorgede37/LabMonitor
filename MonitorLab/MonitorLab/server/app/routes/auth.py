
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.database import engine
from app.security import verificar_contrasena, crear_token
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
                    is_active
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

    token = crear_token(usuario["id"])

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 1800,
        "user": {
            "id": usuario["id"],
            "username": usuario["username"],
            "full_name": usuario["full_name"],
            "role": usuario["role"]
        }
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
