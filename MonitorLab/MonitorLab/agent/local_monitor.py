
import sqlite3
import uuid

from datetime import datetime, timezone

from hardware import obtener_inventario
from local_database import (
    conectar,
    inicializar_base,
    inicializar_inventario_local
)


def fecha_actual():
    return datetime.now(timezone.utc).isoformat()


def crear_evento(
    conexion,
    componente,
    tipo_evento,
    anterior,
    nuevo
):
    fecha = fecha_actual()

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
        str(uuid.uuid4()),
        componente["component_type"],
        componente["hardware_identifier"],
        tipo_evento,
        anterior,
        nuevo,
        fecha,
        fecha
    ))


def comparar_inventario(inventario=None):

    # Permite recibir un inventario existente
    # o consultarlo directamente desde WMI.
    if inventario is None:
        inventario = obtener_inventario()

    if not inventario["complete"]:
        print("ERROR: Inventario WMI incompleto.")

        for error in inventario["errors"]:
            print("-", error)

        return False

    componentes = inventario["components"]

    inicializar_base()
    inicializar_inventario_local()

    fecha = fecha_actual()

    detectados = {
        (
            componente["component_type"],
            componente["hardware_identifier"]
        ): componente
        for componente in componentes
    }

    agregados = 0
    desconectados = 0
    reconectados = 0

    with conectar() as conexion:

        conexion.execute("BEGIN IMMEDIATE")

        anteriores = conexion.execute("""
            SELECT *
            FROM local_hardware
        """).fetchall()

        conocidos = {
            (
                componente["component_type"],
                componente["hardware_identifier"]
            ): dict(componente)
            for componente in anteriores
        }

        # ==================================
        # COMPONENTES PRESENTES
        # ==================================

        for clave, componente in detectados.items():

            anterior = conocidos.get(clave)

            if anterior is None:

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
                    VALUES (
                        ?, ?, ?, ?, ?,
                        'active', 0, ?, ?
                    )
                """, (
                    componente["component_type"],
                    componente["hardware_identifier"],
                    componente.get("manufacturer"),
                    componente.get("model"),
                    componente.get("serial_number"),
                    fecha,
                    fecha
                ))

                crear_evento(
                    conexion,
                    componente,
                    "HARDWARE_ADDED",
                    None,
                    "active"
                )

                agregados += 1

            else:

                if anterior["status"] == "removed":

                    crear_evento(
                        conexion,
                        componente,
                        "DEVICE_CONNECTED",
                        "removed",
                        "active"
                    )

                    reconectados += 1

                conexion.execute("""
                    UPDATE local_hardware
                    SET manufacturer = ?,
                        model = ?,
                        serial_number = ?,
                        status = 'active',
                        missing_count = 0,
                        last_seen = ?
                    WHERE id = ?
                """, (
                    componente.get("manufacturer"),
                    componente.get("model"),
                    componente.get("serial_number"),
                    fecha,
                    anterior["id"]
                ))

        # ==================================
        # COMPONENTES AUSENTES
        # ==================================

        for clave, anterior in conocidos.items():

            if clave in detectados:
                continue

            if anterior["status"] == "removed":
                continue

            nuevo_conteo = anterior["missing_count"] + 1

            if nuevo_conteo >= 2:

                conexion.execute("""
                    UPDATE local_hardware
                    SET status = 'removed',
                        missing_count = ?
                    WHERE id = ?
                """, (
                    nuevo_conteo,
                    anterior["id"]
                ))

                crear_evento(
                    conexion,
                    anterior,
                    "DEVICE_DISCONNECTED",
                    "active",
                    "removed"
                )

                desconectados += 1

            else:

                conexion.execute("""
                    UPDATE local_hardware
                    SET missing_count = ?
                    WHERE id = ?
                """, (
                    nuevo_conteo,
                    anterior["id"]
                ))

    print("\n===== MONITOREO LOCAL LABMONITOR =====")
    print("Componentes detectados:", len(componentes))
    print("Nuevos:", agregados)
    print("Desconectados:", desconectados)
    print("Reconectados:", reconectados)

    return True


if __name__ == "__main__":

    try:
        comparar_inventario()

    except (sqlite3.Error, OSError) as error:
        print("Error en SQLite:", error)
