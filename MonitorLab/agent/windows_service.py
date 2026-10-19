
import os
import sys
import threading
import traceback

from pathlib import Path

import win32service
import win32serviceutil
import win32event
import servicemanager

from monitor import iniciar_monitoreo
from local_bridge import iniciar_puente, despertar_pipe
from logger import logger


# ==========================================
# CONFIGURACION DEL SERVICIO
# ==========================================

SERVICE_NAME = "LabMonitorAgent"
STOP_TIMEOUT = 15

if getattr(sys, "frozen", False):
    AGENT_DIR = Path(sys.executable).resolve().parent
else:
    AGENT_DIR = Path(__file__).resolve().parent

if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


# ==========================================
# SERVICIO PRINCIPAL
# ==========================================

class LabMonitorService(
    win32serviceutil.ServiceFramework
):

    _svc_name_ = SERVICE_NAME

    _svc_display_name_ = (
        "LabMonitor - Agente de Monitoreo"
    )

    _svc_description_ = (
        "Monitorea hardware, registra eventos, "
        "sincroniza información con LabMonitor "
        "y atiende las sesiones estudiantiles."
    )

    _svc_deps_ = []

    def __init__(self, args):
        super().__init__(args)

        self.stop_event = win32event.CreateEvent(
            None,
            1,
            0,
            None
        )

        self.detener = threading.Event()
        self.hilos = []

        self.error_trabajador = None
        self.error_lock = threading.Lock()

        self.detencion_solicitada = False

    # ======================================
    # SOLICITAR DETENCION INTERNA
    # ======================================

    def solicitar_detencion(self):
        self.detener.set()

        win32event.SetEvent(
            self.stop_event
        )

        try:
            despertar_pipe()
        except Exception:
            logger.exception(
                "No fue posible despertar el pipe."
            )

    # ======================================
    # EJECUTAR COMPONENTES
    # ======================================

    def ejecutar_componente(
        self,
        nombre,
        funcion
    ):
        try:
            logger.info(
                "Iniciando componente: %s",
                nombre
            )

            funcion(self.detener)

            if not self.detener.is_set():
                raise RuntimeError(
                    f"El componente {nombre} "
                    "terminó inesperadamente."
                )

        except Exception:
            detalle = traceback.format_exc()

            logger.error(
                "Fallo en %s:\n%s",
                nombre,
                detalle
            )

            with self.error_lock:
                if self.error_trabajador is None:
                    self.error_trabajador = nombre

            self.solicitar_detencion()

        finally:
            logger.info(
                "Componente finalizado: %s",
                nombre
            )

    # ======================================
    # DETENCION SOLICITADA POR WINDOWS
    # ======================================

    def SvcStop(self):
        self.detencion_solicitada = True

        self.ReportServiceStatus(
            win32service.SERVICE_STOP_PENDING,
            waitHint=30000
        )

        logger.info(
            "Windows solicitó detener LabMonitor."
        )

        self.solicitar_detencion()

    # ======================================
    # INICIAR SERVICIO
    # ======================================

    def SvcDoRun(self):
        try:
            self.ejecutar_servicio()

        except Exception:
            detalle = traceback.format_exc()

            logger.error(
                "Error fatal del servicio:\n%s",
                detalle
            )

            servicemanager.LogErrorMsg(
                "LabMonitorAgent encontró "
                "un error fatal."
            )

            raise

    def ejecutar_servicio(self):
        os.chdir(AGENT_DIR)

        servicemanager.LogInfoMsg(
            "LabMonitorAgent iniciado"
        )

        logger.info(
            "Servicio LabMonitor iniciado."
        )

        componentes = [
            (
                "Monitor de hardware",
                iniciar_monitoreo
            ),
            (
                "Puente local",
                iniciar_puente
            ),
        ]

        for nombre, funcion in componentes:
            if self.detener.is_set():
                break

            hilo = threading.Thread(
                target=self.ejecutar_componente,
                args=(nombre, funcion),
                name=nombre.replace(" ", ""),
                daemon=True
            )

            self.hilos.append(hilo)
            hilo.start()

        win32event.WaitForSingleObject(
            self.stop_event,
            win32event.INFINITE
        )

        self.solicitar_detencion()

        for hilo in self.hilos:
            hilo.join(timeout=STOP_TIMEOUT)

            if hilo.is_alive():
                logger.error(
                    "El componente %s no se detuvo "
                    "dentro del tiempo esperado.",
                    hilo.name
                )

        if self.error_trabajador:
            logger.error(
                "Servicio detenido por fallo en: %s",
                self.error_trabajador
            )

            servicemanager.LogErrorMsg(
                "LabMonitorAgent terminó por fallo "
                f"en {self.error_trabajador}."
            )

            # Comunicar un fallo al Administrador
            # de servicios para permitir recuperación.
            self.ReportServiceStatus(
                win32service.SERVICE_STOPPED,
                win32ExitCode=1066,
                svcExitCode=1
            )

        else:
            logger.info(
                "Servicio LabMonitor finalizado."
            )


# ==========================================
# ADMINISTRACION Y ARRANQUE
# ==========================================

def main():
    if getattr(sys, "frozen", False):
        if len(sys.argv) == 1:
            # Ejecución iniciada por el SCM.
            servicemanager.Initialize()

            servicemanager.PrepareToHostSingle(
                LabMonitorService
            )

            servicemanager.StartServiceCtrlDispatcher()

        else:
            # Comandos como install, remove,
            # start, stop y debug.
            win32serviceutil.HandleCommandLine(
                LabMonitorService
            )

    else:
        win32serviceutil.HandleCommandLine(
            LabMonitorService
        )


if __name__ == "__main__":
    main()
