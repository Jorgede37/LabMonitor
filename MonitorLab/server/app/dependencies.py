
import jwt

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import text

from app.database import engine
from app.security import SECRET_KEY, ALGORITHM

bearer_scheme = HTTPBearer(auto_error=False)


def obtener_usuario_actual(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)
):
    error_credenciales = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o expirado",
        headers={"WWW-Authenticate": "Bearer"}
    )

    if credentials is None:
        raise error_credenciales

    try:
        payload = jwt.decode(
            credentials.credentials,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        user_id = int(payload["sub"])

    except (jwt.InvalidTokenError, KeyError, ValueError, TypeError):
        raise error_credenciales

    with engine.connect() as connection:
        resultado = connection.execute(
            text("""
                         SELECT id, username, full_name, role, is_active,
                             teacher_id, teacher_approved
                FROM dbo.users
                WHERE id = :user_id
            """),
            {"user_id": user_id}
        )

        usuario = resultado.mappings().first()

    if usuario is None or not usuario["is_active"]:
        raise error_credenciales

    return dict(usuario)


def solo_administradores(
    usuario: dict = Depends(obtener_usuario_actual)
):
    if usuario["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso exclusivo para administradores"
        )

    return usuario


def solo_docentes_aprobados(
    usuario: dict = Depends(obtener_usuario_actual)
):
    if usuario["role"] != "teacher" or not usuario["teacher_approved"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso exclusivo para docentes autorizados"
        )

    return usuario


def docentes_o_administradores(
    usuario: dict = Depends(obtener_usuario_actual)
):
    if usuario["role"] == "admin":
        return usuario

    if usuario["role"] == "teacher" and usuario["teacher_approved"]:
        return usuario

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Acceso exclusivo para docentes autorizados"
    )
