
import getpass

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.database import engine
from app.security import generar_hash


def crear_administrador():
    print("=== Crear administrador de LabMonitor ===")

    username = input("Nombre de usuario: ").strip()
    full_name = input("Nombre completo: ").strip()

    password = getpass.getpass("Contraseña: ")
    confirm_password = getpass.getpass("Confirmar contraseña: ")

    if not username or not full_name:
        print("El usuario y el nombre son obligatorios.")
        return

    if len(username) > 50 or len(full_name) > 150:
        print("El usuario o el nombre exceden la longitud permitida.")
        return

    if len(password) < 12:
        print("La contraseña debe tener al menos 12 caracteres.")
        return

    if password != confirm_password:
        print("Las contraseñas no coinciden.")
        return

    password_hash = generar_hash(password)

    try:
        with engine.begin() as connection:
            resultado = connection.execute(
                text("""
                    INSERT INTO dbo.users (
                        username,
                        password_hash,
                        role,
                        full_name,
                        student_id
                    )
                    OUTPUT INSERTED.id
                    VALUES (
                        :username,
                        :password_hash,
                        'admin',
                        :full_name,
                        NULL
                    )
                """),
                {
                    "username": username,
                    "password_hash": password_hash,
                    "full_name": full_name
                }
            )

            user_id = resultado.scalar_one()

        print(f"\nAdministrador creado correctamente. ID: {user_id}")

    except IntegrityError:
        print("No se pudo crear el administrador.")
        print("Comprueba si el nombre de usuario ya existe.")


if __name__ == "__main__":
    crear_administrador()
