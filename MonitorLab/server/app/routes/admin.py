
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.dependencies import solo_administradores
from app.database import engine
from app.security import generar_hash
from app.email_verification import emitir_codigo_verificacion
from app.email_service import obtener_estado_configuracion_correo
from app.reservation_context import fecha_local_actual, obtener_reserva_en_hora
from email_worker import worker_correo_activo
from session_worker import TIMEOUT_SIN_HEARTBEAT


router = APIRouter(
    prefix="/admin",
    tags=["Administración"]
)


# ============================================================
# MODELOS DE DATOS
# ============================================================

class LaboratorioCrear(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def validar_nombre(cls, valor: str) -> str:
        valor = valor.strip()
        if not valor:
            raise ValueError("El nombre del laboratorio es obligatorio")
        return valor


class LaboratorioActualizar(LaboratorioCrear):
    pass


class AdministradorCrear(BaseModel):
    full_name: str = Field(min_length=1, max_length=150)
    username: str = Field(min_length=1, max_length=50)
    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("full_name", "username")
    @classmethod
    def validar_texto_requerido(cls, valor: str) -> str:
        valor = valor.strip()
        if not valor:
            raise ValueError("Este campo es obligatorio")
        return valor

    @field_validator("email")
    @classmethod
    def normalizar_correo(cls, valor: EmailStr) -> str:
        return str(valor).strip().lower()


class AdministradorActualizar(BaseModel):
    full_name: str = Field(min_length=1, max_length=150)
    username: str = Field(min_length=1, max_length=50)
    email: EmailStr = Field(max_length=254)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    is_active: bool

    @field_validator("full_name", "username")
    @classmethod
    def validar_texto_requerido(cls, valor: str) -> str:
        valor = valor.strip()
        if not valor:
            raise ValueError("Este campo es obligatorio")
        return valor

    @field_validator("email")
    @classmethod
    def normalizar_correo(cls, valor: EmailStr) -> str:
        return str(valor).strip().lower()


class EstudianteActualizar(BaseModel):
    full_name: str = Field(min_length=1, max_length=150)
    student_id: str = Field(min_length=10, max_length=10)
    email: EmailStr = Field(max_length=254)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    is_active: bool

    @field_validator("full_name")
    @classmethod
    def validar_nombre(cls, valor: str) -> str:
        valor = valor.strip()
        if not valor:
            raise ValueError("El nombre completo es obligatorio")
        return valor

    @field_validator("student_id")
    @classmethod
    def validar_matricula(cls, valor: str) -> str:
        valor = valor.strip()
        if (
            not valor.isascii()
            or not valor.isdecimal()
            or len(valor) != 10
        ):
            raise ValueError(
                "La matrícula debe contener exactamente 10 dígitos"
            )
        return valor

    @field_validator("email")
    @classmethod
    def normalizar_correo(cls, valor: EmailStr) -> str:
        return str(valor).strip().lower()


class EstudianteCrear(BaseModel):
    full_name: str = Field(min_length=1, max_length=150)
    student_id: str = Field(min_length=10, max_length=10)
    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("full_name")
    @classmethod
    def validar_nombre(cls, valor: str) -> str:
        valor = valor.strip()
        if not valor:
            raise ValueError("El nombre completo es obligatorio")
        return valor

    @field_validator("student_id")
    @classmethod
    def validar_matricula(cls, valor: str) -> str:
        valor = valor.strip()
        if not valor.isascii() or not valor.isdecimal() or len(valor) != 10:
            raise ValueError(
                "La matrícula debe contener exactamente 10 dígitos"
            )
        return valor

    @field_validator("email")
    @classmethod
    def normalizar_correo(cls, valor: EmailStr) -> str:
        return str(valor).strip().lower()


class ComputadoraConfigurar(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    laboratory_id: int | None = Field(default=None, gt=0)

    @field_validator("display_name")
    @classmethod
    def validar_nombre(cls, valor: str) -> str:
        valor = valor.strip()
        if not valor:
            raise ValueError("El nombre de la computadora es obligatorio")
        return valor


# ============================================================
# UTILIDADES
# ============================================================

def convertir_fechas(registro):
    """
    Convierte las fechas almacenadas en SQL Server
    a formato ISO 8601 con zona horaria UTC.
    """
    resultado = dict(registro)

    campos_fecha = {
        "detected_at",
        "created_at",
        "last_seen",
        "first_seen",
        "updated_at",
        "sent_at",
        "email_sent_at"
    }

    for campo in campos_fecha:
        valor = resultado.get(campo)

        if isinstance(valor, datetime):
            if valor.tzinfo is None:
                valor = valor.replace(tzinfo=timezone.utc)

            resultado[campo] = (
                valor.astimezone(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
            )

    return resultado


# ============================================================
# ADMINISTRADORES
# ============================================================

@router.get("/administrators")
def listar_administradores(
    administrador: dict = Depends(solo_administradores)
):
    with engine.connect() as connection:
        resultado = connection.execute(
            text("""
                SELECT id, full_name, username, email, is_active, created_at
                FROM dbo.users
                WHERE role = 'admin'
                ORDER BY full_name, username
            """)
        )
        administradores = [
            convertir_fechas(fila)
            for fila in resultado.mappings().all()
        ]

    return {"total": len(administradores), "administrators": administradores}


@router.post("/administrators", status_code=201)
def crear_administrador(
    datos: AdministradorCrear,
    administrador: dict = Depends(solo_administradores)
):
    try:
        with engine.begin() as connection:
            existente = connection.execute(
                text("""
                    SELECT TOP 1 id
                    FROM dbo.users
                    WHERE LOWER(username) = LOWER(:username)
                       OR LOWER(email) = :email
                """),
                {"username": datos.username, "email": str(datos.email)}
            ).first()

            if existente is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Username or email is already registered"
                )

            fila = connection.execute(
                text("""
                    INSERT INTO dbo.users (
                        username, password_hash, role, full_name,
                        student_id, email, is_active
                    )
                    OUTPUT INSERTED.id, INSERTED.full_name,
                           INSERTED.username, INSERTED.email,
                           INSERTED.is_active, INSERTED.created_at
                    VALUES (
                        :username, :password_hash, 'admin', :full_name,
                        NULL, :email, 1
                    )
                """),
                {
                    "username": datos.username,
                    "password_hash": generar_hash(datos.password),
                    "full_name": datos.full_name,
                    "email": str(datos.email)
                }
            ).mappings().one()
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Username or email is already registered"
        )

    return {
        "message": "Administrador creado correctamente",
        "administrator": convertir_fechas(fila)
    }


@router.put("/administrators/{user_id}")
def actualizar_administrador(
    user_id: int,
    datos: AdministradorActualizar,
    administrador: dict = Depends(solo_administradores)
):
    if user_id <= 0:
        raise HTTPException(status_code=400, detail="Identificador inválido")

    if not datos.is_active and user_id == administrador["id"]:
        raise HTTPException(
            status_code=409,
            detail="No puedes desactivar tu propia cuenta."
        )

    try:
        with engine.begin() as connection:
            if not datos.is_active:
                connection.execute(
                    text("""
                        SELECT COUNT(*)
                        FROM dbo.users WITH (TABLOCKX, HOLDLOCK)
                        WHERE role = 'admin' AND is_active = 1
                    """)
                ).scalar_one()

            existente = connection.execute(
                text("""
                    SELECT id, is_active
                    FROM dbo.users WITH (UPDLOCK, HOLDLOCK)
                    WHERE id = :user_id AND role = 'admin'
                """),
                {"user_id": user_id}
            ).mappings().first()

            if existente is None:
                raise HTTPException(
                    status_code=404,
                    detail="Administrador no encontrado."
                )

            if existente["is_active"] and not datos.is_active:
                admins_activos = connection.execute(
                    text("""
                        SELECT COUNT(*)
                        FROM dbo.users WITH (UPDLOCK, HOLDLOCK)
                        WHERE role = 'admin' AND is_active = 1
                    """)
                ).scalar_one()
                if admins_activos <= 1:
                    raise HTTPException(
                        status_code=409,
                        detail="No puedes desactivar el último administrador activo."
                    )

            duplicado = connection.execute(
                text("""
                    SELECT TOP 1 id
                    FROM dbo.users
                    WHERE id <> :user_id
                      AND (
                          LOWER(username) = LOWER(:username)
                          OR LOWER(email) = :email
                      )
                """),
                {
                    "user_id": user_id,
                    "username": datos.username,
                    "email": str(datos.email)
                }
            ).first()
            if duplicado is not None:
                raise HTTPException(
                    status_code=409,
                    detail="El usuario o correo ya está registrado."
                )

            parametros = {
                "user_id": user_id,
                "full_name": datos.full_name,
                "username": datos.username,
                "email": str(datos.email),
                "is_active": datos.is_active
            }
            password_sql = ""
            if datos.password:
                password_sql = ", password_hash = :password_hash"
                parametros["password_hash"] = generar_hash(datos.password)

            fila = connection.execute(
                text(f"""
                    UPDATE dbo.users
                    SET full_name = :full_name,
                        username = :username,
                        email = :email,
                        is_active = :is_active
                        {password_sql}
                    OUTPUT INSERTED.id, INSERTED.full_name,
                           INSERTED.username, INSERTED.email,
                           INSERTED.is_active, INSERTED.created_at
                    WHERE id = :user_id AND role = 'admin'
                """),
                parametros
            ).mappings().one()
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="El usuario o correo ya está registrado."
        )

    return {
        "message": "Administrador actualizado correctamente.",
        "administrator": convertir_fechas(fila)
    }


