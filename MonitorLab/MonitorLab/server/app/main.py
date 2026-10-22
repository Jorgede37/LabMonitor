
from fastapi import FastAPI

from app.routes.users import router as users_router
from app.routes.auth import router as auth_router
from app.routes.admin import router as admin_router
from app.routes.computers import router as computers_router
from app.routes.agent_routes import router as agent_router
from app.routes.sessions import router as sessions_router
from app.routes import agent_events


app = FastAPI(
    title="LabMonitor API",
    description="Sistema de monitoreo de computadoras de laboratorio",
    version="1.0.0"
)


app.include_router(users_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(computers_router)
app.include_router(agent_router)
app.include_router(agent_events.router)
app.include_router(sessions_router)


@app.get("/")
def inicio():
    return {
        "aplicacion": "LabMonitor",
        "estado": "online",
        "mensaje": "Servidor funcionando correctamente"
    }
