
import os

from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.agent_auth import autenticar_agente
from app.database import engine
from app.hardware_events import (
    EVENTOS_PERMITIDOS,
    registrar_evento,
    registrar_notificacion
)


load_dotenv()

ZONA_LOCAL = ZoneInfo("America/Mexico_City")

router = APIRouter(
    prefix="/agent",
    tags=["Agentes - Eventos"]
)


class EventoPendiente(BaseModel):
    event_uuid: UUID
    component_type: str
    hardware_identifier: str = Field(
        min_length=1,
        max_length=255
    )
    event_type: str
    previous_value: str | None = None
    new_value: str | None = None
    detected_at: datetime


class LoteEventos(BaseModel):
    events: list[EventoPendiente] = Field(
        min_length=1,
        max_length=100
    )


def obtener_destinatarios():
    configuracion = os.getenv(
        "ADMIN_ALERT_EMAILS",
        "sistemas@aguascalientes.uad.mx"
    )

    return list(dict.fromkeys(
        correo.strip().lower()
        for correo in configuracion.split(",")
        if correo.strip()
    ))


def construir_notificacion(
    computadora,
    evento
):
    nombre = (
        computadora.get("friendly_name")
        or computadora.get("hostname")
        or f"PC-{computadora['id']}"
    )

    laboratorio = (
        computadora.get("lab")
        or "Sin laboratorio asignado"
    )

    fecha_local = (
        evento.detected_at
        .astimezone(ZONA_LOCAL)
        .strftime("%d/%m/%Y %H:%M:%S")
    )

    asunto = (
        f"[LabMonitor] Alerta de hardware - {nombre}"
    )

    mensaje = f"""LABMONITOR - ALERTA DE HARDWARE

Se detectó un evento de hardware.

COMPUTADORA:
{nombre}

LABORATORIO:
{laboratorio}

EVENTO:
{evento.event_type}

TIPO DE COMPONENTE:
{evento.component_type}

IDENTIFICADOR:
{evento.hardware_identifier}

VALOR ANTERIOR:
{evento.previous_value or "No disponible"}

VALOR NUEVO:
{evento.new_value or "No disponible"}

FECHA Y HORA (AGUASCALIENTES):
{fecha_local}

ESTUDIANTE:
Sin sesión identificada

IDENTIFICADOR DEL EVENTO:
{evento.event_uuid}

----------------------------------------

LabMonitor
Departamento de Sistemas
Universidad de Durango
Campus Aguascalientes
"""

    return asunto, mensaje


@router.post("/events/sync")
def sincronizar_eventos(
    lote: LoteEventos,
    agente: dict = Depends(autenticar_agente)
):
    computer_id = agente["computer_id"]

    aceptados = []
    duplicados = []

    uuids = [
        str(evento.event_uuid)
        for evento in lote.events
    ]

    if len(uuids) != len(set(uuids)):
        raise HTTPException(
            status_code=400,
            detail="El lote contiene UUID duplicados"
        )

    for evento in lote.events:
        if evento.event_type not in EVENTOS_PERMITIDOS:
            raise HTTPException(
                status_code=400,
                detail="Tipo de evento no permitido"
            )

        if evento.detected_at.tzinfo is None:
            raise HTTPException(
                status_code=400,
                detail="La fecha debe incluir zona horaria"
            )

    destinatarios = obtener_destinatarios()

    with engine.begin() as connection:

        computadora = connection.execute(
            text("""
                SELECT *
                FROM dbo.computers
                WHERE id = :computer_id
            """),
            {"computer_id": computer_id}
        ).mappings().first()

        if computadora is None:
            raise HTTPException(
                status_code=404,
                detail="Computadora no encontrada"
            )

        computadora = dict(computadora)

        for evento in lote.events:
            uuid_texto = str(evento.event_uuid)

            existente = connection.execute(
                text("""
                    SELECT computer_id
                    FROM dbo.hardware_events
                    WITH (UPDLOCK, HOLDLOCK)
                    WHERE event_uuid =
                        CONVERT(uniqueidentifier, :event_uuid)
                """),
                {"event_uuid": uuid_texto}
            ).first()

            if existente:
                if existente[0] != computer_id:
                    raise HTTPException(
                        status_code=409,
                        detail="UUID asociado a otra computadora"
                    )

                duplicados.append(uuid_texto)
                continue

            componente = connection.execute(
                text("""
                    SELECT id
                    FROM dbo.hardware_components
                    WHERE computer_id = :computer_id
                      AND component_type = :component_type
                      AND hardware_identifier =
                          :hardware_identifier
                """),
                {
                    "computer_id": computer_id,
                    "component_type": evento.component_type,
                    "hardware_identifier":
                        evento.hardware_identifier
                }
            ).first()

            if componente is None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Componente no registrado: "
                        + evento.hardware_identifier
                    )
                )

            event_id = registrar_evento(
                connection=connection,
                computer_id=computer_id,
                component_id=componente[0],
                event_type=evento.event_type,
                previous_value=evento.previous_value,
                new_value=evento.new_value,
                event_uuid=uuid_texto,
                detected_at=evento.detected_at
            )

            asunto, mensaje = construir_notificacion(
                computadora,
                evento
            )

            for destinatario in destinatarios:
                registrar_notificacion(
                    connection=connection,
                    event_id=event_id,
                    destinatario=destinatario,
                    asunto=asunto,
                    mensaje=mensaje
                )

            aceptados.append(uuid_texto)

    return {
        "message": "Eventos procesados correctamente",
        "computer_id": computer_id,
        "accepted": aceptados,
        "duplicates": duplicados,
        "total": len(lote.events)
    }
