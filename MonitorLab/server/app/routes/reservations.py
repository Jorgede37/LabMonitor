from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.database import engine
from app.dependencies import (
    solo_administradores,
    solo_docentes_aprobados,
    docentes_o_administradores
)
from app.email_service import obtener_correos_administradores


router = APIRouter(tags=["Reservas de laboratorio"])
ZONA_LOCAL = ZoneInfo("America/Mexico_City")
HORA_INICIO = 7
HORA_FIN = 16


class ReservaCrear(BaseModel):
    laboratory_id: int = Field(gt=0)
    reservation_date: date
    start_time: time
    end_time: time
    subject: str = Field(min_length=1, max_length=150)

    @field_validator("subject")
    @classmethod
    def validar_materia(cls, valor: str) -> str:
        valor = valor.strip()
        if not valor:
            raise ValueError("La materia es obligatoria")
        return valor


class ReservaAdministrativa(ReservaCrear):
    teacher_user_id: int = Field(gt=0)


class ReservaRecurrente(BaseModel):
    laboratory_id: int = Field(gt=0)
    teacher_user_id: int = Field(gt=0)
    start_date: date
    end_date: date
    start_time: time
    end_time: time
    subject: str = Field(min_length=1, max_length=150)
    weekdays: list[int] = Field(min_length=1, max_length=6)

    @field_validator("subject")
    @classmethod
    def validar_materia(cls, valor: str) -> str:
        valor = valor.strip()
        if not valor:
            raise ValueError("La materia es obligatoria")
        return valor


class ReservaActualizar(BaseModel):
    laboratory_id: int = Field(gt=0)
    reservation_date: date
    start_time: time
    end_time: time
    subject: str = Field(min_length=1, max_length=150)

    @field_validator("subject")
    @classmethod
    def validar_materia(cls, valor: str) -> str:
        valor = valor.strip()
        if not valor:
            raise ValueError("La materia es obligatoria")
        return valor


def validar_fecha_reserva(fecha: date) -> None:
    if fecha.weekday() == 6:
        raise HTTPException(
            status_code=422,
            detail="El laboratorio no está disponible los domingos."
        )
    if fecha < datetime.now(ZONA_LOCAL).date():
        raise HTTPException(
            status_code=422,
            detail="No se pueden reservar fechas pasadas."
        )


def fechas_recurrentes(
    fecha_inicio: date,
    fecha_fin: date,
    dias_semana: list[int]
) -> list[date]:
    if fecha_fin < fecha_inicio:
        raise HTTPException(
            status_code=422,
            detail="La fecha final debe ser igual o posterior a la inicial."
        )
    if (fecha_fin - fecha_inicio).days > 365:
        raise HTTPException(
            status_code=422,
            detail="El periodo de reserva no puede superar 366 días."
        )
    if not dias_semana or any(dia < 0 or dia > 5 for dia in dias_semana):
        raise HTTPException(
            status_code=422,
            detail="Selecciona uno o más días de lunes a sábado."
        )
    if len(set(dias_semana)) != len(dias_semana):
        raise HTTPException(
            status_code=422,
            detail="No repitas los días seleccionados."
        )
    if fecha_inicio < datetime.now(ZONA_LOCAL).date():
        raise HTTPException(
            status_code=422,
            detail="No se pueden reservar fechas pasadas."
        )

    fechas = []
    fecha = fecha_inicio
    while fecha <= fecha_fin:
        if fecha.weekday() in dias_semana:
            fechas.append(fecha)
        fecha += timedelta(days=1)
    return fechas


def horarios_disponibles() -> list[tuple[time, time]]:
    return [
        (time(hora), time(hora + 1))
        for hora in range(HORA_INICIO, HORA_FIN)
    ]


def normalizar_hora(valor: time) -> time:
    return time(valor.hour, valor.minute)


def validar_hora_reserva(valor: time) -> time:
    if (
        valor.tzinfo is not None
        or valor.minute != 0
        or valor.second != 0
        or valor.microsecond != 0
        or not HORA_INICIO <= valor.hour < HORA_FIN
    ):
        raise HTTPException(
            status_code=422,
            detail="Selecciona un bloque de una hora entre 07:00 y 16:00."
        )

    return time(valor.hour)


