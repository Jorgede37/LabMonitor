
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

# Configuración de SQL Server
SERVER = r"localhost"
DATABASE = "LabMonitor"

# Conexión mediante autenticación de Windows
connection_url = URL.create(
    "mssql+pyodbc",
    query={
        "odbc_connect": (
            "DRIVER={ODBC Driver 17 for SQL Server};"
            f"SERVER={SERVER};"
            f"DATABASE={DATABASE};"
            "Trusted_Connection=yes;"
        )
    }
)

engine = create_engine(connection_url)


def probar_conexion():
    try:
        with engine.connect() as connection:
            resultado = connection.execute(
                text("SELECT DB_NAME() AS base_datos")
            )

            nombre_bd = resultado.scalar()

            print("Conexión exitosa a SQL Server")
            print(f"Base de datos: {nombre_bd}")

    except Exception as error:
        print("Error al conectar con SQL Server:")
        print(error)


if __name__ == "__main__":
    probar_conexion()
