
import logging
import time

from datetime import datetime, timedelta, timezone
from sqlalchemy import text

from app.database import engine
from app.email_service import enviar_correo


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("LabMonitorEmailWorker")

INTERVALO_SEGUNDOS = 5
MAX_ERROR_LENGTH = 1000


def obtener_notificacion():
    """
    Reclama una notificación de forma atómica.
    Evita que dos workers tomen la misma fila.
    """

    with engine.begin() as connection:

        resultado = connection.execute(
            text("""
                ;WITH siguiente AS (
                    SELECT TOP (1)
                        id,
                        status
                    FROM dbo.email_notifications
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

        notification_id = resultado[0]

        notificacion = connection.execute(
            text("""
                SELECT
                    id,
                    recipient,
                    subject,
                    body,
                    attempts,
                    max_attempts
                FROM dbo.email_notifications
                WHERE id = :id
            """),
            {"id": notification_id}
        ).mappings().first()

        return dict(notificacion)


def marcar_enviado(notification_id):
    with engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE dbo.email_notifications
                SET
                    status = 'sent',
                    attempts = attempts + 1,
                    sent_at = SYSUTCDATETIME(),
                    last_error = NULL
                WHERE id = :id
                  AND status = 'processing'
            """),
            {"id": notification_id}
        )


def registrar_fallo(notificacion, error):
    intentos = notificacion["attempts"] + 1
    max_intentos = notificacion["max_attempts"]

    if intentos >= max_intentos:
        nuevo_estado = "failed"
    else:
        nuevo_estado = "pending"

    # Esperas crecientes: 1, 2, 4, 8... minutos
    minutos = min(2 ** (intentos - 1), 60)

    proximo_intento = (
        datetime.now(timezone.utc)
        + timedelta(minutes=minutos)
    ).replace(tzinfo=None)

    with engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE dbo.email_notifications
                SET
                    status = :status,
                    attempts = :attempts,
                    next_attempt_at = :next_attempt_at,
                    last_error = :last_error
                WHERE id = :id
                  AND status = 'processing'
            """),
            {
                "id": notificacion["id"],
                "status": nuevo_estado,
                "attempts": intentos,
                "next_attempt_at": proximo_intento,
                "last_error": str(error)[:MAX_ERROR_LENGTH]
            }
        )


def recuperar_interrumpidos():
    """
    Al arrancar, devuelve a pending los
    envíos que quedaron en processing.

    Ejecuta un único worker durante las pruebas.
    """

    with engine.begin() as connection:
        resultado = connection.execute(
            text("""
                UPDATE dbo.email_notifications
                SET
                    status = 'pending',
                    next_attempt_at = SYSUTCDATETIME()
                WHERE status = 'processing'
            """)
        )

    logger.info(
        "Notificaciones recuperadas: %s",
        resultado.rowcount
    )


def procesar_notificacion(notificacion):
    notification_id = notificacion["id"]

    try:
        logger.info(
            "Enviando notificación %s a %s",
            notification_id,
            notificacion["recipient"]
        )

        enviar_correo(
            destinatario=notificacion["recipient"],
            asunto=notificacion["subject"],
            mensaje=notificacion["body"]
        )

        marcar_enviado(notification_id)

        logger.info(
            "Notificación %s enviada",
            notification_id
        )

    except Exception as error:
        logger.exception(
            "Falló la notificación %s",
            notification_id
        )

        registrar_fallo(notificacion, error)


def main():
    logger.info("Iniciando LabMonitor Email Worker")

    recuperar_interrumpidos()

    logger.info(
        "Consultando correos cada %s segundos",
        INTERVALO_SEGUNDOS
    )

    while True:
        try:
            notificacion = obtener_notificacion()

            if notificacion is None:
                time.sleep(INTERVALO_SEGUNDOS)
                continue

            procesar_notificacion(notificacion)

        except KeyboardInterrupt:
            logger.info("Worker detenido")
            break

        except Exception:
            logger.exception(
                "Error general del worker"
            )
            time.sleep(INTERVALO_SEGUNDOS)


if __name__ == "__main__":
    main()
