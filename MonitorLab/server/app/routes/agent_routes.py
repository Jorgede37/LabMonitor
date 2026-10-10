
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.agent_auth import autenticar_agente
from app.database import engine


# ==========================================
# CONFIGURACIÓN DEL ROUTER
# ==========================================

router = APIRouter(
    prefix="/agent",
    tags=["Agentes"]
)

TIPOS_PERMITIDOS = {
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


# ==========================================
# SINCRONIZACIÓN DEL INVENTARIO
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
        tipo: 0 for tipo in TIPOS_PERMITIDOS
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

        cantidades[componente.component_type] += 1

    # ======================================
    # VALIDAR INVENTARIO COMPLETO
    # ======================================

    inventario_confiable = (
        inventario.complete
        and cantidades["ram"] > 0
        and cantidades["gpu"] > 0
        and cantidades["storage"] > 0
        and cantidades["keyboard"] > 0
    )

    if not inventario_confiable:
        raise HTTPException(
            status_code=400,
            detail=(
                "Inventario incompleto o no confiable. "
                "No se actualizará el estado del hardware."
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
            {"computer_id": computer_id}
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

            existente = componentes_db.get(clave)

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
                        SET manufacturer = :manufacturer,
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
                {"component_id": existente["id"]}
            )

            desconectados += 1

        # ==================================
        # LIMPIAR CONTADORES ANTERIORES
        # ==================================

        # La confirmación de desconexiones
        # ahora ocurre localmente en SQLite.
        # Ya no necesitamos contadores del
        # servidor para esta computadora.

        connection.execute(
            text("""
                DELETE FROM dbo.hardware_missing_checks
                WHERE component_id IN (
                    SELECT id
                    FROM dbo.hardware_components
                    WHERE computer_id = :computer_id
                )
            """),
            {"computer_id": computer_id}
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
        "event_source": "local_agent"
    }
