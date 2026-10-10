
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from app.dependencies import solo_administradores
from app.database import engine


router = APIRouter(
    prefix="/admin",
    tags=["Administración"]
)


def convertir_fechas(registro):
    """
    SQL Server guarda las fechas en UTC sin
    información de zona horaria.

    Las enviamos como ISO 8601 con sufijo Z.
    """
    resultado = dict(registro)

    campos_fecha = {
        "detected_at",
        "created_at",
        "last_seen",
        "first_seen",
        "updated_at",
        "sent_at"
    }

    for campo in campos_fecha:
        valor = resultado.get(campo)

        if isinstance(valor, datetime):
            if valor.tzinfo is None:
                valor = valor.replace(
                    tzinfo=timezone.utc
                )

            resultado[campo] = (
                valor.astimezone(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
            )

    return resultado


@router.get("/dashboard")
def dashboard(
    administrador: dict = Depends(solo_administradores)
):
    with engine.connect() as connection:

        total_computadoras = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM dbo.computers
                WHERE is_active = 1
            """)
        ).scalar_one()

        total_componentes = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM dbo.hardware_components
                WHERE status = 'active'
            """)
        ).scalar_one()

        total_eventos = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM dbo.hardware_events
            """)
        ).scalar_one()

        total_estudiantes = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM dbo.users
                WHERE role = 'student'
                  AND is_active = 1
            """)
        ).scalar_one()

    return {
        "message": "Bienvenido al dashboard de LabMonitor",
        "administrator": administrador["username"],
        "status": "authorized",
        "statistics": {
            "computers": total_computadoras,
            "active_components": total_componentes,
            "hardware_events": total_eventos,
            "students": total_estudiantes
        }
    }


@router.get("/computers")
def listar_computadoras(
    administrador: dict = Depends(solo_administradores)
):
    with engine.connect() as connection:

        resultado = connection.execute(
            text("""
                SELECT
                    c.id,
                    c.hostname,
                    c.mac_address,
                    c.serial_number,
                    c.machine_uuid,
                    c.ip_address,
                    c.lab,
                    c.operating_system,
                    c.agent_version,
                    c.is_active,
                    c.last_seen,
                    c.created_at,

                    (
                        SELECT COUNT(*)
                        FROM dbo.hardware_components hc
                        WHERE hc.computer_id = c.id
                          AND hc.status = 'active'
                    ) AS active_components,

                    (
                        SELECT COUNT(*)
                        FROM dbo.hardware_events he
                        WHERE he.computer_id = c.id
                    ) AS total_events

                FROM dbo.computers c
                ORDER BY c.hostname
            """)
        )

        computadoras = [
            convertir_fechas(fila)
            for fila in resultado.mappings().all()
        ]

    return {
        "total": len(computadoras),
        "computers": computadoras
    }


@router.get("/computers/{computer_id}")
def detalle_computadora(
    computer_id: int,
    administrador: dict = Depends(solo_administradores)
):
    with engine.connect() as connection:

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

        componentes = connection.execute(
            text("""
                SELECT
                    id,
                    component_type,
                    manufacturer,
                    model,
                    serial_number,
                    hardware_identifier,
                    status,
                    first_seen,
                    last_seen
                FROM dbo.hardware_components
                WHERE computer_id = :computer_id
                ORDER BY component_type, model
            """),
            {"computer_id": computer_id}
        ).mappings().all()

        eventos = connection.execute(
            text("""
                SELECT TOP 50
                    he.id,
                    he.component_id,
                    hc.component_type,
                    hc.model,
                    he.event_type,
                    he.previous_value,
                    he.new_value,
                    he.detected_at,
                    he.event_uuid,
                    he.user_id,
                    he.session_id
                FROM dbo.hardware_events he
                LEFT JOIN dbo.hardware_components hc
                    ON he.component_id = hc.id
                WHERE he.computer_id = :computer_id
                ORDER BY he.detected_at DESC, he.id DESC
            """),
            {"computer_id": computer_id}
        ).mappings().all()

    return {
        "computer": convertir_fechas(computadora),
        "hardware": [
            convertir_fechas(componente)
            for componente in componentes
        ],
        "recent_events": [
            convertir_fechas(evento)
            for evento in eventos
        ]
    }
