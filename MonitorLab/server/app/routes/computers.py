
import hashlib
import os
import secrets

from dotenv import load_dotenv
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.database import engine
from app.dependencies import solo_administradores


load_dotenv()

router = APIRouter(
    prefix="/computers",
    tags=["Computadoras"]
)


# ==========================================
# MODELOS
# ==========================================

class RegistroComputadora(BaseModel):
    hostname: str = Field(min_length=1, max_length=100)
    mac_address: str = Field(min_length=17, max_length=17)
    serial_number: str | None = None
    machine_uuid: str | None = None
    ip_address: str | None = None
    operating_system: str | None = None


# ==========================================
# UTILIDADES DE CREDENCIALES
# ==========================================

def generar_credencial():
    token = secrets.token_urlsafe(48)

    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    return token, token_hash


def hash_inscripcion(clave: str) -> str:
    return hashlib.sha256(clave.encode("utf-8")).hexdigest()


def identidad_hardware(datos: RegistroComputadora) -> str:
    """Use the strongest available stable identity; never use mutable hostname/IP."""
    if datos.machine_uuid and datos.machine_uuid.strip():
        valor = "uuid:" + datos.machine_uuid.strip().casefold()
    elif datos.serial_number and datos.serial_number.strip():
        valor = "serial:" + datos.serial_number.strip().casefold()
    else:
        valor = "mac:" + datos.mac_address.strip().casefold()
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


# ==========================================
# LISTAR COMPUTADORAS
# ==========================================

@router.get("/")
def listar_computadoras(
    administrador: dict = Depends(
        solo_administradores
    )
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


# ==========================================
# REGISTRAR COMPUTADORA NUEVA
# ==========================================

@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED
)
def registrar_computadora(
    datos: RegistroComputadora,
    x_enrollment_key: str | None = Header(default=None)
):
    # Keep the installer-compatible header name; its value is now a
    # one-time dashboard-issued code, never a reusable server secret.
    if not x_enrollment_key or not x_enrollment_key.strip():
        raise HTTPException(status_code=401, detail="Codigo de inscripcion invalido")

    enrollment_hash = hash_inscripcion(x_enrollment_key.strip().upper())
    identity_hash = identidad_hardware(datos)
    agent_token, token_hash = generar_credencial()

    try:
        with engine.begin() as connection:
            enrollment = connection.execute(
                text("""
                    SELECT code_hash, expires_at, consumed_at,
                           bound_identity_hash, bound_computer_id
                    FROM dbo.agent_enrollment_codes WITH (UPDLOCK, HOLDLOCK)
                    WHERE code_hash = :code_hash
                      AND expires_at > SYSDATETIME()
                """),
                {"code_hash": enrollment_hash}
            ).mappings().first()

            if enrollment is None:
                raise HTTPException(status_code=401, detail="Codigo de inscripcion invalido o expirado")

            # Lock all possible hardware-identity matches. Reject conflicting
            # matches rather than risk merging two distinct records.
            matches = connection.execute(
                text("""
                    SELECT id, hostname, mac_address, serial_number,
                           machine_uuid, is_active
                    FROM dbo.computers WITH (UPDLOCK, HOLDLOCK)
                    WHERE (:machine_uuid IS NOT NULL AND machine_uuid = :machine_uuid)
                       OR (:serial_number IS NOT NULL AND serial_number = :serial_number)
                       OR mac_address = :mac_address
                """),
                {
                    "machine_uuid": datos.machine_uuid,
                    "serial_number": datos.serial_number,
                    "mac_address": datos.mac_address
                }
            ).mappings().all()

            if len(matches) > 1:
                raise HTTPException(status_code=409, detail="Identificadores de hardware en conflicto")

            computer = matches[0] if matches else None
            computer_id = computer["id"] if computer else None

            if computer is not None:
                # Never merge records when any reported stable identifier conflicts.
                if (datos.machine_uuid and computer["machine_uuid"]
                        and datos.machine_uuid.strip().casefold() != computer["machine_uuid"].strip().casefold()):
                    raise HTTPException(status_code=409, detail="Identificadores de hardware en conflicto")
                if (datos.serial_number and computer["serial_number"]
                        and datos.serial_number.strip().casefold() != computer["serial_number"].strip().casefold()):
                    raise HTTPException(status_code=409, detail="Identificadores de hardware en conflicto")

            if enrollment["consumed_at"] is not None:
                if computer_id is None or computer_id != enrollment["bound_computer_id"]:
                    raise HTTPException(status_code=409, detail="Codigo de inscripcion ya utilizado")

            if computer is not None:
                if not computer["is_active"]:
                    raise HTTPException(status_code=409, detail="La computadora esta desactivada")
                connection.execute(
                    text("""
                        UPDATE dbo.computers
                        SET hostname = :hostname,
                            mac_address = :mac_address,
                            serial_number = COALESCE(:serial_number, serial_number),
                            machine_uuid = COALESCE(:machine_uuid, machine_uuid),
                            ip_address = :ip_address,
                            operating_system = :operating_system,
                            last_seen = SYSDATETIME()
                        WHERE id = :computer_id
                    """),
                    {**datos.model_dump(), "computer_id": computer_id}
                )
                updated = connection.execute(
                    text("""
                        UPDATE dbo.agent_credentials
                        SET token_hash = :token_hash, is_active = 1
                        WHERE computer_id = :computer_id
                    """),
                    {"computer_id": computer_id, "token_hash": token_hash}
                )
                if updated.rowcount == 0:
                    connection.execute(
                        text("""
                            INSERT INTO dbo.agent_credentials (computer_id, token_hash)
                            VALUES (:computer_id, :token_hash)
                        """),
                        {"computer_id": computer_id, "token_hash": token_hash}
                    )
            else:
                result = connection.execute(
                    text("""
                        INSERT INTO dbo.computers (
                            hostname, mac_address, serial_number, machine_uuid,
                            ip_address, operating_system, last_seen
                        )
                        OUTPUT INSERTED.id
                        VALUES (
                            :hostname, :mac_address, :serial_number, :machine_uuid,
                            :ip_address, :operating_system, SYSDATETIME()
                        )
                    """),
                    datos.model_dump()
                )
                computer_id = result.scalar_one()
                connection.execute(
                    text("""
                        INSERT INTO dbo.agent_credentials (computer_id, token_hash)
                        VALUES (:computer_id, :token_hash)
                    """),
                    {"computer_id": computer_id, "token_hash": token_hash}
                )

            if enrollment["consumed_at"] is None:
                connection.execute(
                    text("""
                        UPDATE dbo.agent_enrollment_codes
                        SET consumed_at = SYSDATETIME(),
                            bound_identity_hash = :identity_hash,
                            bound_computer_id = :computer_id
                        WHERE code_hash = :code_hash
                    """),
                    {
                        "identity_hash": identity_hash,
                        "computer_id": computer_id,
                        "code_hash": enrollment_hash
                    }
                )

        return {
            "message": "Computadora registrada correctamente",
            "computer_id": computer_id,
            "hostname": datos.hostname,
            "agent_token": agent_token
        }

    except HTTPException:
        raise
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Conflicto de identificadores de hardware")
    except SQLAlchemyError:
        raise HTTPException(status_code=500, detail="No fue posible registrar la computadora")


