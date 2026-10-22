
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text


EVENTOS_PERMITIDOS = {
    "SYSTEM_SHUTDOWN",
    "SYSTEM_START",
    "HARDWARE_CHANGED",
    "HARDWARE_REMOVED",
    "HARDWARE_ADDED",
    "DEVICE_DISCONNECTED",
    "DEVICE_CONNECTED"
}


def registrar_evento(
    connection,
    computer_id,
    component_id,
    event_type,
    previous_value=None,
    new_value=None,
    session_id=None,
    user_id=None,
    event_uuid=None,
    detected_at=None
):
    """
    Registra eventos de hardware en SQL Server.

    Compatible con:
    - Eventos generados directamente por FastAPI.
    - Eventos provenientes de SQLite.

    Devuelve el ID del evento registrado.
    """

    if event_type not in EVENTOS_PERMITIDOS:
        raise ValueError(
            f"Tipo de evento no permitido: {event_type}"
        )

    if event_uuid is not None:
        event_uuid = str(UUID(str(event_uuid)))

    if detected_at is None:
        fecha = datetime.now(timezone.utc)
    else:
        if isinstance(detected_at, str):
            fecha = datetime.fromisoformat(
                detected_at.replace("Z", "+00:00")
            )
        else:
            fecha = detected_at

        if fecha.tzinfo is None:
            raise ValueError(
                "detected_at debe incluir zona horaria"
            )

        fecha = fecha.astimezone(timezone.utc)

    fecha_sql = fecha.replace(tzinfo=None)

    resultado = connection.execute(
        text("""
            INSERT INTO dbo.hardware_events (
                computer_id,
                component_id,
                event_type,
                previous_value,
                new_value,
                detected_at,
                session_id,
                user_id,
                event_uuid
            )
            OUTPUT INSERTED.id
            VALUES (
                :computer_id,
                :component_id,
                :event_type,
                :previous_value,
                :new_value,
                :detected_at,
                :session_id,
                :user_id,
                :event_uuid
            )
        """),
        {
            "computer_id": computer_id,
            "component_id": component_id,
            "event_type": event_type,
            "previous_value": previous_value,
            "new_value": new_value,
            "detected_at": fecha_sql,
            "session_id": session_id,
            "user_id": user_id,
            "event_uuid": event_uuid
        }
    )

    return resultado.scalar_one()


def registrar_notificacion(
    connection,
    event_id,
    destinatario,
    asunto,
    mensaje
):
    """
    Registra una notificación pendiente.

    Debe ejecutarse usando la misma conexión
    y transacción que el evento de hardware.
    """

    connection.execute(
        text("""
            IF NOT EXISTS (
                SELECT 1
                FROM dbo.email_notifications WITH (
                    UPDLOCK,
                    HOLDLOCK
                )
                WHERE event_id = :event_id
                  AND recipient = :recipient
            )
            BEGIN
                INSERT INTO dbo.email_notifications (
                    event_id,
                    recipient,
                    subject,
                    body,
                    status
                )
                VALUES (
                    :event_id,
                    :recipient,
                    :subject,
                    :body,
                    'pending'
                )
            END
        """),
        {
            "event_id": event_id,
            "recipient": destinatario,
            "subject": asunto,
            "body": mensaje
        }
    )
