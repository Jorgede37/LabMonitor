

import hashlib
import hmac
import os
import sqlite3
import uuid

from pathlib import Path
from datetime import datetime, timezone


# ==========================================
# ALMACENAMIENTO PERSISTENTE
# ==========================================

AGENT_DIR = Path(__file__).resolve().parent

PROGRAM_DATA = Path(
    os.environ.get(
        "PROGRAMDATA",
        str(AGENT_DIR)
    )
)

LABMONITOR_DIR = PROGRAM_DATA / "LabMonitor"

DATA_DIR = LABMONITOR_DIR / "data"

DB_PATH = DATA_DIR / "labmonitor_local.db"


def huella_token(token):
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


def preparar_directorio_datos():
    """
    Crea la carpeta de datos si no existe.

    Los permisos de acceso deben establecerse
    durante la instalación de LabMonitor.
    """

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


preparar_directorio_datos()



def conectar():
    conexion = sqlite3.connect(DB_PATH, timeout=10)
    conexion.row_factory = sqlite3.Row
    return conexion


def inicializar_base():
    with conectar() as conexion:
        conexion.execute("""
            CREATE TABLE IF NOT EXISTS pending_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_uuid TEXT NOT NULL UNIQUE,
                component_type TEXT NOT NULL,
                hardware_identifier TEXT NOT NULL,
                event_type TEXT NOT NULL,
                previous_value TEXT,
                new_value TEXT,
                detected_at TEXT NOT NULL,
                sent INTEGER NOT NULL DEFAULT 0
                    CHECK (sent IN (0, 1)),
                created_at TEXT NOT NULL
            )
        """)

        conexion.execute("""
            CREATE INDEX IF NOT EXISTS idx_pending_events_sent
            ON pending_events(sent, id)
        """)


def guardar_evento(
    component_type,
    hardware_identifier,
    event_type,
    previous_value=None,
    new_value=None
):
    inicializar_base()

    event_uuid = str(uuid.uuid4())
    fecha = datetime.now(timezone.utc).isoformat()

    with conectar() as conexion:
        conexion.execute("""
            INSERT INTO pending_events (
                event_uuid,
                component_type,
                hardware_identifier,
                event_type,
                previous_value,
                new_value,
                detected_at,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event_uuid,
            component_type,
            hardware_identifier,
            event_type,
            previous_value,
            new_value,
            fecha,
            fecha
        ))

    return event_uuid


def obtener_pendientes():
    inicializar_base()

    with conectar() as conexion:
        registros = conexion.execute("""
            SELECT *
            FROM pending_events
            WHERE sent = 0
            ORDER BY id ASC
        """).fetchall()

    return [dict(registro) for registro in registros]


def marcar_enviado(event_uuid):
    with conectar() as conexion:
        conexion.execute("""
            UPDATE pending_events
            SET sent = 1
            WHERE event_uuid = ?
        """, (event_uuid,))


def inicializar_inventario_local():
    """
    Crea la tabla que almacenará el último
    estado conocido de cada componente.
    """

    with conectar() as conexion:
        conexion.execute("""
            CREATE TABLE IF NOT EXISTS local_hardware (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                component_type TEXT NOT NULL,
                hardware_identifier TEXT NOT NULL,
                manufacturer TEXT,
                model TEXT,
                serial_number TEXT,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'removed')),
                missing_count INTEGER NOT NULL DEFAULT 0,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                UNIQUE(component_type, hardware_identifier)
            )
        """)

        conexion.execute("""
            CREATE TABLE IF NOT EXISTS hardware_baseline_types (
                component_type TEXT PRIMARY KEY,
                established_at TEXT NOT NULL
            )
        """)

        conexion.execute("""
            INSERT OR IGNORE INTO hardware_baseline_types (
                component_type,
                established_at
            )
            SELECT DISTINCT component_type, first_seen
            FROM local_hardware
        """)


def obtener_inventario_local():
    """
    Consulta todos los componentes guardados
    en la base de datos local.
    """

    inicializar_inventario_local()

    with conectar() as conexion:
        registros = conexion.execute("""
            SELECT
                id,
                component_type,
                hardware_identifier,
                manufacturer,
                model,
                serial_number,
                status,
                missing_count,
                first_seen,
                last_seen
            FROM local_hardware
            ORDER BY component_type, id
        """).fetchall()

    return [dict(registro) for registro in registros]



def guardar_inventario_inicial(componentes):
    """
    Guarda el inventario inicial en SQLite.

    No genera eventos porque los componentes
    ya estaban instalados antes del monitoreo.
    """

    inicializar_inventario_local()

    fecha = datetime.now(timezone.utc).isoformat()

    with conectar() as conexion:

        existentes = conexion.execute("""
            SELECT COUNT(*)
            FROM local_hardware
        """).fetchone()[0]

        if existentes > 0:
            print(
                "Ya existe un inventario local. "
                "No se reemplazará."
            )
            return False

        tipos = set()

        for componente in componentes:
            conexion.execute("""
                INSERT INTO local_hardware (
                    component_type,
                    hardware_identifier,
                    manufacturer,
                    model,
                    serial_number,
                    status,
                    missing_count,
                    first_seen,
                    last_seen
                )
                VALUES (?, ?, ?, ?, ?, 'active', 0, ?, ?)
            """, (
                componente["component_type"],
                componente["hardware_identifier"],
                componente.get("manufacturer"),
                componente.get("model"),
                componente.get("serial_number"),
                fecha,
                fecha
            ))
            tipos.add(componente["component_type"])

        for tipo in tipos:
            conexion.execute("""
                INSERT OR IGNORE INTO hardware_baseline_types (
                    component_type,
                    established_at
                )
                VALUES (?, ?)
            """, (tipo, fecha))

    return True




if __name__ == "__main__":
    inicializar_base()

    print("Base de datos local creada correctamente")
    print("Ubicación:", DB_PATH)

    pendientes = obtener_pendientes()
    print("Eventos pendientes:", len(pendientes))


    
# ==========================================
# SESIONES LOCALES DE ESTUDIANTES
# ==========================================

def inicializar_sesiones_locales():
    """
    Crea la tabla para conservar el estado
    de las sesiones de estudiantes.
    """

    with conectar() as conexion:
        conexion.execute("""
            CREATE TABLE IF NOT EXISTS local_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_session_id INTEGER NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                computer_id INTEGER NOT NULL,
                student_id TEXT NOT NULL,
                login_at TEXT NOT NULL,
                logout_at TEXT,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (
                        status IN (
                            'active',
                            'closed',
                            'pending_close'
                        )
                    ),
                close_reason TEXT
            )
        """)

        columnas = {
            fila["name"]
            for fila in conexion.execute(
                "PRAGMA table_info(local_sessions)"
            ).fetchall()
        }

        if "close_reason" not in columnas:
            conexion.execute(
                "ALTER TABLE local_sessions "
                "ADD COLUMN close_reason TEXT"
            )

        if "logout_token_hash" not in columnas:
            conexion.execute(
                "ALTER TABLE local_sessions "
                "ADD COLUMN logout_token_hash TEXT"
            )

        if "previous_logout_token_hash" not in columnas:
            conexion.execute(
                "ALTER TABLE local_sessions "
                "ADD COLUMN previous_logout_token_hash TEXT"
            )

        conexion.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
                ux_local_sessions_active
            ON local_sessions(computer_id)
            WHERE status IN ('active', 'pending_close')
        """)