@router.post(
    "/register-admin",
    status_code=status.HTTP_201_CREATED
)
def registrar_computadora_con_administrador(
    datos: RegistroComputadora,
    administrador: dict = Depends(solo_administradores)
):
    """Register or reauthorize this machine using a LabMonitor admin session."""
    del administrador
    agent_token, token_hash = generar_credencial()

    try:
        with engine.begin() as connection:
            matches = connection.execute(
                text("""
                    SELECT id, hostname, mac_address, serial_number,
                           machine_uuid, is_active
                    FROM dbo.computers WITH (UPDLOCK, HOLDLOCK)
                    WHERE (:machine_uuid IS NOT NULL AND machine_uuid = :machine_uuid)
                       OR (:serial_number IS NOT NULL AND serial_number = :serial_number)
                       OR mac_address = :mac_address
                """),
                {
                    "machine_uuid": datos.machine_uuid,
                    "serial_number": datos.serial_number,
                    "mac_address": datos.mac_address
                }
            ).mappings().all()

            if len(matches) > 1:
                raise HTTPException(
                    status_code=409,
                    detail="Identificadores de hardware en conflicto"
                )

            computer = matches[0] if matches else None
            if computer is not None:
                if (
                    datos.machine_uuid
                    and computer["machine_uuid"]
                    and datos.machine_uuid.strip().casefold()
                    != computer["machine_uuid"].strip().casefold()
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Identificadores de hardware en conflicto"
                    )
                if (
                    datos.serial_number
                    and computer["serial_number"]
                    and datos.serial_number.strip().casefold()
                    != computer["serial_number"].strip().casefold()
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Identificadores de hardware en conflicto"
                    )
                if not computer["is_active"]:
                    raise HTTPException(
                        status_code=409,
                        detail="La computadora esta desactivada"
                    )

                computer_id = computer["id"]
                connection.execute(
                    text("""
                        UPDATE dbo.computers
                        SET hostname = :hostname,
                            mac_address = :mac_address,
                            serial_number = COALESCE(:serial_number, serial_number),
                            machine_uuid = COALESCE(:machine_uuid, machine_uuid),
                            ip_address = :ip_address,
                            operating_system = :operating_system,
                            last_seen = SYSDATETIME()
                        WHERE id = :computer_id
                    """),
                    {
                        **datos.model_dump(),
                        "computer_id": computer_id
                    }
                )
                updated = connection.execute(
                    text("""
                        UPDATE dbo.agent_credentials
                        SET token_hash = :token_hash, is_active = 1
                        WHERE computer_id = :computer_id
                    """),
                    {
                        "computer_id": computer_id,
                        "token_hash": token_hash
                    }
                )
                if updated.rowcount == 0:
                    connection.execute(
                        text("""
                            INSERT INTO dbo.agent_credentials (
                                computer_id, token_hash
                            )
                            VALUES (:computer_id, :token_hash)
                        """),
                        {
                            "computer_id": computer_id,
                            "token_hash": token_hash
                        }
                    )
            else:
                computer_id = connection.execute(
                    text("""
                        INSERT INTO dbo.computers (
                            hostname, mac_address, serial_number, machine_uuid,
                            ip_address, operating_system, last_seen
                        )
                        OUTPUT INSERTED.id
                        VALUES (
                            :hostname, :mac_address, :serial_number, :machine_uuid,
                            :ip_address, :operating_system, SYSDATETIME()
                        )
                    """),
                    datos.model_dump()
                ).scalar_one()
                connection.execute(
                    text("""
                        INSERT INTO dbo.agent_credentials (computer_id, token_hash)
                        VALUES (:computer_id, :token_hash)
                    """),
                    {
                        "computer_id": computer_id,
                        "token_hash": token_hash
                    }
                )

        return {
            "message": "Computadora registrada correctamente",
            "computer_id": computer_id,
            "hostname": datos.hostname,
            "agent_token": agent_token
        }

    except HTTPException:
        raise
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Conflicto de identificadores de hardware"
        )
    except SQLAlchemyError:
        raise HTTPException(
            status_code=500,
            detail="No fue posible registrar la computadora"
        )


