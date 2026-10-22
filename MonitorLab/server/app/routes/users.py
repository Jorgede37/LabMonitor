
import hashlib
import re
import secrets

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.database import engine
from app.security import generar_hash
from app.email_verification import emitir_codigo_verificacion
from app.email_service import (
    obtener_administradores_con_correo,
    obtener_url_dashboard
)


router = APIRouter(prefix="/users", tags=["Usuarios"])


class RegistroAlumno(BaseModel):
    student_id: str = Field(
        min_length=10,
        max_length=10
    )

    full_name: str = Field(
        min_length=1,
        max_length=150
    )

    email: EmailStr

    password: str = Field(
        min_length=8,
        max_length=128
    )

    @field_validator("student_id")
    @classmethod
    def validar_matricula(cls, valor):
        if not re.fullmatch(r"[0-9]{10}", valor):
            raise ValueError(
                "La matrícula debe contener exactamente 10 dígitos"
            )
        return valor

    @field_validator("full_name")
    @classmethod
    def validar_nombre(cls, valor):
        valor = valor.strip()
        if not valor:
            raise ValueError(
                "El nombre completo no puede estar vacío"
            )
        return valor


class RegistroDocente(BaseModel):
    matricula: str = Field(min_length=1, max_length=50)
    full_name: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("matricula", "full_name")
    @classmethod
    def validar_texto_requerido(cls, valor):
        valor = valor.strip()
        if not valor:
            raise ValueError("Este campo es obligatorio")
        return valor

@router.post("/register", status_code=201)
def registrar_alumno(datos: RegistroAlumno):

    matricula = datos.student_id
    correo = str(datos.email).strip().lower()
    nombre = datos.full_name

    hash_contrasena = generar_hash(datos.password)

    try:
        with engine.begin() as connection:

            # Verificar matrícula y correo existentes.
            resultado = connection.execute(
                text("""
                    SELECT
                        student_id,
                        email
                    FROM dbo.users
                    WHERE LOWER(username) = LOWER(:matricula)
                       OR student_id = :matricula
                       OR LOWER(email) = :email
                """),
                {
                    "matricula": matricula,
                    "email": correo
                }
            )

            existente = resultado.mappings().first()

            if existente is not None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "La matrícula o el correo electrónico "
                        "ya están registrados"
                    )
                )

            # Registrar estudiante.
            resultado = connection.execute(
                text("""
                    INSERT INTO dbo.users (
                        username,
                        password_hash,
                        role,
                        full_name,
                        student_id,
                        email,
                        email_verified
                    )
                    OUTPUT INSERTED.id
                    VALUES (
                        :username,
                        :password_hash,
                        'student',
                        :full_name,
                        :student_id,
                        :email,
                        0
                    )
                """),
                {
                    "username": matricula,
                    "password_hash": hash_contrasena,
                    "full_name": nombre,
                    "student_id": matricula,
                    "email": correo
                }
            )

            nuevo_id = resultado.scalar_one()

            emitir_codigo_verificacion(
                connection,
                nuevo_id,
                correo,
                nombre
            )

        return {
            "message": (
                "Cuenta creada. Se envió un código de seguridad "
                "al correo registrado; ingrésalo en LabMonitor "
                "antes de iniciar sesión."
            ),
            "user_id": nuevo_id,
            "username": matricula,
            "student_id": matricula,
            "email": correo,
            "role": "student"
        }

    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=(
                "No fue posible registrar al alumno. "
                "Verifica que la matrícula y el correo "
                "no estén registrados."
            )
        )


@router.post("/teachers/register", status_code=201)
def registrar_docente(datos: RegistroDocente):
    matricula = datos.matricula
    nombre = datos.full_name
    hash_contrasena = generar_hash(datos.password)
    administradores = obtener_administradores_con_correo()
    if not administradores:
        raise HTTPException(
            status_code=503,
            detail="No hay administradores con correo configurado para autorizar cuentas."
        )

    try:
        with engine.begin() as connection:
            existente = connection.execute(
                text("""
                    SELECT TOP 1 id
                    FROM dbo.users WITH (UPDLOCK, HOLDLOCK)
                    WHERE LOWER(LTRIM(RTRIM(username))) =
                              LOWER(LTRIM(RTRIM(:matricula)))
                       OR teacher_id = :matricula
                """),
                {"matricula": matricula}
            ).first()

            if existente is not None:
                raise HTTPException(
                    status_code=409,
                    detail="La matrícula ya está registrada."
                )

            user_id = connection.execute(
                text("""
                    INSERT INTO dbo.users (
                        username, password_hash, role, full_name,
                        teacher_id, email, email_verified, teacher_approved
                    )
                    OUTPUT INSERTED.id
                    VALUES (
                        :matricula, :password_hash, 'teacher', :full_name,
                        :matricula, NULL, 1, 0
                    )
                """),
                {
                    "matricula": matricula,
                    "password_hash": hash_contrasena,
                    "full_name": nombre
                }
            ).scalar_one()

            base_dashboard = obtener_url_dashboard()
            for administrador in administradores:
                token_aprobacion = secrets.token_urlsafe(32)
                token_hash = hashlib.sha256(
                    token_aprobacion.encode("ascii")
                ).hexdigest()
                enlace = (
                    f"{base_dashboard}/teacher-approval"
                    f"#token={token_aprobacion}"
                )
                asunto = "[LabMonitor] Solicitud de cuenta docente"
                mensaje = (
                    "Se solicitó una nueva cuenta para reservar el laboratorio.\n\n"
                    f"Nombre: {nombre}\n"
                    f"Matrícula: {matricula}\n\n"
                    "Para revisar y autorizar esta cuenta, abre el enlace y confirma:\n"
                    f"{enlace}\n\n"
                    "El enlace es personal, de un solo uso y vence en 48 horas.\n\n"
                    "Departamento de Sistemas\n"
                    "Universidad de Durango\n"
                    "Campus Aguascalientes"
                )
                connection.execute(
                    text("""
                        INSERT INTO dbo.teacher_approval_tokens (
                            teacher_user_id,
                            administrator_user_id,
                            token_hash,
                            expires_at
                        )
                        VALUES (
                            :teacher_user_id,
                            :administrator_user_id,
                            :token_hash,
                            DATEADD(HOUR, 48, SYSUTCDATETIME())
                        )
                    """),
                    {
                        "teacher_user_id": user_id,
                        "administrator_user_id": administrador["id"],
                        "token_hash": token_hash
                    }
                )
                connection.execute(
                    text("""
                        INSERT INTO dbo.teacher_approval_email_notifications (
                            teacher_user_id, administrator_user_id, recipient,
                            subject, body
                        )
                        VALUES (
                            :teacher_user_id, :administrator_user_id,
                            :recipient, :subject, :body
                        )
                    """),
                    {
                        "teacher_user_id": user_id,
                        "administrator_user_id": administrador["id"],
                        "recipient": administrador["email"],
                        "subject": asunto,
                        "body": mensaje
                    }
                )

        return {
            "message": (
                "Cuenta creada. Se envió una solicitud de autorización "
                "a los administradores. No podrás reservar hasta que la aprueben."
            ),
            "user_id": user_id,
            "username": matricula,
            "role": "teacher",
            "approved": False
        }

    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="La matrícula ya está registrada."
        )
