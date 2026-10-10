
from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.database import engine
from app.dependencies import solo_administradores

router = APIRouter(
    prefix="/computers",
    tags=["Computadoras"]
)


@router.get("/")
def listar_computadoras(
    administrador: dict = Depends(solo_administradores)
):
    with engine.connect() as connection:
        resultado = connection.execute(
            text("""
                SELECT
                    id,
                    hostname,
                    mac_address,
                    serial_number,
                    machine_uuid,
                    ip_address,
                    lab,
                    operating_system,
                    agent_version,
                    is_active,
                    last_seen
                FROM dbo.computers
                ORDER BY hostname
            """)
        )

        computadoras = [
            dict(fila)
            for fila in resultado.mappings()
        ]

    return {
        "total": len(computadoras),
        "computers": computadoras
    }


import os

from dotenv import load_dotenv
from fastapi import Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

load_dotenv()

ENROLLMENT_KEY = os.getenv("AGENT_ENROLLMENT_KEY")


class RegistroComputadora(BaseModel):
    hostname: str = Field(min_length=1, max_length=100)
    mac_address: str = Field(min_length=17, max_length=17)
    serial_number: str | None = None
    machine_uuid: str | None = None
    ip_address: str | None = None
    operating_system: str | None = None


@router.post("/register", status_code=201)
def registrar_computadora(
    datos: RegistroComputadora,
    x_enrollment_key: str | None = Header(default=None)
):
    import secrets

    if not ENROLLMENT_KEY:
        raise HTTPException(
            status_code=503,
            detail="Registro de agentes no configurado"
        )

    if not x_enrollment_key or not secrets.compare_digest(
        x_enrollment_key, ENROLLMENT_KEY
    ):
        raise HTTPException(
            status_code=401,
            detail="Clave de registro inválida"
        )

    try:
        with engine.begin() as connection:
            resultado = connection.execute(
                text("""
                    INSERT INTO dbo.computers (
                        hostname,
                        mac_address,
                        serial_number,
                        machine_uuid,
                        ip_address,
                        operating_system,
                        last_seen
                    )
                    OUTPUT INSERTED.id
                    VALUES (
                        :hostname,
                        :mac_address,
                        :serial_number,
                        :machine_uuid,
                        :ip_address,
                        :operating_system,
                        SYSDATETIME()
                    )
                """),
                datos.model_dump()
            )

            computer_id = resultado.scalar_one()

        return {
            "message": "Computadora registrada correctamente",
            "computer_id": computer_id,
            "hostname": datos.hostname
        }

    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="La computadora ya está registrada o existe un identificador duplicado"
        )