# ==========================================
# RECUPERAR CREDENCIAL DE AGENTE
# ==========================================

@router.post(
    "/{computer_id}/recover-credential"
)
def recuperar_credencial(
    computer_id: int,
    administrador: dict = Depends(
        solo_administradores
    )
):
    """
    Genera una nueva credencial para una
    computadora existente.

    Requiere autenticacion administrativa.

    La credencial anterior deja de ser valida
    al confirmar la transaccion.

    El token nuevo se devuelve una sola vez.
    """

    if computer_id <= 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "Identificador de computadora "
                "invalido"
            )
        )

    nuevo_token, nuevo_hash = (
        generar_credencial()
    )

    try:
        with engine.begin() as connection:

            # Bloquear la computadora durante
            # la rotacion de credenciales.
            resultado = connection.execute(
                text("""
                    SELECT
                        id,
                        hostname,
                        is_active
                    FROM dbo.computers
                    WITH (UPDLOCK, HOLDLOCK)
                    WHERE id = :computer_id
                """),
                {
                    "computer_id": computer_id
                }
            )

            computadora = (
                resultado.mappings().first()
            )

            if computadora is None:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        "La computadora no existe"
                    )
                )

            if not computadora["is_active"]:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "La computadora esta "
                        "desactivada"
                    )
                )

            # Reemplazar el hash de la credencial
            # existente. Si no existe, crearla.
            actualizado = connection.execute(
                text("""
                    UPDATE dbo.agent_credentials
                    SET token_hash = :token_hash
                    WHERE computer_id = :computer_id
                """),
                {
                    "computer_id": computer_id,
                    "token_hash": nuevo_hash
                }
            )

            if actualizado.rowcount == 0:
                connection.execute(
                    text("""
                        INSERT INTO
                            dbo.agent_credentials (
                                computer_id,
                                token_hash
                            )
                        VALUES (
                            :computer_id,
                            :token_hash
                        )
                    """),
                    {
                        "computer_id": computer_id,
                        "token_hash": nuevo_hash
                    }
                )

        return {
            "message": (
                "Credencial recuperada "
                "correctamente"
            ),
            "computer_id": computer_id,
            "hostname": computadora["hostname"],
            "agent_token": nuevo_token
        }

    except HTTPException:
        raise

    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=(
                "Conflicto al recuperar "
                "la credencial"
            )
        )

    except SQLAlchemyError:
        raise HTTPException(
            status_code=500,
            detail=(
                "No fue posible recuperar "
                "la credencial"
            )
        )
