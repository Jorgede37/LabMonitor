
import os
from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv
from pwdlib import PasswordHash

load_dotenv()

password_hash = PasswordHash.recommended()

SECRET_KEY = os.getenv("JWT_SECRET_KEY")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "30"))

if not SECRET_KEY or len(SECRET_KEY) < 32:
    raise RuntimeError(
        "Configura una JWT_SECRET_KEY segura en el archivo .env"
    )


def generar_hash(contrasena: str) -> str:
    return password_hash.hash(contrasena)


def verificar_contrasena(
    contrasena: str,
    hash_guardado: str
) -> bool:
    return password_hash.verify(
        contrasena,
        hash_guardado
    )


def crear_token(user_id: int) -> str:
    ahora = datetime.now(timezone.utc)

    datos = {
        "sub": str(user_id),
        "iat": ahora,
        "exp": ahora + timedelta(minutes=EXPIRE_MINUTES)
    }

    return jwt.encode(
        datos,
        SECRET_KEY,
        algorithm=ALGORITHM
    )