def validar_intervalo_reserva(inicio: time, fin: time) -> tuple[time, time]:
    hora_inicio = validar_hora_reserva(inicio)
    if (
        fin.tzinfo is not None
        or fin.minute != 0
        or fin.second != 0
        or fin.microsecond != 0
        or fin <= inicio
        or fin.hour > HORA_FIN
    ):
        raise HTTPException(
            status_code=422,
            detail="La duración debe ser de horas consecutivas entre 07:00 y 16:00."
        )

    return hora_inicio, time(fin.hour)


def intervalos_se_solapan(
    inicio_a: time,
    fin_a: time,
    inicio_b: time,
    fin_b: time
) -> bool:
    return inicio_a < fin_b and fin_a > inicio_b


def serializar_reserva(fila) -> dict:
    return {
        "id": fila["id"],
        "laboratory_id": fila["laboratory_id"],
        "laboratory_name": fila["laboratory_name"],
        "reservation_date": fila["reservation_date"].isoformat(),
        "start_time": normalizar_hora(fila["start_time"]).strftime("%H:%M"),
        "end_time": normalizar_hora(fila["end_time"]).strftime("%H:%M"),
        "subject": fila["subject"],
        "teacher_name": fila["full_name"],
        "matricula": fila["teacher_id"],
        "teacher_user_id": fila["teacher_user_id"],
        "status": fila["status"]
    }


def bloquear_fecha(connection, laboratory_id: int, fecha: date) -> None:
    resultado = connection.execute(
        text("""
            DECLARE @lock_result INT;
            EXEC @lock_result = sys.sp_getapplock
                @Resource = :resource,
                @LockMode = 'Exclusive',
                @LockOwner = 'Transaction',
                @LockTimeout = 10000;
            SELECT @lock_result;
        """),
        {
            "resource": (
                f"LabMonitor:lab-reservations:"
                f"{laboratory_id}:{fecha:%Y%m%d}"
            )
        }
    ).scalar_one()
    if resultado < 0:
        raise HTTPException(
            status_code=503,
            detail="No se pudo confirmar la disponibilidad. Inténtalo nuevamente."
        )


def comprobar_sin_solapamiento(
    connection,
    laboratory_id: int,
    fecha: date,
    hora_inicio: time,
    hora_fin: time,
    excluir_id: int | None = None
) -> None:
    bloquear_fecha(connection, laboratory_id, fecha)
    conflicto = connection.execute(
        text("""
            SELECT TOP (1) id
            FROM dbo.lab_reservations
            WITH (UPDLOCK, HOLDLOCK, INDEX(UX_lab_reservations_slot))
            WHERE laboratory_id = :laboratory_id
              AND reservation_date = :reservation_date
              AND status = 'confirmed'
              AND start_time < :end_time
              AND end_time > :start_time
              AND (:exclude_id IS NULL OR id <> :exclude_id)
        """),
        {
            "laboratory_id": laboratory_id,
            "reservation_date": fecha,
            "start_time": hora_inicio,
            "end_time": hora_fin,
            "exclude_id": excluir_id
        }
    ).first()
    if conflicto is not None:
        raise HTTPException(
            status_code=409,
            detail="Ese horario se cruza con una reserva existente. Elige otro."
        )


def obtener_laboratorio(connection, laboratory_id: int) -> dict:
    laboratorio = connection.execute(
        text("""
            SELECT id, name
            FROM dbo.laboratories
            WHERE id = :laboratory_id
        """),
        {"laboratory_id": laboratory_id}
    ).mappings().first()
    if laboratorio is None:
        raise HTTPException(
            status_code=404,
            detail="No se encontró el laboratorio seleccionado."
        )
    return dict(laboratorio)


def obtener_docente_activo(connection, teacher_user_id: int) -> dict:
    docente = connection.execute(
        text("""
            SELECT id, full_name, teacher_id
            FROM dbo.users
            WHERE id = :user_id
              AND role = 'teacher'
              AND is_active = 1
              AND teacher_approved = 1
        """),
        {"user_id": teacher_user_id}
    ).mappings().first()
    if docente is None:
        raise HTTPException(
            status_code=404,
            detail="No se encontró un docente activo y autorizado."
        )
    return dict(docente)


def validar_horario_futuro(fecha: date, hora_inicio: time) -> None:
    ahora_local = datetime.now(ZONA_LOCAL)
    if (
        fecha == ahora_local.date()
        and hora_inicio <= ahora_local.time().replace(tzinfo=None)
    ):
        raise HTTPException(
            status_code=422,
            detail="No se pueden reservar horarios que ya comenzaron."
        )


