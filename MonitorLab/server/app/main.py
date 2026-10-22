
import asyncio
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from session_worker import iniciar_worker

from email_worker import iniciar_worker_email
from reservation_email_worker import iniciar_worker_reservas
from teacher_approval_email_worker import iniciar_worker_aprobaciones

from app.routes.users import router as users_router
from app.routes.auth import router as auth_router
from app.routes.admin import router as admin_router
from app.routes.computers import router as computers_router
from app.routes.enrollment import router as enrollment_router
from app.routes.agent_routes import router as agent_router
from app.routes.sessions import router as sessions_router
from app.routes import agent_events
from app.routes.reservations import router as reservations_router


logger = logging.getLogger("LabMonitor-API")


@asynccontextmanager
async def lifespan(_app):
    detener_worker = threading.Event()
    detener_worker_correo = threading.Event()
    detener_worker_reservas = threading.Event()
    detener_worker_aprobaciones = threading.Event()
    worker = threading.Thread(
        target=iniciar_worker,
        args=(detener_worker,),
        name="LabMonitor-SessionWorker",
        daemon=True
    )
    worker_correo = threading.Thread(
        target=iniciar_worker_email,
        args=(detener_worker_correo,),
        name="LabMonitor-EmailWorker",
        daemon=True
    )
    worker_reservas = threading.Thread(
        target=iniciar_worker_reservas,
        args=(detener_worker_reservas,),
        name="LabMonitor-ReservationEmailWorker",
        daemon=True
    )
    worker_aprobaciones = threading.Thread(
        target=iniciar_worker_aprobaciones,
        args=(detener_worker_aprobaciones,),
        name="LabMonitor-TeacherApprovalEmailWorker",
        daemon=True
    )
    worker.start()
    worker_correo.start()
    worker_reservas.start()
    worker_aprobaciones.start()

    try:
        yield
    finally:
        detener_worker.set()
        detener_worker_correo.set()
        detener_worker_reservas.set()
        detener_worker_aprobaciones.set()
        await asyncio.to_thread(worker.join, 15)
        await asyncio.to_thread(worker_correo.join, 15)
        await asyncio.to_thread(worker_reservas.join, 15)
        await asyncio.to_thread(worker_aprobaciones.join, 15)

        if worker.is_alive():
            logger.error(
                "El worker de sesiones no se detuvo a tiempo."
            )

        if worker_correo.is_alive():
            logger.error(
                "El worker de correo no se detuvo a tiempo."
            )

        if worker_reservas.is_alive():
            logger.error(
                "El worker de reservas no se detuvo a tiempo."
            )

        if worker_aprobaciones.is_alive():
            logger.error(
                "El worker de aprobación docente no se detuvo a tiempo."
            )


app = FastAPI(
    title="LabMonitor API",
    description="Sistema de monitoreo de computadoras de laboratorio",
    version="1.0.0",
    lifespan=lifespan
)


app.include_router(users_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(computers_router)
app.include_router(enrollment_router)
app.include_router(agent_router)
app.include_router(agent_events.router)
app.include_router(sessions_router)
app.include_router(reservations_router)


@app.get("/")
def inicio():
    return {
        "aplicacion": "LabMonitor",
        "estado": "online",
        "mensaje": "Servidor funcionando correctamente"
    }
