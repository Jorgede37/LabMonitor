import logging
import time
import os

from dotenv import load_dotenv
from sqlalchemy import text

from app.database import engine


# ==========================================
# CONFIGURACION
# ==========================================

load_dotenv()

INTERVALO_REVISION = 5

# PRUEBAS: 15 segundos
# PRODUCCION: 300 segundos (5 minutos)
TIMEOUT_INACTIVIDAD = 300

# Perdida de comunicacion con el agente
TIMEOUT_SIN_HEARTBEAT = 120

# Solo computadora de pruebas
load_dotenv()

COMPUTADORA_PRUEBA_ID = int(
    os.getenv("COMPUTADORA_PRUEBA_ID", "2")
)


logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(message)s"
    )
)

logger = logging.getLogger(
    "LabMonitor-SessionWorker"
)


# ==========================================
# CERRAR SESIONES POR INACTIVIDAD
# ==========================================

def cerrar_sesiones_inactivas():

    with engine.begin() as connection:

        resultado = connection.execute(
            text("""
                UPDATE s

                SET logout_at = SYSUTCDATETIME()

                OUTPUT
                    INSERTED.id,
                    INSERTED.computer_id,
                    INSERTED.logout_at

                FROM dbo.sessions AS s

                INNER JOIN dbo.computers AS c
                    ON c.id = s.computer_id

                WHERE s.logout_at IS NULL

                  AND (
                      :computer_id IS NULL
                      OR s.computer_id = :computer_id
                  )

                  -- Solo aplicar inactividad
                  -- cuando la comunicacion
                  -- con el agente es reciente.

                  AND c.last_seen IS NOT NULL

                  AND c.last_seen >= DATEADD(
                      SECOND,
                      -:timeout_heartbeat,
                      SYSUTCDATETIME()
                  )

                  -- Debemos haber recibido
                  -- al menos una medicion de
                  -- actividad para esta sesion.

                  AND s.last_activity_at IS NOT NULL

                  AND s.last_activity_at < DATEADD(
                      SECOND,
                      -:timeout_inactividad,
                      SYSUTCDATETIME()
                  )

                  AND s.login_at < DATEADD(
                      SECOND,
                      -:timeout_inactividad,
                      SYSUTCDATETIME()
                  )
            """),
            {
                "computer_id": COMPUTADORA_PRUEBA_ID,
                "timeout_heartbeat": TIMEOUT_SIN_HEARTBEAT,
                "timeout_inactividad": TIMEOUT_INACTIVIDAD
            }
        ).mappings().all()

    return resultado


# ==========================================
# CERRAR SESIONES SIN HEARTBEAT
# ==========================================

def cerrar_sesiones_sin_heartbeat():

    with engine.begin() as connection:

        resultado = connection.execute(
            text("""
                UPDATE s

                SET logout_at = SYSUTCDATETIME()

                OUTPUT
                    INSERTED.id,
                    INSERTED.computer_id,
                    INSERTED.logout_at

                FROM dbo.sessions AS s

                INNER JOIN dbo.computers AS c
                    ON c.id = s.computer_id

                WHERE s.logout_at IS NULL

                  AND (
                      :computer_id IS NULL
                      OR s.computer_id = :computer_id
                  )

                  AND (
                      c.last_seen IS NULL

                      OR c.last_seen < DATEADD(
                          SECOND,
                          -:timeout,
                          SYSUTCDATETIME()
                      )
                  )

                  AND s.login_at < DATEADD(
                      SECOND,
                      -:timeout,
                      SYSUTCDATETIME()
                  )
            """),
            {
                "computer_id": COMPUTADORA_PRUEBA_ID,
                "timeout": TIMEOUT_SIN_HEARTBEAT
            }
        ).mappings().all()

    return resultado


# ==========================================
# CICLO PRINCIPAL
# ==========================================

def iniciar_worker():

    logger.info(
        "Session Worker iniciado"
    )

    logger.info(
        "Intervalo de revision: %s segundos",
        INTERVALO_REVISION
    )

    logger.info(
        "Timeout de inactividad: %s segundos",
        TIMEOUT_INACTIVIDAD
    )

    logger.info(
        "Timeout sin heartbeat: %s segundos",
        TIMEOUT_SIN_HEARTBEAT
    )

    logger.info(
        "Computadora de prueba: %s",
        COMPUTADORA_PRUEBA_ID
    )

    while True:

        try:

            # ==================================
            # 1. CIERRE POR INACTIVIDAD
            # ==================================

            inactivas = (
                cerrar_sesiones_inactivas()
            )

            for sesion in inactivas:

                logger.warning(
                    "Sesion %s cerrada por inactividad "
                    "(computadora %s, fecha %s)",
                    sesion["id"],
                    sesion["computer_id"],
                    sesion["logout_at"]
                )

            # ==================================
            # 2. CIERRE POR FALTA DE HEARTBEAT
            # ==================================

            desconectadas = (
                cerrar_sesiones_sin_heartbeat()
            )

            for sesion in desconectadas:

                logger.warning(
                    "Sesion %s cerrada por perdida "
                    "de comunicacion "
                    "(computadora %s, fecha %s)",
                    sesion["id"],
                    sesion["computer_id"],
                    sesion["logout_at"]
                )

            if not inactivas and not desconectadas:

                logger.info(
                    "Sin sesiones expiradas"
                )

        except Exception:

            logger.exception(
                "Error revisando sesiones"
            )

        time.sleep(
            INTERVALO_REVISION
        )


# ==========================================
# EJECUCION
# ==========================================

if __name__ == "__main__":

    try:

        iniciar_worker()

    except KeyboardInterrupt:

        logger.info(
            "Session Worker detenido"
        )