def encolar_confirmacion(
    connection,
    reserva_id: int,
    docente: dict,
    fecha: date,
    hora_inicio: time,
    hora_fin: time,
    materia: str,
    creador: dict
) -> None:
    destinatarios = obtener_correos_administradores()
    if not destinatarios:
        raise HTTPException(
            status_code=503,
            detail=(
                "No hay correos administrativos configurados "
                "para recibir avisos de reservas."
            )
        )

    creado_por = (
        f"\nReservó: {creador['full_name']} ({creador['role']})"
        if creador["id"] != docente["id"]
        else ""
    )
    asunto = "[LabMonitor] Nueva reserva de laboratorio"
    mensaje = (
        "Se registró una reserva del laboratorio de cómputo.\n\n"
        f"Docente: {docente['full_name']}\n"
        f"Matrícula: {docente['teacher_id']}\n"
        f"Materia: {materia}\n"
        f"Fecha: {fecha.strftime('%d/%m/%Y')}\n"
        f"Horario: {hora_inicio:%H:%M} - {hora_fin:%H:%M}\n"
        f"Folio: {reserva_id}{creado_por}\n\n"
        "Departamento de Sistemas\n"
        "Universidad de Durango\n"
        "Campus Aguascalientes"
    )
    for destinatario in destinatarios:
        connection.execute(
            text("""
                INSERT INTO dbo.reservation_email_notifications (
                    reservation_id, recipient, subject, body
                )
                VALUES (
                    :reservation_id, :recipient, :subject, :body
                )
            """),
            {
                "reservation_id": reserva_id,
                "recipient": destinatario,
                "subject": asunto,
                "body": mensaje
            }
        )


@router.get("/reservations/availability")
def consultar_disponibilidad(
    fecha: date = Query(alias="date"),
    laboratory_id: int = Query(gt=0),
    exclude_id: int | None = Query(default=None, ge=1),
    usuario: dict = Depends(docentes_o_administradores)
):
    validar_fecha_reserva(fecha)
    with engine.connect() as connection:
        obtener_laboratorio(connection, laboratory_id)
        if exclude_id is not None:
            reserva = connection.execute(
                text("""
                    SELECT teacher_user_id, status
                    FROM dbo.lab_reservations
                    WHERE id = :reservation_id
                """),
                {"reservation_id": exclude_id}
            ).mappings().first()
            if (
                reserva is None
                or reserva["status"] != "confirmed"
                or (
                    usuario["role"] != "admin"
                    and reserva["teacher_user_id"] != usuario["id"]
                )
            ):
                raise HTTPException(
                    status_code=404,
                    detail="No se encontró una reserva activa que puedas modificar."
                )

        ocupados = connection.execute(
            text("""
                SELECT start_time, end_time
                FROM dbo.lab_reservations
                WHERE laboratory_id = :laboratory_id
                                    AND reservation_date = :reservation_date
                                    AND status = 'confirmed'
                                    AND (:exclude_id IS NULL OR id <> :exclude_id)
            """),
            {
                "laboratory_id": laboratory_id,
                "reservation_date": fecha,
                "exclude_id": exclude_id
            }
        ).mappings().all()

    hora_actual = None
    ahora_local = datetime.now(ZONA_LOCAL)
    if fecha == ahora_local.date():
        hora_actual = ahora_local.time().replace(tzinfo=None)
    return {
        "date": fecha.isoformat(),
        "laboratory_id": laboratory_id,
        "slots": [
            {
                "start_time": inicio.strftime("%H:%M"),
                "end_time": fin.strftime("%H:%M"),
                "available": (
                    not any(
                        intervalos_se_solapan(
                            inicio,
                            fin,
                            normalizar_hora(reserva["start_time"]),
                            normalizar_hora(reserva["end_time"])
                        )
                        for reserva in ocupados
                    )
                    and (hora_actual is None or inicio > hora_actual)
                )
            }
            for inicio, fin in horarios_disponibles()
        ]
    }


@router.get("/reservations/laboratories")
def listar_laboratorios_reservables(
    _usuario: dict = Depends(docentes_o_administradores)
):
    with engine.connect() as connection:
        laboratorios = connection.execute(
            text("""
                SELECT id, name
                FROM dbo.laboratories
                ORDER BY name, id
            """)
        ).mappings().all()
    return {
        "laboratories": [
            {"id": laboratorio["id"], "name": laboratorio["name"]}
            for laboratorio in laboratorios
        ]
    }