@router.delete("/administrators/{user_id}")
def desactivar_administrador(
    user_id: int,
    administrador: dict = Depends(solo_administradores)
):
    if user_id <= 0:
        raise HTTPException(status_code=400, detail="Identificador inválido")
    if user_id == administrador["id"]:
        raise HTTPException(
            status_code=409,
            detail="No puedes desactivar tu propia cuenta."
        )

    with engine.begin() as connection:
        connection.execute(
            text("""
                SELECT COUNT(*)
                FROM dbo.users WITH (TABLOCKX, HOLDLOCK)
                WHERE role = 'admin' AND is_active = 1
            """)
        ).scalar_one()
        resultado = connection.execute(
            text("""
                UPDATE dbo.users
                SET is_active = 0
                OUTPUT INSERTED.id
                WHERE id = :user_id
                  AND role = 'admin'
                  AND is_active = 1
                  AND (
                      SELECT COUNT(*)
                      FROM dbo.users
                      WHERE role = 'admin' AND is_active = 1
                  ) > 1
            """),
            {"user_id": user_id}
        ).first()
        if resultado is None:
            existe = connection.execute(
                text("""
                    SELECT id
                    FROM dbo.users
                    WHERE id = :user_id AND role = 'admin'
                """),
                {"user_id": user_id}
            ).first()
            if existe is None:
                raise HTTPException(
                    status_code=404,
                    detail="Administrador no encontrado."
                )
            raise HTTPException(
                status_code=409,
                detail="No se puede desactivar esta cuenta; debe quedar al menos un administrador activo."
            )

    return {"message": "Administrador desactivado. Se conservó su historial."}


