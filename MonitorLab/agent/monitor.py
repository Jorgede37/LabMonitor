import os
import msvcrt
import sqlite3
import threading
import pythoncom

from datetime import datetime
from pathlib import Path

from hardware import obtener_inventario
from local_monitor import comparar_inventario
from local_database import conectar, inicializar_inventario_local
from sync_events import sincronizar_eventos
from sync_hardware import sincronizar
from logger import logger
from heartbeat import iniciar_heartbeat


# ==========================================
# CONFIGURACIÓN
# ==========================================

INTERVALO = 5

AGENT_DIR = Path(__file__).resolve().parent
PROGRAM_DATA = Path(os.environ.get("PROGRAMDATA", str(AGENT_DIR)))
LABMONITOR_DIR = PROGRAM_DATA / "LabMonitor"
DATA_DIR = LABMONITOR_DIR / "data"
LOCK_FILE = DATA_DIR / "monitor.lock"


# ==========================================
# BLOQUEO DE INSTANCIAS
# ==========================================

def obtener_bloqueo():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    archivo = open(LOCK_FILE, "a+b")

    try:
        archivo.seek(0, os.SEEK_END)

        if archivo.tell() == 0:
            archivo.write(b"0")
            archivo.flush()

        archivo.seek(0)

        msvcrt.locking(
            archivo.fileno(),
            msvcrt.LK_NBLCK,
            1
        )

        return archivo

    except OSError:
        archivo.close()
        return None


def liberar_bloqueo(archivo):
    if archivo is None:
        return

    try:
        archivo.seek(0)
        msvcrt.locking(
            archivo.fileno(),
            msvcrt.LK_UNLCK,
            1
        )
    finally:
        archivo.close()


# ==========================================
# AUSENCIAS SIN CONFIRMAR
# ==========================================

def hay_ausencias_pendientes():
    inicializar_inventario_local()

    with conectar() as conexion:
        resultado = conexion.execute("""
            SELECT COUNT(*)
            FROM local_hardware
            WHERE status = 'active'
              AND missing_count > 0
        """).fetchone()

    return resultado[0] > 0


# ==========================================
# MONITOREO AUTOMÁTICO
# ==========================================

def _iniciar_monitoreo_interno(detener=None):
    if detener is None:
        detener = threading.Event()

    bloqueo = obtener_bloqueo()

    if bloqueo is None:
        logger.error("LabMonitor ya se encuentra ejecutándose")
        print("ERROR: LabMonitor ya está ejecutándose.")
        return False

    hilo_heartbeat = None

    try:
        print("================================")
        print("       LABMONITOR AGENT")
        print("================================")
        print("Monitoreo automático iniciado")
        print(f"Intervalo de monitoreo: {INTERVALO} segundos")
        print("Heartbeat: configuración provisional")

        logger.info("Monitoreo automático iniciado")

        # El heartbeat sigue siendo provisional: la inactividad
        # del usuario no se mide correctamente desde la sesión 0.
        hilo_heartbeat = threading.Thread(
            target=iniciar_heartbeat,
            args=(detener,),
            daemon=True,
            name="LabMonitor-Heartbeat"
        )
        hilo_heartbeat.start()
        logger.info("Hilo de heartbeat iniciado")

        while not detener.is_set():
            fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n[{fecha}] Revisando hardware...")

            try:
                # 1. OBTENER INVENTARIO
                # Importante: se usa la función importada directamente.
                inventario = obtener_inventario()

                if not inventario.get("complete_types"):
                    logger.warning(
                        "No se pudo consultar ninguna categoría WMI. "
                        "Cantidades: %s. Errores: %s",
                        inventario["counts"],
                        inventario["errors"]
                    )
                    print(
                        "No hay categorías WMI confiables. "
                        "Se omite esta revisión."
                    )
                    continue

                if not inventario["complete"]:
                    logger.warning(
                        "Inventario WMI parcial. "
                        "Categorías confiables: %s. Errores: %s",
                        inventario["complete_types"],
                        inventario["errors"]
                    )
                    print(
                        "Inventario parcial. Se procesarán "
                        "solo las categorías confiables."
                    )

                # 2. COMPARAR CON SQLITE
                resultado_local = comparar_inventario(inventario)

                if not resultado_local:
                    logger.warning("Comparación local fallida")
                    continue

                # 3. VALIDAR AUSENCIAS
                ausencias_pendientes = hay_ausencias_pendientes()

                # 4. SINCRONIZAR INVENTARIO
                inventario_sincronizado = False

                if ausencias_pendientes:
                    print(
                        "Ausencias sin confirmar. "
                        "Inventario remoto pospuesto."
                    )
                else:
                    print(
                        "\nSincronizando inventario "
                        "antes de enviar eventos..."
                    )

                    inventario_sincronizado = sincronizar(inventario)

                    if inventario_sincronizado:
                        logger.info(
                            "Inventario sincronizado con el servidor"
                        )
                        print("Inventario remoto actualizado.")
                    else:
                        logger.warning(
                            "Sincronización de inventario fallida"
                        )
                        print(
                            "No se pudo actualizar "
                            "el inventario remoto."
                        )

                # 5. SINCRONIZAR EVENTOS
                if not inventario_sincronizado:
                    print("Sincronización de eventos pospuesta.")
                    continue

                eventos_enviados = sincronizar_eventos()

                if eventos_enviados:
                    logger.info("Eventos locales sincronizados")
                    print("Estado: sincronización exitosa")
                else:
                    logger.warning("Eventos pendientes de envío")
                    print(
                        "El servidor rechazó eventos "
                        "o no pudo procesarlos."
                    )
                    print(
                        "Los eventos permanecen "
                        "guardados localmente."
                    )

            except (
                sqlite3.Error,
                OSError,
                ValueError,
                KeyError
            ):
                logger.exception("Error durante el monitoreo")

            except Exception:
                logger.exception(
                    "Error inesperado durante el monitoreo"
                )

            finally:
                detener.wait(INTERVALO)

    finally:
        detener.set()

        if hilo_heartbeat is not None:
            hilo_heartbeat.join(timeout=12)

            if hilo_heartbeat.is_alive():
                logger.warning(
                    "El hilo de heartbeat no terminó "
                    "dentro del tiempo esperado"
                )
            else:
                logger.info("Hilo de heartbeat detenido")

        liberar_bloqueo(bloqueo)
        logger.info("Monitoreo detenido")
        print("\nMonitoreo detenido.")

    return True


# ==========================================
# INICIALIZACIÓN COM PARA WMI
# ==========================================

def iniciar_monitoreo(detener=None):
    """Inicializa COM en el hilo que realiza las consultas WMI."""
    pythoncom.CoInitialize()
    try:
        return _iniciar_monitoreo_interno(detener)
    finally:
        pythoncom.CoUninitialize()


# ==========================================
# EJECUCIÓN MANUAL
# ==========================================

if __name__ == "__main__":
    detener = threading.Event()
    try:
        iniciar_monitoreo(detener)
    except KeyboardInterrupt:
        detener.set()
        print("\nDetención manual solicitada.")
