import hashlib
import secrets

from sqlalchemy import text

from app.email_service import enviar_codigo_verificacion


def hash_codigo(codigo):
    return hashlib.sha256(codigo.encode("ascii")).hexdigest()


def emitir_codigo_verificacion(
    connection,
    user_id,
    destinatario,
    nombre
):
    codigo = f"{secrets.randbelow(1_000_000):06d}"

    connection.execute(
        text("""
            UPDATE dbo.users
            SET email_verified = 0,
                email_verification_code_hash = :code_hash,
                email_verification_expires_at =
                    DATEADD(MINUTE, 15, SYSUTCDATETIME()),
                email_verification_sent_at = SYSUTCDATETIME(),
                email_verification_attempts = 0
            WHERE id = :user_id
              AND role = 'student'
        """),
        {
            "user_id": user_id,
            "code_hash": hash_codigo(codigo)
        }
    )

    enviar_codigo_verificacion(
        destinatario=destinatario,
        nombre=nombre,
        codigo=codigo
    )