def eliminar_cuenta_permanentemente(
    connection,
    user_id,
    role,
    administrador
):
    if user_id <= 0:
        raise HTTPException(
            status_code=400,
            detail="Identificador inválido"
        )

    if role == "admin" and user_id == administrador["id"]:
        raise HTTPException(
            status_code=409,
            detail="No puedes eliminar tu propia cuenta."
        )

    if role == "admin":
        connection.execute(
            text("""
                SELECT COUNT(*)
                FROM dbo.users WITH (TABLOCKX, HOLDLOCK)
                WHERE role = 'admin' AND is_active = 1
            """)
        ).scalar_one()

    cuenta = connection.execute(
        text("""
            SELECT id, role, email, is_active
            FROM dbo.users WITH (UPDLOCK, HOLDLOCK)
            WHERE id = :user_id AND role = :role
        """),
        {"user_id": user_id, "role": role}
    ).mappings().first()

    if cuenta is None:
        nombre_tipo = "Administrador" if role == "admin" else "Estudiante"
        raise HTTPException(
            status_code=404,
            detail=f"{nombre_tipo} no encontrado."
        )

    if role == "admin":
        administradores_activos = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM dbo.users WITH (UPDLOCK, HOLDLOCK)
                WHERE role = 'admin'
                  AND is_active = 1
                  AND id <> :user_id
            """),
            {"user_id": user_id}
        ).scalar_one()
        if administradores_activos < 1:
            raise HTTPException(
                status_code=409,
                detail="No se puede eliminar al último administrador activo."
            )

    connection.execute(
        text("""
            UPDATE dbo.email_notifications
            SET recipient = CONCAT(
                    'deleted-user-', :user_id, '-',
                    id, '@invalid.invalid'
                ),
                subject = 'LabMonitor - Registro anonimizado',
                body = 'Notificación anonimizada por eliminación de cuenta.',
                status = CASE
                    WHEN status IN ('pending', 'processing')
                        THEN 'failed'
                    ELSE status
                END,
                last_error = CASE
                    WHEN status IN ('pending', 'processing')
                        THEN 'Destinatario anonimizado al eliminar la cuenta.'
                    ELSE NULL
                END
            WHERE LOWER(recipient) = LOWER(:email)
              AND :email IS NOT NULL
        """),
        {
            "user_id": user_id,
            "email": cuenta["email"]
        }
    )

    connection.execute(
        text("""
            UPDATE dbo.email_notifications
            SET subject = 'LabMonitor - Registro anonimizado',
                body = 'Notificación anonimizada por eliminación de cuenta.',
                last_error = NULL
            WHERE event_id IN (
                SELECT he.id
                FROM dbo.hardware_events AS he
                WHERE he.user_id = :user_id
                   OR he.session_id IN (
                       SELECT s.id
                       FROM dbo.sessions AS s
                       WHERE s.user_id = :user_id
                   )
            )
        """),
        {"user_id": user_id}
    )

    connection.execute(
        text("""
            UPDATE dbo.audit_logs
            SET user_id = NULL,
                target = 'deleted user',
                details = 'Account deleted; actor reference anonymized.'
            WHERE user_id = :user_id
        """),
        {"user_id": user_id}
    )

    connection.execute(
        text("""
            UPDATE dbo.hardware_events
            SET user_id = NULL
            WHERE user_id = :user_id
        """),
        {"user_id": user_id}
    )

    connection.execute(
        text("""
            UPDATE dbo.sessions
            SET user_id = NULL,
                logout_at = COALESCE(logout_at, SYSUTCDATETIME())
            WHERE user_id = :user_id
        """),
        {"user_id": user_id}
    )

    connection.execute(
        text("""
            DELETE FROM dbo.password_reset_tokens
            WHERE user_id = :user_id
        """),
        {"user_id": user_id}
    )

    if role == "admin":
        connection.execute(
            text("""
                UPDATE dbo.users
                SET teacher_approved_by = NULL
                WHERE teacher_approved_by = :user_id
            """),
            {"user_id": user_id}
        )
        connection.execute(
            text("""
                UPDATE dbo.lab_reservations
                SET created_by_user_id = NULL
                WHERE created_by_user_id = :user_id;

                UPDATE dbo.lab_reservations
                SET updated_by_user_id = NULL
                WHERE updated_by_user_id = :user_id;
            """),
            {"user_id": user_id}
        )

    connection.execute(
        text("""
            DELETE FROM dbo.users
            WHERE id = :user_id AND role = :role
        """),
        {"user_id": user_id, "role": role}
    )


@router.delete("/administrators/{user_id}/permanent")
def eliminar_administrador_permanentemente(
    user_id: int,
    administrador: dict = Depends(solo_administradores)
):
    with engine.begin() as connection:
        eliminar_cuenta_permanentemente(
            connection,
            user_id,
            "admin",
            administrador
        )

    return {
        "message": (
            "Administrador eliminado permanentemente. "
            "Su historial se conservó anonimizado."
        )
    }


@router.get("/students")
def listar_estudiantes(
    administrador: dict = Depends(solo_administradores)
):
    with engine.connect() as connection:
        resultado = connection.execute(
            text("""
                SELECT id, full_name, username, student_id,
                       email, email_verified, is_active, created_at
                FROM dbo.users
                WHERE role = 'student'
                ORDER BY full_name, username
            """)
        )
        estudiantes = [
            convertir_fechas(fila)
            for fila in resultado.mappings().all()
        ]
    return {"total": len(estudiantes), "students": estudiantes}


@router.post("/students", status_code=201)
def crear_estudiante(
    datos: EstudianteCrear,
    administrador: dict = Depends(solo_administradores)
):
    matricula = datos.student_id
    correo = str(datos.email)
    try:
        with engine.begin() as connection:
            duplicado = connection.execute(
                text("""
                    SELECT TOP 1 id
                    FROM dbo.users WITH (UPDLOCK, HOLDLOCK)
                    WHERE LOWER(username) = LOWER(:matricula)
                       OR student_id = :matricula
                       OR LOWER(email) = :email
                """),
                {
                    "matricula": matricula,
                    "email": correo
                }
            ).first()
            if duplicado is not None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "La matrícula, el nombre de usuario o "
                        "el correo ya están registrados."
                    )
                )

            fila = connection.execute(
                text("""
                    INSERT INTO dbo.users (
                        username, password_hash, role, full_name,
                        student_id, email, email_verified
                    )
                    OUTPUT INSERTED.id, INSERTED.full_name,
                           INSERTED.username, INSERTED.student_id,
                           INSERTED.email, INSERTED.email_verified,
                           INSERTED.is_active, INSERTED.created_at
                    VALUES (
                        :username, :password_hash, 'student', :full_name,
                        :student_id, :email, 0
                    )
                """),
                {
                    "username": matricula,
                    "password_hash": generar_hash(datos.password),
                    "full_name": datos.full_name,
                    "student_id": matricula,
                    "email": correo
                }
            ).mappings().one()

            emitir_codigo_verificacion(
                connection,
                fila["id"],
                correo,
                datos.full_name
            )
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=(
                "La matrícula, el nombre de usuario o "
                "el correo ya están registrados."
            )
        )

    return {
        "message": (
            "Estudiante creado. Se envió un código de seguridad "
            "al correo registrado; deberá ingresarlo en LabMonitor "
            "para habilitar su acceso."
        ),
        "student": convertir_fechas(fila)
    }


@router.put("/students/{user_id}")
def actualizar_estudiante(
    user_id: int,
    datos: EstudianteActualizar,
    administrador: dict = Depends(solo_administradores)
):
    if user_id <= 0:
        raise HTTPException(status_code=400, detail="Identificador inválido")

    try:
        with engine.begin() as connection:
            existe = connection.execute(
                text("""
                    SELECT id, full_name, email, email_verified
                    FROM dbo.users
                    WHERE id = :user_id AND role = 'student'
                """),
                {"user_id": user_id}
            ).mappings().first()
            if existe is None:
                raise HTTPException(
                    status_code=404,
                    detail="Estudiante no encontrado."
                )

            duplicado = connection.execute(
                text("""
                    SELECT TOP 1 id
                    FROM dbo.users WITH (UPDLOCK, HOLDLOCK)
                    WHERE id <> :user_id
                      AND (
                          LOWER(username) = LOWER(:student_id)
                          OR student_id = :student_id
                          OR LOWER(email) = :email
                      )
                """),
                {
                    "user_id": user_id,
                    "student_id": datos.student_id,
                    "email": str(datos.email)
                }
            ).first()
            if duplicado is not None:
                raise HTTPException(
                    status_code=409,
                    detail="La matrícula o el correo ya están registrados."
                )

            parametros = {
                "user_id": user_id,
                "full_name": datos.full_name,
                "student_id": datos.student_id,
                "email": str(datos.email),
                "is_active": datos.is_active
            }
            password_sql = ""
            if datos.password:
                password_sql = ", password_hash = :password_hash"
                parametros["password_hash"] = generar_hash(datos.password)

            fila = connection.execute(
                text(f"""
                    UPDATE dbo.users
                    SET full_name = :full_name,
                        username = :student_id,
                        student_id = :student_id,
                        email = :email,
                        is_active = :is_active
                        {password_sql}
                    OUTPUT INSERTED.id, INSERTED.full_name,
                           INSERTED.username, INSERTED.student_id,
                           INSERTED.email, INSERTED.email_verified,
                           INSERTED.is_active,
                           INSERTED.created_at
                    WHERE id = :user_id AND role = 'student'
                """),
                parametros
            ).mappings().one()

            correo_cambiado = (
                (existe["email"] or "").strip().casefold()
                != str(datos.email).strip().casefold()
            )
            if correo_cambiado:
                emitir_codigo_verificacion(
                    connection,
                    user_id,
                    str(datos.email),
                    datos.full_name
                )
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="La matrícula o el correo ya están registrados."
        )

    estudiante = convertir_fechas(fila)
    if correo_cambiado:
        estudiante["email_verified"] = False
    return {
        "message": (
            "Estudiante actualizado. Se envió un nuevo código de "
            "verificación al correo actualizado."
            if correo_cambiado
            else "Estudiante actualizado correctamente."
        ),
        "student": estudiante
    }


@router.delete("/students/{user_id}")
def desactivar_estudiante(
    user_id: int,
    administrador: dict = Depends(solo_administradores)
):
    if user_id <= 0:
        raise HTTPException(status_code=400, detail="Identificador inválido")
    with engine.begin() as connection:
        resultado = connection.execute(
            text("""
                UPDATE dbo.users
                SET is_active = 0
                OUTPUT INSERTED.id
                WHERE id = :user_id
                  AND role = 'student'
                  AND is_active = 1
            """),
            {"user_id": user_id}
        ).first()
        if resultado is None:
            existe = connection.execute(
                text("""
                    SELECT id
                    FROM dbo.users
                    WHERE id = :user_id AND role = 'student'
                """),
                {"user_id": user_id}
            ).first()
            if existe is None:
                raise HTTPException(
                    status_code=404,
                    detail="Estudiante no encontrado."
                )
            raise HTTPException(
                status_code=409,
                detail="El estudiante ya está desactivado."
            )
    return {"message": "Estudiante desactivado. Se conservó su historial."}


@router.delete("/students/{user_id}/permanent")
def eliminar_estudiante_permanentemente(
    user_id: int,
    administrador: dict = Depends(solo_administradores)
):
    with engine.begin() as connection:
        eliminar_cuenta_permanentemente(
            connection,
            user_id,
            "student",
            administrador
        )

    return {
        "message": (
            "Estudiante eliminado permanentemente. "
            "Su historial se conservó anonimizado."
        )
    }


# ============================================================
# DASHBOARD ADMINISTRATIVO
# ============================================================

@router.get("/dashboard")
def dashboard(
    administrador: dict = Depends(solo_administradores)
):
    with engine.connect() as connection:

        total_computadoras = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM dbo.computers
                WHERE is_active = 1
            """)
        ).scalar_one()

        total_componentes = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM dbo.hardware_components
                WHERE status = 'active'
            """)
        ).scalar_one()

        total_eventos = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM dbo.hardware_events
            """)
        ).scalar_one()

        total_estudiantes = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM dbo.users
                WHERE role = 'student'
                  AND is_active = 1
            """)
        ).scalar_one()

    return {
        "message": "Bienvenido al dashboard de LabMonitor",
        "administrator": administrador["username"],
        "status": "authorized",
        "statistics": {
            "computers": total_computadoras,
            "active_components": total_componentes,
            "hardware_events": total_eventos,
            "students": total_estudiantes
        }
    }


@router.get("/hardware-events")
def listar_eventos_hardware(
    administrador: dict = Depends(solo_administradores),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
):
    if from_date and to_date and from_date > to_date:
        raise HTTPException(
            status_code=400,
            detail="La fecha inicial no puede ser posterior a la fecha final."
        )

    top_clause = "" if from_date or to_date else "TOP 100"
    with engine.connect() as connection:
        resultado = connection.execute(
            text(f"""
                SELECT {top_clause}
                    he.id,
                    he.computer_id,
                    c.hostname,
                    c.lab,
                    hc.component_type,
                    hc.model,
                    hc.hardware_identifier,
                    he.event_type,
                    he.previous_value,
                    he.new_value,
                    he.detected_at,
                    COUNT(en.id) AS notification_count,
                    SUM(CASE
                        WHEN en.status IN ('pending', 'processing')
                            THEN 1
                        ELSE 0
                    END) AS pending_notifications,
                    SUM(CASE
                        WHEN en.status = 'sent' THEN 1
                        ELSE 0
                    END) AS sent_notifications,
                    SUM(CASE
                        WHEN en.status = 'failed' THEN 1
                        ELSE 0
                    END) AS failed_notifications,
                    MAX(en.sent_at) AS email_sent_at,
                    CASE
                        WHEN COUNT(en.id) = 0 THEN 'not_queued'
                        WHEN SUM(CASE
                            WHEN en.status = 'failed' THEN 1
                            ELSE 0
                        END) > 0 THEN 'failed'
                        WHEN SUM(CASE
                            WHEN en.status IN ('pending', 'processing')
                                THEN 1
                            ELSE 0
                        END) > 0 THEN 'pending'
                        ELSE 'sent'
                    END AS email_status
                FROM dbo.hardware_events he
                JOIN dbo.computers c
                    ON c.id = he.computer_id
                LEFT JOIN dbo.hardware_components hc
                    ON hc.id = he.component_id
                LEFT JOIN dbo.email_notifications en
                    ON en.event_id = he.id
                WHERE (:from_date IS NULL OR he.detected_at >= :from_date)
                  AND (
                    :to_date IS NULL
                    OR he.detected_at < DATEADD(DAY, 1, :to_date)
                  )
                GROUP BY
                    he.id,
                    he.computer_id,
                    c.hostname,
                    c.lab,
                    hc.component_type,
                    hc.model,
                    hc.hardware_identifier,
                    he.event_type,
                    he.previous_value,
                    he.new_value,
                    he.detected_at
                ORDER BY he.detected_at DESC, he.id DESC
            """),
            {
                "from_date": from_date,
                "to_date": to_date,
            }
        )

        eventos = [
            convertir_fechas(fila)
            for fila in resultado.mappings().all()
        ]

    correo = obtener_estado_configuracion_correo()
    correo["worker_running"] = worker_correo_activo()

    return {
        "total": len(eventos),
        "events": eventos,
        "email": correo
    }


# ============================================================
# LISTADO DE COMPUTADORAS
# ============================================================

@router.get("/computers")
def listar_computadoras(
    administrador: dict = Depends(solo_administradores),
    events_from: date | None = Query(default=None),
    events_to: date | None = Query(default=None),
):
    if events_from and events_to and events_from > events_to:
        raise HTTPException(
            status_code=400,
            detail="La fecha inicial no puede ser posterior a la fecha final."
        )

    with engine.connect() as connection:

        resultado = connection.execute(
            text("""
                SELECT
                    c.id,
                    c.hostname,
                    c.display_name,
                    c.mac_address,
                    c.serial_number,
                    c.machine_uuid,
                    c.ip_address,
                    c.lab,
                    c.laboratory_id,
                    c.operating_system,
                    c.agent_version,
                    c.is_active,
                    c.last_seen,
                    CASE
                        WHEN c.last_seen >= DATEADD(
                            SECOND,
                            -:heartbeat_timeout,
                            SYSUTCDATETIME()
                        ) THEN CAST(1 AS bit)
                        ELSE CAST(0 AS bit)
                    END AS is_online,
                    c.created_at,

                    (
                        SELECT COUNT(*)
                        FROM dbo.hardware_components hc
                        WHERE hc.computer_id = c.id
                          AND hc.status = 'active'
                    ) AS active_components,

                    (
                        SELECT COUNT(*)
                        FROM dbo.hardware_events he
                        WHERE he.computer_id = c.id
                    ) AS total_events,

                    (
                        SELECT COUNT(*)
                        FROM dbo.hardware_events he
                        WHERE he.computer_id = c.id
                          AND (
                            :events_from IS NULL
                            OR he.detected_at >= :events_from
                          )
                          AND (
                            :events_to IS NULL
                            OR he.detected_at < DATEADD(DAY, 1, :events_to)
                          )
                    ) AS matching_event_count

                FROM dbo.computers c
                WHERE (
                    (:events_from IS NULL AND :events_to IS NULL)
                    OR EXISTS (
                        SELECT 1
                        FROM dbo.hardware_events he
                        WHERE he.computer_id = c.id
                          AND (
                            :events_from IS NULL
                            OR he.detected_at >= :events_from
                          )
                          AND (
                            :events_to IS NULL
                            OR he.detected_at < DATEADD(DAY, 1, :events_to)
                          )
                    )
                )
                ORDER BY c.hostname
            """),
            {
                "heartbeat_timeout": TIMEOUT_SIN_HEARTBEAT,
                "events_from": events_from,
                "events_to": events_to,
            }
        )

        computadoras = [
            convertir_fechas(fila)
            for fila in resultado.mappings().all()
        ]

    return {
        "total": len(computadoras),
        "computers": computadoras
    }


# ============================================================
# DETALLE DE UNA COMPUTADORA
# ============================================================

@router.get("/computers/{computer_id}")
def detalle_computadora(
    computer_id: int,
    administrador: dict = Depends(solo_administradores)
):
    with engine.connect() as connection:

        computadora = connection.execute(
            text("""
                SELECT *
                FROM dbo.computers
                WHERE id = :computer_id
            """),
            {"computer_id": computer_id}
        ).mappings().first()

        if computadora is None:
            raise HTTPException(
                status_code=404,
                detail="Computadora no encontrada"
            )

        componentes = connection.execute(
            text("""
                SELECT
                    id,
                    component_type,
                    manufacturer,
                    model,
                    serial_number,
                    hardware_identifier,
                    status,
                    first_seen,
                    last_seen
                FROM dbo.hardware_components
                WHERE computer_id = :computer_id
                ORDER BY component_type, model
            """),
            {"computer_id": computer_id}
        ).mappings().all()

        eventos = connection.execute(
            text("""
                SELECT TOP 50
                    he.id,
                    he.component_id,
                    hc.component_type,
                    hc.model,
                    he.event_type,
                    he.previous_value,
                    he.new_value,
                    he.detected_at,
                    he.event_uuid,
                    he.user_id,
                    he.session_id,
                    he.reservation_id,
                    he.reserved_teacher_user_id,
                    he.reserved_teacher_name,
                    he.reserved_teacher_matricula,
                    he.reservation_subject,
                    he.reservation_was_active
                FROM dbo.hardware_events he
                LEFT JOIN dbo.hardware_components hc
                    ON he.component_id = hc.id
                WHERE he.computer_id = :computer_id
                ORDER BY he.detected_at DESC, he.id DESC
            """),
            {"computer_id": computer_id}
        ).mappings().all()
        reserva_actual = obtener_reserva_en_hora(
            connection,
            computadora.get("laboratory_id"),
            fecha_local_actual()
        )
        laboratorios = connection.execute(
            text("""
                SELECT id, name
                FROM dbo.laboratories
                ORDER BY name
            """)
        ).mappings().all()

    return {
        "computer": convertir_fechas(computadora),
        "current_reservation": reserva_actual,
        "laboratories": [
            convertir_fechas(laboratorio)
            for laboratorio in laboratorios
        ],
        "hardware": [
            convertir_fechas(componente)
            for componente in componentes
        ],
        "recent_events": [
            convertir_fechas(evento)
            for evento in eventos
        ]
    }


# ============================================================
# LISTAR LABORATORIOS
# ============================================================

@router.get("/laboratories")
def listar_laboratorios(
    administrador: dict = Depends(solo_administradores)
):
    with engine.connect() as connection:

        resultado = connection.execute(
            text("""
                SELECT
                    id,
                    name,
                    created_at
                FROM dbo.laboratories
                ORDER BY name
            """)
        ).mappings().all()

    laboratorios = [
        convertir_fechas(fila)
        for fila in resultado
    ]

    return {
        "total": len(laboratorios),
        "laboratories": laboratorios
    }


# ============================================================
# CREAR LABORATORIO
# ============================================================

@router.post("/laboratories", status_code=201)
def crear_laboratorio(
    datos: LaboratorioCrear,
    administrador: dict = Depends(solo_administradores)
):
    try:
        with engine.begin() as connection:
            existente = connection.execute(
                text("""
                    SELECT TOP 1 id
                    FROM dbo.laboratories WITH (UPDLOCK, HOLDLOCK)
                    WHERE LOWER(LTRIM(RTRIM(name))) =
                          LOWER(LTRIM(RTRIM(:name)))
                """),
                {"name": datos.name}
            ).first()
            if existente is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Ya existe un laboratorio con ese nombre"
                )

            resultado = connection.execute(
                text("""
                    INSERT INTO dbo.laboratories (name)
                    OUTPUT
                        INSERTED.id,
                        INSERTED.name,
                        INSERTED.created_at
                    VALUES (:name)
                """),
                {"name": datos.name}
            ).mappings().one()

            laboratorio = convertir_fechas(resultado)

    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Ya existe un laboratorio con ese nombre"
        )

    return {
        "message": "Laboratorio creado correctamente",
        "laboratory": laboratorio
    }


@router.put("/laboratories/{laboratory_id}")
def actualizar_laboratorio(
    laboratory_id: int,
    datos: LaboratorioActualizar,
    administrador: dict = Depends(solo_administradores)
):
    try:
        with engine.begin() as connection:
            laboratorio = connection.execute(
                text("""
                    SELECT id
                    FROM dbo.laboratories WITH (UPDLOCK, HOLDLOCK)
                    WHERE id = :laboratory_id
                """),
                {"laboratory_id": laboratory_id}
            ).first()
            if laboratorio is None:
                raise HTTPException(
                    status_code=404,
                    detail="El laboratorio no existe"
                )

            duplicado = connection.execute(
                text("""
                    SELECT TOP 1 id
                    FROM dbo.laboratories WITH (UPDLOCK, HOLDLOCK)
                    WHERE LOWER(LTRIM(RTRIM(name))) =
                          LOWER(LTRIM(RTRIM(:name)))
                      AND id <> :laboratory_id
                """),
                {
                    "name": datos.name,
                    "laboratory_id": laboratory_id
                }
            ).first()
            if duplicado is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Ya existe un laboratorio con ese nombre"
                )

            resultado = connection.execute(
                text("""
                    UPDATE dbo.laboratories
                    SET name = :name
                    OUTPUT
                        INSERTED.id,
                        INSERTED.name,
                        INSERTED.created_at
                    WHERE id = :laboratory_id
                """),
                {
                    "name": datos.name,
                    "laboratory_id": laboratory_id
                }
            ).mappings().one()

            connection.execute(
                text("""
                    UPDATE dbo.computers
                    SET lab = :name
                    WHERE laboratory_id = :laboratory_id
                """),
                {
                    "name": datos.name,
                    "laboratory_id": laboratory_id
                }
            )
            laboratorio_actualizado = convertir_fechas(resultado)
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Ya existe un laboratorio con ese nombre"
        )

    return {
        "message": "Laboratorio actualizado correctamente",
        "laboratory": laboratorio_actualizado
    }


@router.delete("/laboratories/{laboratory_id}")
def eliminar_laboratorio(
    laboratory_id: int,
    administrador: dict = Depends(solo_administradores)
):
    with engine.begin() as connection:
        laboratorio = connection.execute(
            text("""
                SELECT id
                FROM dbo.laboratories WITH (UPDLOCK, HOLDLOCK)
                WHERE id = :laboratory_id
            """),
            {"laboratory_id": laboratory_id}
        ).first()
        if laboratorio is None:
            raise HTTPException(
                status_code=404,
                detail="El laboratorio no existe"
            )

        referencias = connection.execute(
            text("""
                SELECT
                    (SELECT COUNT(*)
                     FROM dbo.computers
                     WHERE laboratory_id = :laboratory_id) AS computers,
                    (SELECT COUNT(*)
                     FROM dbo.lab_reservations
                     WHERE laboratory_id = :laboratory_id) AS reservations
            """),
            {"laboratory_id": laboratory_id}
        ).mappings().one()
        if referencias["computers"] or referencias["reservations"]:
            raise HTTPException(
                status_code=409,
                detail=(
                    "No se puede eliminar este laboratorio porque tiene "
                    f"{referencias['computers']} computadora(s) y "
                    f"{referencias['reservations']} reserva(s) asociadas. "
                    "Reasigna las computadoras y conserva o cancela las "
                    "reservas antes de eliminarlo."
                )
            )

        connection.execute(
            text("""
                DELETE FROM dbo.laboratories
                WHERE id = :laboratory_id
            """),
            {"laboratory_id": laboratory_id}
        )

    return {"message": "Laboratorio eliminado correctamente"}


# ============================================================
# CONFIGURAR COMPUTADORA
# ============================================================

@router.put("/computers/{computer_id}/configuration")
def configurar_computadora(
    computer_id: int,
    datos: ComputadoraConfigurar,
    administrador: dict = Depends(solo_administradores)
):
    with engine.begin() as connection:

        laboratorio = None
        if datos.laboratory_id is not None:
            laboratorio = connection.execute(
                text("""
                    SELECT id, name
                    FROM dbo.laboratories
                    WHERE id = :laboratory_id
                """),
                {"laboratory_id": datos.laboratory_id}
            ).mappings().first()

            if laboratorio is None:
                raise HTTPException(
                    status_code=404,
                    detail="El laboratorio seleccionado no existe"
                )

        # Verificar que exista la computadora
        computadora = connection.execute(
            text("""
                SELECT id
                FROM dbo.computers WITH (UPDLOCK, HOLDLOCK)
                WHERE id = :computer_id
            """),
            {"computer_id": computer_id}
        ).mappings().first()

        if computadora is None:
            raise HTTPException(
                status_code=404,
                detail="La computadora no existe"
            )

        # Evitar nombres repetidos en el mismo laboratorio
        if datos.laboratory_id is not None:
            duplicado = connection.execute(
                text("""
                    SELECT id
                    FROM dbo.computers
                    WHERE laboratory_id = :laboratory_id
                      AND display_name = :display_name
                      AND id <> :computer_id
                """),
                {
                    "laboratory_id": datos.laboratory_id,
                    "display_name": datos.display_name,
                    "computer_id": computer_id
                }
            ).first()

            if duplicado is not None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Ya existe otra computadora con ese nombre "
                        "en el laboratorio seleccionado"
                    )
                )

        # Guardar la configuración
        connection.execute(
            text("""
                UPDATE dbo.computers
                SET
                    display_name = :display_name,
                    laboratory_id = :laboratory_id,
                    lab = :lab
                WHERE id = :computer_id
            """),
            {
                "display_name": datos.display_name,
                "laboratory_id": datos.laboratory_id,
                "lab": laboratorio["name"] if laboratorio else None,
                "computer_id": computer_id
            }
        )

    return {
        "message": "Computadora configurada correctamente",
        "computer": {
            "id": computer_id,
            "display_name": datos.display_name,
            "laboratory_id": (
                laboratorio["id"] if laboratorio else None
            ),
            "lab": laboratorio["name"] if laboratorio else None
        }
    }