def guardar_sesion_local(
    server_session_id,
    user_id,
    computer_id,
    student_id,
    login_at,
    student_token
):
    inicializar_sesiones_locales()

    with conectar() as conexion:
        conexion.execute("""
            INSERT INTO local_sessions (
                server_session_id,
                user_id,
                computer_id,
                student_id,
                login_at,
                status,
                logout_token_hash
            )
            VALUES (?, ?, ?, ?, ?, 'active', ?)
        """, (
            server_session_id,
            user_id,
            computer_id,
            student_id,
            login_at,
            huella_token(student_token)
        ))


def obtener_sesion_local_activa():
    inicializar_sesiones_locales()

    with conectar() as conexion:
        registro = conexion.execute("""
            SELECT *
            FROM local_sessions
            WHERE status IN ('active', 'pending_close')
            ORDER BY id DESC
            LIMIT 1
        """).fetchone()

    return dict(registro) if registro else None


def marcar_cierre_pendiente(server_session_id):
    inicializar_sesiones_locales()

    with conectar() as conexion:
        resultado = conexion.execute("""
            UPDATE local_sessions
            SET status = 'pending_close',
                logout_token_hash = NULL,
                previous_logout_token_hash = NULL
            WHERE server_session_id = ?
              AND status = 'active'
        """, (server_session_id,))

    if resultado.rowcount != 1:
        raise RuntimeError(
            "No se pudo guardar localmente la intención de cierre."
        )


def token_autoriza_cierre_offline(sesion, student_token):
    huella = huella_token(student_token)

    return any(
        guardada is not None
        and hmac.compare_digest(huella, guardada)
        for guardada in (
            sesion.get("logout_token_hash"),
            sesion.get("previous_logout_token_hash")
        )
    )


def actualizar_huellas_token_locales(
    server_session_id,
    token_presentado,
    token_renovado
):
    inicializar_sesiones_locales()
    huella_presentada = huella_token(token_presentado)
    huella_renovada = huella_token(token_renovado)

    with conectar() as conexion:
        resultado = conexion.execute("""
            UPDATE local_sessions
            SET previous_logout_token_hash = logout_token_hash,
                logout_token_hash = ?
            WHERE server_session_id = ?
              AND status = 'active'
              AND (
                  logout_token_hash = ?
                  OR previous_logout_token_hash = ?
              )
        """, (
            huella_renovada,
            server_session_id,
            huella_presentada,
            huella_presentada
        ))

    if resultado.rowcount != 1:
        raise RuntimeError(
            "No se pudo actualizar el token local de la sesión."
        )


def confirmar_cierre_local(
    server_session_id,
    logout_at,
    close_reason=None
):
    inicializar_sesiones_locales()

    with conectar() as conexion:
        conexion.execute("""
            UPDATE local_sessions
            SET status = 'closed',
                logout_at = ?,
                close_reason = COALESCE(?, close_reason),
                logout_token_hash = NULL,
                previous_logout_token_hash = NULL
            WHERE server_session_id = ?
              AND status IN ('active', 'pending_close')
        """, (
            logout_at,
            close_reason,
            server_session_id
        ))


def obtener_cierres_pendientes():
    inicializar_sesiones_locales()

    with conectar() as conexion:
        registros = conexion.execute("""
            SELECT *
            FROM local_sessions
            WHERE status = 'pending_close'
            ORDER BY id ASC
        """).fetchall()

    return [dict(registro) for registro in registros]


def obtener_sesiones_locales_abiertas():
    inicializar_sesiones_locales()

    with conectar() as conexion:
        registros = conexion.execute("""
            SELECT *
            FROM local_sessions
            WHERE status IN ('active', 'pending_close')
            ORDER BY id ASC
        """).fetchall()

    return [dict(registro) for registro in registros]
