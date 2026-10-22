
import hashlib
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import text

from app.database import engine

agent_bearer = HTTPBearer(auto_error=False)


def autenticar_agente(
    credentials: HTTPAuthorizationCredentials | None = Depends(agent_bearer)
):
    error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credencial de agente inválida",
        headers={"WWW-Authenticate": "Bearer"}
    )

    if credentials is None:
        raise error

    token = credentials.credentials

    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    with engine.connect() as connection:
        resultado = connection.execute(
            text("""
                SELECT
                    ac.computer_id,
                    ac.token_hash,
                    ac.is_active,
                    c.hostname
                FROM dbo.agent_credentials ac
                INNER JOIN dbo.computers c
                    ON c.id = ac.computer_id
                WHERE ac.token_hash = :token_hash
                  AND ac.is_active = 1
                  AND c.is_active = 1
            """),
            {"token_hash": token_hash}
        )

        agente = resultado.mappings().first()

    if agente is None:
        raise error

    if not secrets.compare_digest(
        agente["token_hash"],
        token_hash
    ):
        raise error

    return {
        "computer_id": agente["computer_id"],
        "hostname": agente["hostname"]
    }
