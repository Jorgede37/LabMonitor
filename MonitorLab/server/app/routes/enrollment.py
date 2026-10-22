import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database import engine
from app.dependencies import solo_administradores

router = APIRouter(prefix="/computers", tags=["Inscripcion"])
CODE_TTL_SECONDS = 15 * 60


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


@router.post("/enrollment-code", status_code=201)
def crear_codigo_inscripcion(administrador: dict = Depends(solo_administradores)):
    # 12 random characters (~72 bits); plaintext is returned only here.
    code = secrets.token_urlsafe(9).upper()
    code_hash = _hash_code(code)
    try:
        with engine.begin() as connection:
            result = connection.execute(
                text("""
                    INSERT INTO dbo.agent_enrollment_codes
                        (code_hash, created_by, expires_at)
                    OUTPUT INSERTED.expires_at
                    VALUES (
                        :code_hash, :created_by,
                        DATEADD(SECOND, :ttl_seconds, SYSDATETIME())
                    )
                """),
                {
                    "code_hash": code_hash,
                    "created_by": administrador["id"],
                    "ttl_seconds": CODE_TTL_SECONDS
                }
            )
            expires_at = result.scalar_one()
    except SQLAlchemyError:
        raise HTTPException(status_code=500, detail="No fue posible crear el codigo de inscripcion")

    return {
        "enrollment_code": code,
        "expires_at": expires_at.isoformat(),
        "expires_in_seconds": CODE_TTL_SECONDS
    }
