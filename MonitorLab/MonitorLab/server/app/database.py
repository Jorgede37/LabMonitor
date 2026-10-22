import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

load_dotenv()

# Configuracion de SQL Server
SERVER = os.getenv("SQL_SERVER", "localhost")
DATABASE = os.getenv("SQL_DATABASE", "LabMonitor")

# Conexion mediante autenticacion de Windows
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