@router.get("/reservations")
def listar_reservas_docente(
    fecha_desde: date | None = Query(default=None, alias="from"),
    fecha_hasta: date | None = Query(default=None, alias="to"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    docente: dict = Depends(solo_docentes_aprobados)
):
    if fecha_desde and fecha_hasta and fecha_hasta < fecha_desde:
        raise HTTPException(
            status_code=422,
            detail="La fecha final debe ser igual o posterior a la inicial."
        )

    with engine.connect() as connection:
        filas = connection.execute(
            text("""
                  SELECT r.id, r.laboratory_id, l.name AS laboratory_name,
                      r.reservation_date, r.start_time, r.end_time,
                      r.subject, r.status, r.teacher_user_id,
                      u.full_name, u.teacher_id
                FROM dbo.lab_reservations AS r
                INNER JOIN dbo.users AS u ON u.id = r.teacher_user_id
                INNER JOIN dbo.laboratories AS l ON l.id = r.laboratory_id
                WHERE r.teacher_user_id = :teacher_user_id
                  AND (:date_from IS NULL OR r.reservation_date >= :date_from)
                  AND (:date_to IS NULL OR r.reservation_date <= :date_to)
                ORDER BY r.reservation_date, r.start_time, r.id
                OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
            """),
            {
                "teacher_user_id": docente["id"],
                "date_from": fecha_desde,
                "date_to": fecha_hasta,
                "offset": offset,
                "limit": limit
            }
        ).mappings().all()

    return {"reservations": [serializar_reserva(fila) for fila in filas]}


@router.post("/reservations", status_code=201)
def crear_reserva(
    datos: ReservaCrear,
    docente: dict = Depends(solo_docentes_aprobados)
):
    fecha = datos.reservation_date
    validar_fecha_reserva(fecha)
    hora_inicio, hora_fin = validar_intervalo_reserva(
        datos.start_time,
        datos.end_time
    )
    validar_horario_futuro(fecha, hora_inicio)
    try:
        with engine.begin() as connection:
            obtener_laboratorio(connection, datos.laboratory_id)
            reserva_id = insertar_reserva(
                connection,
                docente,
                datos.laboratory_id,
                fecha,
                hora_inicio,
                hora_fin,
                datos.subject.strip(),
                docente
            )
    except IntegrityError as error:
        if "UX_lab_reservations_slot" in str(error.orig):
            raise HTTPException(
                status_code=409,
                detail="Ese horario acaba de ser reservado. Elige otro."
            ) from error
        raise

    return {
        "id": reserva_id,
        "reservation_date": fecha.isoformat(),
        "start_time": hora_inicio.strftime("%H:%M"),
        "end_time": hora_fin.strftime("%H:%M"),
        "subject": datos.subject.strip(),
        "message": "Reserva creada correctamente."
    }


def insertar_reserva(
    connection,
    docente: dict,
    laboratory_id: int,
    fecha: date,
    hora_inicio: time,
    hora_fin: time,
    materia: str,
    creador: dict
) -> int:
    comprobar_sin_solapamiento(
        connection,
        laboratory_id,
        fecha,
        hora_inicio,
        hora_fin
    )
    reserva_id = connection.execute(
        text("""
            INSERT INTO dbo.lab_reservations (
                teacher_user_id, laboratory_id, reservation_date, start_time,
                end_time, subject, created_by_user_id
            )
            OUTPUT INSERTED.id
            VALUES (
                :teacher_user_id, :laboratory_id, :reservation_date, :start_time,
                :end_time, :subject, :created_by_user_id
            )
        """),
        {
            "teacher_user_id": docente["id"],
            "laboratory_id": laboratory_id,
            "reservation_date": fecha,
            "start_time": hora_inicio,
            "end_time": hora_fin,
            "subject": materia,
            "created_by_user_id": creador["id"]
        }
    ).scalar_one()
    encolar_confirmacion(
        connection,
        reserva_id,
        docente,
        fecha,
        hora_inicio,
        hora_fin,
        materia,
        creador
    )
    return reserva_id


def actualizar_reserva(
    connection,
    reserva_id: int,
    docente: dict,
    datos: ReservaActualizar,
    actor: dict,
    propietario_requerido: bool
) -> None:
    reserva = connection.execute(
        text("""
            SELECT teacher_user_id, status
            FROM dbo.lab_reservations WITH (UPDLOCK, HOLDLOCK)
            WHERE id = :reservation_id
        """),
        {"reservation_id": reserva_id}
    ).mappings().first()
    if (
        reserva is None
        or reserva["status"] != "confirmed"
        or (
            propietario_requerido
            and reserva["teacher_user_id"] != actor["id"]
        )
    ):
        raise HTTPException(
            status_code=404,
            detail="No se encontró una reserva activa que puedas modificar."
        )

    fecha = datos.reservation_date
    validar_fecha_reserva(fecha)
    hora_inicio, hora_fin = validar_intervalo_reserva(
        datos.start_time,
        datos.end_time
    )
    validar_horario_futuro(fecha, hora_inicio)
    obtener_laboratorio(connection, datos.laboratory_id)
    comprobar_sin_solapamiento(
        connection,
        datos.laboratory_id,
        fecha,
        hora_inicio,
        hora_fin,
        excluir_id=reserva_id
    )
    connection.execute(
        text("""
            UPDATE dbo.lab_reservations
            SET teacher_user_id = :teacher_user_id,
                laboratory_id = :laboratory_id,
                reservation_date = :reservation_date,
                start_time = :start_time,
                end_time = :end_time,
                subject = :subject,
                updated_at = SYSUTCDATETIME(),
                updated_by_user_id = :actor_id
            WHERE id = :reservation_id
              AND status = 'confirmed'
        """),
        {
            "reservation_id": reserva_id,
            "teacher_user_id": docente["id"],
            "laboratory_id": datos.laboratory_id,
            "reservation_date": fecha,
            "start_time": hora_inicio,
            "end_time": hora_fin,
            "subject": datos.subject.strip(),
            "actor_id": actor["id"]
        }
    )


def cancelar_reserva(
    connection,
    reserva_id: int,
    actor: dict,
    propietario_requerido: bool
) -> None:
    parametros = {"reservation_id": reserva_id, "actor_id": actor["id"]}
    filtro_propietario = ""
    if propietario_requerido:
        filtro_propietario = "AND teacher_user_id = :teacher_user_id"
        parametros["teacher_user_id"] = actor["id"]

    resultado = connection.execute(
        text(f"""
            UPDATE dbo.lab_reservations
            SET status = 'cancelled',
                updated_at = SYSUTCDATETIME(),
                updated_by_user_id = :actor_id
            OUTPUT INSERTED.id
            WHERE id = :reservation_id
              AND status = 'confirmed'
              {filtro_propietario}
        """),
        parametros
    ).first()
    if resultado is None:
        raise HTTPException(
            status_code=404,
            detail="No se encontró una reserva activa que puedas cancelar."
        )


@router.put("/reservations/{reserva_id}")
def modificar_reserva_docente(
    reserva_id: int,
    datos: ReservaActualizar,
    docente: dict = Depends(solo_docentes_aprobados)
):
    if reserva_id <= 0:
        raise HTTPException(status_code=400, detail="Identificador inválido.")
    try:
        with engine.begin() as connection:
            actualizar_reserva(
                connection,
                reserva_id,
                docente,
                datos,
                docente,
                propietario_requerido=True
            )
    except IntegrityError as error:
        if "UX_lab_reservations_slot" in str(error.orig):
            raise HTTPException(
                status_code=409,
                detail="Ese horario se cruza con otra reserva."
            ) from error
        raise
    return {"message": "Reserva modificada correctamente."}


@router.delete("/reservations/{reserva_id}")
def cancelar_reserva_docente(
    reserva_id: int,
    docente: dict = Depends(solo_docentes_aprobados)
):
    if reserva_id <= 0:
        raise HTTPException(status_code=400, detail="Identificador inválido.")
    with engine.begin() as connection:
        cancelar_reserva(
            connection,
            reserva_id,
            docente,
            propietario_requerido=True
        )
    return {"message": "Reserva cancelada. Se conservó en el historial."}


@router.get("/admin/reservations")
def listar_reservas_admin(
    fecha_desde: date | None = Query(default=None, alias="from"),
    fecha_hasta: date | None = Query(default=None, alias="to"),
    matricula: str | None = Query(default=None, max_length=50),
    estado: Literal["confirmed", "cancelled"] = Query(
        default="confirmed",
        alias="status"
    ),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _administrador: dict = Depends(solo_administradores)
):
    if fecha_desde and fecha_hasta and fecha_hasta < fecha_desde:
        raise HTTPException(
            status_code=422,
            detail="La fecha final debe ser igual o posterior a la inicial."
        )

    with engine.connect() as connection:
        filas = connection.execute(
            text("""
                  SELECT r.id, r.laboratory_id, l.name AS laboratory_name,
                      r.reservation_date, r.start_time, r.end_time,
                      r.subject, r.status, r.teacher_user_id,
                      u.full_name, u.teacher_id
                FROM dbo.lab_reservations AS r
                INNER JOIN dbo.users AS u ON u.id = r.teacher_user_id
                INNER JOIN dbo.laboratories AS l ON l.id = r.laboratory_id
                WHERE r.status = :status
                  AND (:date_from IS NULL OR r.reservation_date >= :date_from)
                  AND (:date_to IS NULL OR r.reservation_date <= :date_to)
                  AND (:teacher_id IS NULL OR u.teacher_id = :teacher_id)
                ORDER BY r.reservation_date, r.start_time, r.id
                OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
            """),
            {
                "date_from": fecha_desde,
                "date_to": fecha_hasta,
                "teacher_id": matricula.strip() if matricula else None,
                "status": estado,
                "offset": offset,
                "limit": limit
            }
        ).mappings().all()
        pendientes = connection.execute(
            text("""
                SELECT id, full_name, teacher_id, created_at
                FROM dbo.users
                WHERE role = 'teacher'
                  AND teacher_approved = 0
                  AND is_active = 1
                ORDER BY created_at, id
            """)
        ).mappings().all()
        docentes = connection.execute(
            text("""
                SELECT id, full_name, teacher_id
                FROM dbo.users
                WHERE role = 'teacher'
                  AND teacher_approved = 1
                  AND is_active = 1
                ORDER BY full_name, teacher_id
            """)
        ).mappings().all()
        laboratorios = connection.execute(
            text("""
                SELECT id, name
                FROM dbo.laboratories
                ORDER BY name, id
            """)
        ).mappings().all()

    return {
        "reservations": [serializar_reserva(fila) for fila in filas],
        "teachers": [
            {
                "id": fila["id"],
                "full_name": fila["full_name"],
                "matricula": fila["teacher_id"]
            }
            for fila in docentes
        ],
        "laboratories": [
            {"id": fila["id"], "name": fila["name"]}
            for fila in laboratorios
        ],
        "pending_teachers": [
            {
                "id": fila["id"],
                "full_name": fila["full_name"],
                "matricula": fila["teacher_id"],
                "created_at": fila["created_at"].isoformat()
                if fila["created_at"] else None
            }
            for fila in pendientes
        ]
    }


@router.post("/admin/reservations/teachers/{teacher_id}/approve")
def aprobar_docente(
    teacher_id: int,
    administrador: dict = Depends(solo_administradores)
):
    if teacher_id <= 0:
        raise HTTPException(status_code=400, detail="Identificador inválido.")

    with engine.begin() as connection:
        usuario = connection.execute(
            text("""
                UPDATE dbo.users
                SET teacher_approved = 1,
                    teacher_approved_by = :admin_id,
                    teacher_approved_at = SYSUTCDATETIME()
                OUTPUT INSERTED.id, INSERTED.full_name, INSERTED.teacher_id
                WHERE id = :teacher_id
                  AND role = 'teacher'
                  AND is_active = 1
                  AND teacher_approved = 0
            """),
            {"admin_id": administrador["id"], "teacher_id": teacher_id}
        ).mappings().first()

    if usuario is None:
        raise HTTPException(
            status_code=404,
            detail="No se encontró una cuenta docente pendiente."
        )

    return {
        "message": "Cuenta docente autorizada.",
        "teacher": {
            "id": usuario["id"],
            "full_name": usuario["full_name"],
            "matricula": usuario["teacher_id"]
        }
    }


@router.post("/admin/reservations", status_code=201)
def crear_reserva_administrativa(
    datos: ReservaAdministrativa,
    administrador: dict = Depends(solo_administradores)
):
    fecha = datos.reservation_date
    validar_fecha_reserva(fecha)
    hora_inicio, hora_fin = validar_intervalo_reserva(
        datos.start_time,
        datos.end_time
    )
    validar_horario_futuro(fecha, hora_inicio)
    try:
        with engine.begin() as connection:
            docente = obtener_docente_activo(connection, datos.teacher_user_id)
            obtener_laboratorio(connection, datos.laboratory_id)
            reserva_id = insertar_reserva(
                connection,
                docente,
                datos.laboratory_id,
                fecha,
                hora_inicio,
                hora_fin,
                datos.subject.strip(),
                administrador
            )
    except IntegrityError as error:
        if "UX_lab_reservations_slot" in str(error.orig):
            raise HTTPException(
                status_code=409,
                detail="Ese horario se cruza con otra reserva."
            ) from error
        raise

    return {
        "id": reserva_id,
        "message": "Reserva creada a nombre del docente."
    }


@router.post("/admin/reservations/recurring", status_code=201)
def crear_reservas_recurrentes_administrativas(
    datos: ReservaRecurrente,
    administrador: dict = Depends(solo_administradores)
):
    fechas_programadas = fechas_recurrentes(
        datos.start_date,
        datos.end_date,
        datos.weekdays
    )
    if not fechas_programadas:
        raise HTTPException(
            status_code=422,
            detail="El rango no contiene fechas para los días seleccionados."
        )
    hora_inicio, hora_fin = validar_intervalo_reserva(
        datos.start_time,
        datos.end_time
    )

    creadas = []
    conflictos = []
    try:
        with engine.begin() as connection:
            docente = obtener_docente_activo(connection, datos.teacher_user_id)
            obtener_laboratorio(connection, datos.laboratory_id)
            for fecha in fechas_programadas:
                validar_fecha_reserva(fecha)
                try:
                    validar_horario_futuro(fecha, hora_inicio)
                    reserva_id = insertar_reserva(
                        connection,
                        docente,
                        datos.laboratory_id,
                        fecha,
                        hora_inicio,
                        hora_fin,
                        datos.subject.strip(),
                        administrador
                    )
                    creadas.append({
                        "id": reserva_id,
                        "reservation_date": fecha.isoformat()
                    })
                except HTTPException as error:
                    if error.status_code != 409:
                        raise
                    conflictos.append(fecha.isoformat())
    except IntegrityError as error:
        if "UX_lab_reservations_slot" in str(error.orig):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Una fecha de la serie acaba de ser reservada. "
                    "No se guardó ninguna reserva de la serie."
                )
            ) from error
        raise

    if not creadas:
        raise HTTPException(
            status_code=409,
            detail=(
                "No se crearon reservas; todos los días seleccionados "
                "ya están ocupados."
            )
        )
    return {
        "created_count": len(creadas),
        "reservations": creadas,
        "conflicts": conflictos,
        "message": (
            f"Se crearon {len(creadas)} reservas."
            + (
                f" {len(conflictos)} fechas ocupadas se omitieron."
                if conflictos else ""
            )
        )
    }


