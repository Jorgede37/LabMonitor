import logging
import threading

from datetime import datetime, timedelta, timezone
from sqlalchemy import text

from app.database import engine
from app.email_service import enviar_correo


logger = logging.getLogger("LabMonitorTeacherApprovalEmailWorker")
INTERVALO_SEGUNDOS = 5
MAX_ERROR_LENGTH = 1000
_worker_activo = threading.Event()


def worker_aprobaciones_activo():
    return _worker_activo.is_set()


def obtener_notificacion_aprobacion():
    with engine.begin() as connection:
        resultado = connection.execute(
            text("""
                ;WITH siguiente AS (
                    SELECT TOP (1) id, status
                    FROM dbo.teacher_approval_email_notifications
                    WITH (UPDLOCK, READPAST, ROWLOCK)
                    WHERE status = 'pending'
                      AND next_attempt_at <= SYSUTCDATETIME()
                    ORDER BY next_attempt_at, id
                )
                UPDATE siguiente
                SET status = 'processing'
                OUTPUT INSERTED.id;
            """)
        ).first()

        if resultado is None:
            return None

        fila = connection.execute(
            text("""
                SELECT id, recipient, subject, body, attempts, max_attempts
                FROM dbo.teacher_approval_email_notifications
                WHERE id = :id
            """),
            {"id": resultado[0]}
        ).mappings().first()
        return dict(fila) if fila else None


def marcar_aprobacion_enviada(notification_id):
    with engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE dbo.teacher_approval_email_notifications
                SET status = 'sent',
                    attempts = attempts + 1,
                    sent_at = SYSUTCDATETIME(),
                    last_error = NULL,
                    body = N''
                WHERE id = :id AND status = 'processing'
            """),
            {"id": notification_id}
        )


def registrar_fallo_aprobacion(notificacion, error):
    intentos = notificacion["attempts"] + 1
    minutos = min(2 ** (intentos - 1), 60)
    estado = (
        "failed"
        if intentos >= notificacion["max_attempts"]
        else "pending"
    )
    siguiente_intento = (
        datetime.now(timezone.utc) + timedelta(minutes=minutos)
    ).replace(tzinfo=None)

    with engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE dbo.teacher_approval_email_notifications
                SET status = :status,
                    attempts = :attempts,
                    next_attempt_at = :next_attempt_at,
                    last_error = :last_error
                WHERE id = :id AND status = 'processing'
            """),
            {
                "id": notificacion["id"],
                "status": estado,
                "attempts": intentos,
                "next_attempt_at": siguiente_intento,
                "last_error": str(error)[:MAX_ERROR_LENGTH]
            }
        )


def recuperar_aprobaciones_interrumpidas():
    with engine.begin() as connection:
        resultado = connection.execute(
            text("""
                UPDATE dbo.teacher_approval_email_notifications
                SET status = 'pending',
                    next_attempt_at = SYSUTCDATETIME()
                WHERE status = 'processing'
            """))
    logger.info(
        "Avisos de aprobación recuperados: %s",
        resultado.rowcount
    )


def procesar_notificacion_aprobacion(notificacion):
    try:
        enviar_correo(
            destinatario=notificacion["recipient"],
            asunto=notificacion["subject"],
            mensaje=notificacion["body"]
        )
        marcar_aprobacion_enviada(notificacion["id"])
    except Exception as error:
        logger.exception(
            "Falló el aviso de aprobación docente %s",
            notificacion["id"]
        )
        registrar_fallo_aprobacion(notificacion, error)


def iniciar_worker_aprobaciones(detener):
    _worker_activo.set()
    recuperar_pendientes = True
    logger.info("Worker de aprobación docente iniciado")

    try:
        while not detener.is_set():
            try:
                if recuperar_pendientes:
                    recuperar_aprobaciones_interrumpidas()
                    recuperar_pendientes = False

                notificacion = obtener_notificacion_aprobacion()
                if notificacion is None:
                    detener.wait(INTERVALO_SEGUNDOS)
                    continue

                procesar_notificacion_aprobacion(notificacion)
            except Exception:
                logger.exception("Error en worker de aprobación docente")
                detener.wait(INTERVALO_SEGUNDOS)
    finally:
        _worker_activo.clear()
        logger.info("Worker de aprobación docente detenido")
