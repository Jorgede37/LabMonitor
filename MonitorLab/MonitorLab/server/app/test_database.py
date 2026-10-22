
from sqlalchemy import text
from app.database import engine


def verificar_tablas():
    tablas_esperadas = [
        "users",
        "computers",
        "hardware_components",
        "sessions",
        "hardware_events",
        "audit_logs"
    ]

    try:
        with engine.connect() as connection:
            print("Verificando base de datos LabMonitor...\n")

            resultado = connection.execute(
                text("""
                    SELECT TABLE_NAME
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_SCHEMA = 'dbo'
                      AND TABLE_TYPE = 'BASE TABLE'
                """)
            )

            tablas_encontradas = {
                fila[0] for fila in resultado
            }

            for tabla in tablas_esperadas:
                if tabla in tablas_encontradas:
                    print(f"[OK] {tabla}")
                else:
                    print(f"[ERROR] No se encontró: {tabla}")

            if all(
                tabla in tablas_encontradas
                for tabla in tablas_esperadas
            ):
                print("\nTodas las tablas están disponibles.")
            else:
                print("\nFaltan tablas en la base de datos.")

    except Exception as error:
        print(f"Error al consultar SQL Server: {error}")


if __name__ == "__main__":
    verificar_tablas()