@router.put("/admin/reservations/{reserva_id}")
def modificar_reserva_administrativa(
    reserva_id: int,
    datos: ReservaAdministrativa,
    administrador: dict = Depends(solo_administradores)
):
    if reserva_id <= 0:
        raise HTTPException(status_code=400, detail="Identificador inválido.")
    try:
        with engine.begin() as connection:
            docente = obtener_docente_activo(connection, datos.teacher_user_id)
            obtener_laboratorio(connection, datos.laboratory_id)
            actualizar_reserva(
                connection,
                reserva_id,
                docente,
                datos,
                administrador,
                propietario_requerido=False
            )
    except IntegrityError as error:
        if "UX_lab_reservations_slot" in str(error.orig):
            raise HTTPException(
                status_code=409,
                detail="Ese horario se cruza con otra reserva."
            ) from error
        raise
    return {"message": "Reserva modificada correctamente."}


@router.delete("/admin/reservations/{reserva_id}")
def cancelar_reserva_administrativa(
    reserva_id: int,
    administrador: dict = Depends(solo_administradores)
):
    if reserva_id <= 0:
        raise HTTPException(status_code=400, detail="Identificador inválido.")
    with engine.begin() as connection:
        cancelar_reserva(
            connection,
            reserva_id,
            administrador,
            propietario_requerido=False
        )
    return {"message": "Reserva cancelada. Se conservó en el historial."}