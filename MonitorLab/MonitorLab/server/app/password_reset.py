
import hashlib
import logging
import os
import secrets

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from dotenv import load_dotenv
from sqlalchemy import text

from app.database import engine
from app.email_service import enviar_recuperacion_password
from app.security import generar_hash


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

logger = logging.getLogger(__name__)

RESET_URL = os.getenv(
    "PASSWORD_RESET_URL",
    "http://localhost:5173/reset-password"
)

RESET_MINUTES = int(
    os.getenv("PASSWORD_RESET_EXPIRE_MINUTES", "15")
)

if RESET_MINUTES <= 0:
    raise RuntimeError(
        "PASSWORD_RESET_EXPIRE_MINUTES debe ser positivo"
    )


def fecha_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def calcular_hash_token(token):
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


def solicitar_recuperacion(identificador):
    """
    Busca únicamente estudiantes activos.

    La respuesta pública siempre será genérica
    para evitar revelar cuentas existentes.
    """

    identificador = identificador.strip()

    if not identificador:
        return

    with engine.connect() as connection:
        usuario = connection.execute(
            text("""
                SELECT TOP 1
                    id,
                    full_name,
                    email
                FROM dbo.users
                WHERE role = 'student'
                  AND is_active = 1
                  AND email IS NOT NULL
                  AND (
                      username = :identificador
                      OR student_id = :identificador
                      OR LOWER(email) = :correo
                  )
            """),
            {
                "identificador": identificador,
                "correo": identificador.lower()
            }
        ).mappings().first()

    if usuario is None:
        return

    token = secrets.token_urlsafe(48)
    token_hash = calcular_hash_token(token)

    ahora = fecha_utc()
    expiracion = ahora + timedelta(
        minutes=RESET_MINUTES
    )

    with engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE dbo.password_reset_tokens
                SET used_at = :ahora
                WHERE user_id = :user_id
                  AND used_at IS NULL
            """),
            {
                "ahora": ahora,
                "user_id": usuario["id"]
            }
        )

        connection.execute(
            text("""
                INSERT INTO dbo.password_reset_tokens (
                    user_id,
                    token_hash,
                    created_at,
                    expires_at
                )
                VALUES (
                    :user_id,
                    :token_hash,
                    :created_at,
                    :expires_at
                )
            """),
            {
                "user_id": usuario["id"],
                "token_hash": token_hash,
                "created_at": ahora,
                "expires_at": expiracion
            }
        )

    separador = "&" if "?" in RESET_URL else "?"

    enlace = (
        RESET_URL
        + separador
        + urlencode({"token": token})
    )

    try:
        enviar_recuperacion_password(
            destinatario=usuario["email"],
            nombre=usuario["full_name"],
            enlace=enlace
        )

    except Exception:
        logger.exception(
            "No fue posible enviar un correo de recuperación"
        )


def restablecer_contrasena(token, nueva_contrasena):
    """
    Verifica que el token exista, no esté usado
    y no haya caducado.

    El token se consume en la misma transacción
    que actualiza la contraseña.
    """

    token_hash = calcular_hash_token(token)
    nuevo_hash = generar_hash(nueva_contrasena)
    ahora = fecha_utc()

    with engine.begin() as connection:

        registro = connection.execute(
            text("""
                SELECT
                    pr.id,
                    pr.user_id
                FROM dbo.password_reset_tokens pr
                    WITH (UPDLOCK, HOLDLOCK)
                INNER JOIN dbo.users u
                    ON u.id = pr.user_id
                WHERE pr.token_hash = :token_hash
                  AND pr.used_at IS NULL
                  AND pr.expires_at > :ahora
                  AND u.role = 'student'
                  AND u.is_active = 1
            """),
            {
                "token_hash": token_hash,
                "ahora": ahora
            }
        ).mappings().first()

        if registro is None:
            return False

        connection.execute(
            text("""
                UPDATE dbo.users
                SET password_hash = :password_hash
                WHERE id = :user_id
            """),
            {
                "password_hash": nuevo_hash,
                "user_id": registro["user_id"]
            }
        )

        connection.execute(
            text("""
                UPDATE dbo.password_reset_tokens
                SET used_at = :ahora
                WHERE user_id = :user_id
                  AND used_at IS NULL
            """),
            {
                "ahora": ahora,
                "user_id": registro["user_id"]
            }
        )

    return True
