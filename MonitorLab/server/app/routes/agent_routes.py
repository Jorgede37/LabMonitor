from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.agent_auth import autenticar_agente
from app.database import engine


# ==========================================
# CONFIGURACION DEL ROUTER
# ==========================================

router = APIRouter(
    prefix="/agent",
    tags=["Agentes"]
)

TIPOS_PERMITIDOS = {
    "cpu",
    "motherboard",
    "ram",
    "gpu",
    "storage",
    "mouse",
    "keyboard",
    "network"
}


# ==========================================
# IDENTIFICAR AGENTE
# ==========================================

@router.get("/me")
def identificar_agente(
    agente: dict = Depends(autenticar_agente)
):
    return {
        "message": "Agente autenticado correctamente",
        "computer_id": agente["computer_id"],
        "hostname": agente["hostname"]
    }


# ==========================================
# MODELOS
# ==========================================

class ComponenteHardware(BaseModel):
    component_type: str
    manufacturer: str | None = None
    model: str | None = None
    serial_number: str | None = None
    hardware_identifier: str = Field(
        min_length=1,
        max_length=255
    )


class InventarioHardware(BaseModel):
    components: list[ComponenteHardware]
    complete: bool = False
    complete_types: list[str] | None = None


class HeartbeatRequest(BaseModel):
    pass


# ==========================================
# SINCRONIZACION DEL INVENTARIO
# ==========================================

@router.post("/hardware/sync")
def sincronizar_hardware(
    inventario: InventarioHardware,
    agente: dict = Depends(autenticar_agente)
):
    computer_id = agente["computer_id"]

    if len(inventario.components) > 200:
        raise HTTPException(
            status_code=400,
            detail="Inventario demasiado grande"
        )

    identificadores = set()
    presentes = set()

    cantidades = {
        tipo: 0
        for tipo in TIPOS_PERMITIDOS
    }

    # ======================================
    # VALIDAR COMPONENTES
    # ======================================

    for componente in inventario.components:

        if componente.component_type not in TIPOS_PERMITIDOS:
            raise HTTPException(
                status_code=400,
                detail="Tipo de componente no permitido"
            )

        clave = (
            componente.component_type,
            componente.hardware_identifier
        )

        if clave in identificadores:
            raise HTTPException(
                status_code=400,
                detail="Componentes duplicados"
            )

        identificadores.add(clave)
        presentes.add(clave)

        cantidades[
            componente.component_type
        ] += 1

    if inventario.complete_types is None:
        if (
            not inventario.complete
            or any(
                cantidades[tipo] == 0
                for tipo in ("ram", "gpu", "storage", "keyboard")
            )
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Inventario incompleto o no confiable. "
                    "No se actualizara el estado del hardware."
                )
            )
        tipos_consultados = set(TIPOS_PERMITIDOS)
    else:
        tipos_consultados = set(inventario.complete_types)

    if not tipos_consultados or not tipos_consultados.issubset(
        TIPOS_PERMITIDOS
    ):
        raise HTTPException(
            status_code=400,
            detail="El inventario no contiene categorías confiables."
        )

    if any(
        tipo in tipos_consultados and cantidades[tipo] == 0
        for tipo in ("ram", "gpu", "storage", "keyboard")
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Una categoría obligatoria está vacía. "
                "No se actualizará su estado."
            )
        )

    if any(
        componente.component_type not in tipos_consultados
        for componente in inventario.components
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "El inventario incluye componentes de una "
                "categoría no consultada correctamente."
            )
        )

    registrados = 0
    actualizados = 0
    desconectados = 0
    reconectados = 0

    # ======================================
    # ACTUALIZAR BASE DE DATOS
    # ======================================

    with engine.begin() as connection:

        existentes = connection.execute(
            text("""
                SELECT
                    id,
                    component_type,
                    hardware_identifier,
                    status
                FROM dbo.hardware_components
                WHERE computer_id = :computer_id
            """),
            {
                "computer_id": computer_id
            }
        ).mappings().all()

        componentes_db = {
            (
                fila["component_type"],
                fila["hardware_identifier"]
            ): fila
            for fila in existentes
            if fila["hardware_identifier"] is not None
        }

        # ==================================
        # COMPONENTES PRESENTES
        # ==================================

        for componente in inventario.components:

            clave = (
                componente.component_type,
                componente.hardware_identifier
            )

            existente = componentes_db.get(
                clave
            )

            parametros = {
                "computer_id": computer_id,
                **componente.model_dump()
            }

            if existente:

                if existente["status"] == "removed":
                    reconectados += 1

                connection.execute(
                    text("""
                        UPDATE dbo.hardware_components
                        SET
                            manufacturer = :manufacturer,
                            model = :model,
                            serial_number = :serial_number,
                            status = 'active',
                            last_seen = SYSUTCDATETIME()
                        WHERE id = :id
                    """),
                    {
                        **parametros,
                        "id": existente["id"]
                    }
                )

                actualizados += 1

            else:

                connection.execute(
                    text("""
                        INSERT INTO dbo.hardware_components (
                            computer_id,
                            component_type,
                            manufacturer,
                            model,
                            serial_number,
                            hardware_identifier,
                            status
                        )
                        VALUES (
                            :computer_id,
                            :component_type,
                            :manufacturer,
                            :model,
                            :serial_number,
                            :hardware_identifier,
                            'active'
                        )
                    """),
                    parametros
                )

                registrados += 1

        # ==================================
        # COMPONENTES AUSENTES
        # ==================================

        for clave, existente in componentes_db.items():

            if clave[0] not in tipos_consultados:
                continue

            if clave in presentes:
                continue

            if existente["status"] != "active":
                continue

            connection.execute(
                text("""
                    UPDATE dbo.hardware_components
                    SET status = 'removed'
                    WHERE id = :component_id
                """),
                {
                    "component_id": existente["id"]
                }
            )

            desconectados += 1

        # ==================================
        # LIMPIAR CONTADORES ANTERIORES
        # ==================================

        connection.execute(
            text("""
                DELETE FROM dbo.hardware_missing_checks
                WHERE component_id IN (
                    SELECT id
                    FROM dbo.hardware_components
                    WHERE computer_id = :computer_id
                )
            """),
            {
                "computer_id": computer_id
            }
        )

    return {
        "message": "Inventario sincronizado",
        "computer_id": computer_id,
        "registered": registrados,
        "updated": actualizados,
        "disconnected": desconectados,
        "reconnected": reconectados,
        "events_created": 0,
        "total": len(inventario.components),
        "absence_check_enabled": False,
        "event_source": "local_agent",
        "complete_types": sorted(tipos_consultados)
    }


