import logging
import os
import threading

from dotenv import load_dotenv
from sqlalchemy import text

from app.database import engine


# ==========================================
# CONFIGURACION
# ==========================================

load_dotenv()

INTERVALO_REVISION = 5


def obtener_entero_entorno(nombre, predeterminado, minimo=1):
    valor = os.getenv(nombre)

    if valor is None or not valor.strip():
        return predeterminado

    try:
        resultado = int(valor)
    except ValueError as error:
        raise ValueError(
            f"{nombre} debe ser un número entero."
        ) from error

    if resultado < minimo:
        raise ValueError(
            f"{nombre} debe ser mayor o igual a {minimo}."
        )

    return resultado


# Test scope defaults to VM 2; production must explicitly use
# "all" (or leave the setting blank) to cover every computer.
def obtener_filtro_computadora(valor):
    valor = valor.strip()

    if valor.lower() in {"", "all", "*"}:
        return None

    try:
        computer_id = int(valor)
    except ValueError as error:
        raise ValueError(
            "COMPUTADORA_PRUEBA_ID debe ser un ID o 'all'."
        ) from error

    if computer_id <= 0:
        raise ValueError(
            "COMPUTADORA_PRUEBA_ID debe ser mayor que cero."
        )

    return computer_id


TIMEOUT_INACTIVIDAD = obtener_entero_entorno(
    # Test uses 15 seconds; production uses 300 seconds.
    "LABMONITOR_IDLE_TIMEOUT_SECONDS",
    300
)

TIMEOUT_SIN_HEARTBEAT = obtener_entero_entorno(
    "LABMONITOR_HEARTBEAT_TIMEOUT_SECONDS",
    120
)

valor_filtro_computadora = os.getenv(
    "COMPUTADORA_PRUEBA_ID",
    "2"
)
COMPUTADORA_PRUEBA_ID = obtener_filtro_computadora(
    valor_filtro_computadora
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

                SET logout_at = SYSUTCDATETIME(),
                    close_reason = 'inactivity'

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

                  -- Solo se aceptan señales de actividad
                  -- reportadas desde el cliente interactivo.

                  AND s.last_activity_at IS NOT NULL

                  AND s.last_activity_at < DATEADD(
                      SECOND,
                      -:timeout_inactividad,
                      SYSUTCDATETIME()
                  )

                  AND s.login_at <= s.last_activity_at
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

                SET logout_at = SYSUTCDATETIME(),
                    close_reason = 'heartbeat_lost'

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

def procesar_sesiones_expiradas():
    inactivas = cerrar_sesiones_inactivas()

    for sesion in inactivas:
        logger.warning(
            "Sesión %s cerrada por inactividad "
            "(computadora %s, fecha %s)",
            sesion["id"],
            sesion["computer_id"],
            sesion["logout_at"]
        )

    desconectadas = cerrar_sesiones_sin_heartbeat()

    for sesion in desconectadas:
        logger.warning(
            "Sesión %s cerrada por pérdida de comunicación "
            "(computadora %s, fecha %s)",
            sesion["id"],
            sesion["computer_id"],
            sesion["logout_at"]
        )

    if not inactivas and not desconectadas:
        logger.info("Sin sesiones expiradas")


def iniciar_worker(detener=None):
    if detener is None:
        detener = threading.Event()

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

    if COMPUTADORA_PRUEBA_ID is None:
        logger.info("Filtro de computadora: todos los equipos")
    else:
        logger.info(
            "Filtro de computadora de prueba: %s",
            COMPUTADORA_PRUEBA_ID
        )

    while not detener.is_set():

        try:

            procesar_sesiones_expiradas()

        except Exception:

            logger.exception(
                "Error revisando sesiones"
            )

        detener.wait(INTERVALO_REVISION)


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
