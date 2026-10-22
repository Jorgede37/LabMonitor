from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import text


ZONA_LOCAL = ZoneInfo("America/Mexico_City")


def obtener_reserva_en_hora(connection, laboratory_id, fecha):
    if laboratory_id is None:
        return None

    if fecha.tzinfo is None:
        raise ValueError("La fecha debe incluir zona horaria.")

    fecha_local = fecha.astimezone(ZONA_LOCAL)
    resultado = connection.execute(
        text("""
            SELECT TOP 1
                r.id AS reservation_id,
                r.teacher_user_id,
                u.full_name AS teacher_name,
                u.teacher_id AS teacher_matricula,
                r.subject,
                r.reservation_date,
                r.start_time,
                r.end_time
            FROM dbo.lab_reservations AS r
            INNER JOIN dbo.users AS u
                ON u.id = r.teacher_user_id
            WHERE r.laboratory_id = :laboratory_id
              AND r.reservation_date = :reservation_date
              AND r.start_time <= :reservation_time
              AND r.end_time > :reservation_time
              AND r.status = 'confirmed'
            ORDER BY r.start_time DESC, r.id DESC
        """),
        {
            "laboratory_id": laboratory_id,
            "reservation_date": fecha_local.date(),
            "reservation_time": fecha_local.time().replace(tzinfo=None),
        }
    ).mappings().first()

    return dict(resultado) if resultado is not None else None


def fecha_local_actual():
    return datetime.now(timezone.utc).astimezone(ZONA_LOCAL)