# ==========================================
# HEARTBEAT Y ACTIVIDAD DEL ALUMNO
# ==========================================

@router.post("/heartbeat")
def registrar_heartbeat(
    datos: HeartbeatRequest,
    agente: dict = Depends(autenticar_agente)
):

    computer_id = agente["computer_id"]

    with engine.begin() as connection:

        # Hora tomada del servidor SQL Server.
        # No dependemos del reloj del agente.

        resultado = connection.execute(
            text("""
                UPDATE dbo.computers
                SET last_seen = SYSUTCDATETIME()
                OUTPUT INSERTED.last_seen
                WHERE id = :computer_id
            """),
            {
                "computer_id": computer_id
            }
        ).scalar_one_or_none()

        if resultado is None:
            raise HTTPException(
                status_code=404,
                detail="Computadora no encontrada"
            )

    return {
        "message": "Heartbeat registrado",
        "computer_id": computer_id,
        "last_seen": resultado.isoformat()
    }

# ==========================================
# CONFIGURACION INICIAL DEL EQUIPO
# ==========================================

@router.get("/configuration")
def consultar_configuracion_agente(
    agente: dict = Depends(autenticar_agente)
):
    computer_id = agente["computer_id"]

    with engine.connect() as connection:

        computadora = connection.execute(
            text("""
                SELECT
                    c.id,
                    c.hostname,
                    c.display_name,
                    c.laboratory_id,
                    l.name AS laboratory_name
                FROM dbo.computers AS c
                LEFT JOIN dbo.laboratories AS l
                    ON c.laboratory_id = l.id
                WHERE c.id = :computer_id
            """),
            {"computer_id": computer_id}
        ).mappings().first()

    if computadora is None:
        raise HTTPException(
            status_code=404,
            detail="Computadora no encontrada"
        )

    configurada = bool(computadora["display_name"])

    return {
        "computer_id": computadora["id"],
        "hostname": computadora["hostname"],
        "display_name": computadora["display_name"],
        "laboratory_id": computadora["laboratory_id"],
        "laboratory_name": computadora["laboratory_name"],
        "configured": configurada
    }