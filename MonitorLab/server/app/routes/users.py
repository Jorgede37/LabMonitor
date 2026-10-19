
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.database import engine
from app.security import generar_hash
from app.email_verification import emitir_codigo_verificacion


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
