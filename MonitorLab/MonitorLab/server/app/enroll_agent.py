
import hashlib
import secrets

from sqlalchemy import text
from app.database import engine


def crear_credencial():
    computer_id = int(input("ID de computadora: "))

    token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    with engine.begin() as connection:
        computadora = connection.execute(
            text("""
                SELECT id, hostname
                FROM dbo.computers
                WHERE id = :computer_id
            """),
            {"computer_id": computer_id}
        ).mappings().first()

        if computadora is None:
            print("La computadora no existe.")
            return

        existente = connection.execute(
            text("""
                SELECT id
                FROM dbo.agent_credentials
                WHERE computer_id = :computer_id
            """),
            {"computer_id": computer_id}
        ).first()

        if existente:
            print("Esta computadora ya tiene una credencial.")
            return

        connection.execute(
            text("""
                INSERT INTO dbo.agent_credentials (
                    computer_id,
                    token_hash
                )
                VALUES (
                    :computer_id,
                    :token_hash
                )
            """),
            {
                "computer_id": computer_id,
                "token_hash": token_hash
            }
        )

    print("\nCredencial generada correctamente.")
    print("Computadora:", computadora["hostname"])
    print("Token:", token)
    print("\nGuarda el token en un lugar seguro.")
    print("No se podrá recuperar después.")


if __name__ == "__main__":
    crear_credencial()
