
import logging

from datetime import datetime
from datetime import timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.agent_auth import autenticar_agente
from app.database import engine
from app.email_service import obtener_correos_administradores
from app.hardware_events import (
    EVENTOS_PERMITIDOS,
    registrar_evento,
    registrar_notificacion
)


logger = logging.getLogger("LabMonitor-HardwareEvents")

ZONA_LOCAL = ZoneInfo("America/Mexico_City")

NOMBRES_EVENTOS = {
    "SYSTEM_SHUTDOWN": "Sistema apagado",
    "SYSTEM_START": "Sistema iniciado",
    "HARDWARE_CHANGED": "Hardware modificado",
    "HARDWARE_REMOVED": "Hardware retirado",
    "HARDWARE_ADDED": "Hardware agregado",
    "DEVICE_DISCONNECTED": "Dispositivo desconectado",
    "DEVICE_CONNECTED": "Dispositivo conectado"
}

NOMBRES_COMPONENTES = {
    "cpu": "Procesador",
    "motherboard": "Tarjeta madre",
    "ram": "Memoria RAM",
    "gpu": "Tarjeta gráfica",
    "storage": "Almacenamiento",
    "mouse": "Mouse",
    "keyboard": "Teclado",
    "network": "Adaptador de red"
}

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
    return obtener_correos_administradores()


def obtener_sesion_estudiante_en_fecha(
    connection,
    computer_id,
    fecha_evento
):
    fecha_utc = fecha_evento.astimezone(timezone.utc).replace(
        tzinfo=None
    )
    return connection.execute(
        text("""
            SELECT TOP 1
                s.id AS session_id,
                u.id AS user_id,
                u.full_name,
                u.student_id
            FROM dbo.sessions AS s
            INNER JOIN dbo.users AS u
                ON u.id = s.user_id
            WHERE s.computer_id = :computer_id
              AND u.role = 'student'
              AND s.login_at <= :event_at
              AND (
                    s.logout_at IS NULL
                    OR s.logout_at >= :event_at
              )
            ORDER BY s.login_at DESC, s.id DESC
        """),
        {
            "computer_id": computer_id,
            "event_at": fecha_utc
        }
    ).mappings().first()


def construir_notificacion(
    computadora,
    evento,
    estudiante=None
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
{NOMBRES_EVENTOS.get(evento.event_type, evento.event_type)}

TIPO DE COMPONENTE:
{NOMBRES_COMPONENTES.get(
        evento.component_type,
        evento.component_type
    )}

IDENTIFICADOR:
{evento.hardware_identifier}

VALOR ANTERIOR:
{evento.previous_value or "No disponible"}

VALOR NUEVO:
{evento.new_value or "No disponible"}

FECHA Y HORA (AGUASCALIENTES):
{fecha_local}

ESTUDIANTE:
{estudiante["full_name"] if estudiante else "Sin sesión identificada"}

MATRÍCULA:
{estudiante.get("student_id") or "No disponible" if estudiante else "No disponible"}

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
    if not destinatarios:
        logger.error(
            "No se configuraron destinatarios para alertas "
            "de hardware; los eventos no generarán correos."
        )

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
                    logger.error(
                        "Evento de hardware duplicado de otra "
                        "computadora: origen %s, destino %s",
                        existente[0],
                        computer_id
                    )
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
                estados_transicion = {
                    "DEVICE_DISCONNECTED": "removed",
                    "HARDWARE_REMOVED": "removed",
                    "DEVICE_CONNECTED": "active",
                    "HARDWARE_ADDED": "active"
                }
                estado = estados_transicion.get(evento.event_type)

                if estado is None:
                    logger.error(
                        "Evento de hardware sin componente registrado: "
                        "computadora %s, tipo %s, evento %s",
                        computer_id,
                        evento.component_type,
                        evento.event_type
                    )
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Componente no registrado: "
                            + evento.hardware_identifier
                        )
                    )

                componente = connection.execute(
                    text("""
                        INSERT INTO dbo.hardware_components (
                            computer_id,
                            component_type,
                            manufacturer,
                            model,
                            serial_number,
                            hardware_identifier,
                            status,
                            first_seen,
                            last_seen
                        )
                        OUTPUT INSERTED.id
                        VALUES (
                            :computer_id,
                            :component_type,
                            NULL,
                            NULL,
                            NULL,
                            :hardware_identifier,
                            :status,
                            SYSUTCDATETIME(),
                            SYSUTCDATETIME()
                        )
                    """),
                    {
                        "computer_id": computer_id,
                        "component_type": evento.component_type,
                        "hardware_identifier":
                            evento.hardware_identifier,
                        "status": estado
                    }
                ).scalar_one()
                logger.warning(
                    "Componente faltante registrado desde evento "
                    "de transición: computadora %s, tipo %s, "
                    "evento %s, estado %s",
                    computer_id,
                    evento.component_type,
                    evento.event_type,
                    estado
                )
            else:
                componente = componente[0]

            estudiante = obtener_sesion_estudiante_en_fecha(
                connection,
                computer_id,
                evento.detected_at
            )

            event_id = registrar_evento(
                connection=connection,
                computer_id=computer_id,
                component_id=componente,
                event_type=evento.event_type,
                previous_value=evento.previous_value,
                new_value=evento.new_value,
                session_id=(
                    estudiante["session_id"]
                    if estudiante else None
                ),
                user_id=estudiante["user_id"] if estudiante else None,
                event_uuid=uuid_texto,
                detected_at=evento.detected_at
            )

            asunto, mensaje = construir_notificacion(
                computadora,
                evento,
                estudiante
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
