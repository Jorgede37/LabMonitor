
import os
import sys
import threading

from pathlib import Path

import win32service
import win32serviceutil
import win32event
import servicemanager

from monitor import iniciar_monitoreo
from logger import logger


# ==========================================
# CONFIGURACIÓN DEL SERVICIO
# ==========================================

AGENT_DIR = Path(__file__).resolve().parent

# Asegurar que los módulos del agente
# puedan importarse desde cualquier directorio.
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


class LabMonitorService(
    win32serviceutil.ServiceFramework
):

    _svc_name_ = "LabMonitorAgent"

    _svc_display_name_ = (
        "LabMonitor - Agente de Monitoreo"
    )

    _svc_description_ = (
        "Monitorea los componentes de hardware, "
        "registra eventos localmente y los "
        "sincroniza con el servidor LabMonitor."
    )

    _svc_deps_ = []

    def __init__(self, args):

        super().__init__(args)

        self.stop_event = win32event.CreateEvent(
            None,
            0,
            0,
            None
        )

        self.detener = threading.Event()

        self.trabajador = None

    # ======================================
    # DETENER SERVICIO
    # ======================================

    def SvcStop(self):

        self.ReportServiceStatus(
            win32service.SERVICE_STOP_PENDING
        )

        logger.info(
            "Windows solicitó detener LabMonitor"
        )

        self.detener.set()

        win32event.SetEvent(self.stop_event)

    # ======================================
    # INICIAR SERVICIO
    # ======================================

    def SvcDoRun(self):

        os.chdir(AGENT_DIR)

        servicemanager.LogInfoMsg(
            "LabMonitorAgent iniciado"
        )

        logger.info(
            "Servicio LabMonitor iniciado"
        )

        self.trabajador = threading.Thread(
            target=iniciar_monitoreo,
            args=(self.detener,),
            daemon=False
        )

        self.trabajador.start()

        # Esperar la solicitud de detención.
        # El monitor utiliza su propia señal
        # para finalizar de manera ordenada.
        win32event.WaitForSingleObject(
            self.stop_event,
            win32event.INFINITE
        )

        self.detener.set()

        self.trabajador.join()

        logger.info(
            "Servicio LabMonitor finalizado"
        )


# ==========================================
# ADMINISTRACIÓN DEL SERVICIO
# ==========================================

if __name__ == "__main__":

    win32serviceutil.HandleCommandLine(
        LabMonitorService
    )
