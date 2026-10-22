import unittest
from contextlib import contextmanager
from unittest.mock import patch

from fastapi import HTTPException

from app.routes import admin, agent_routes


class FakeResult:
    def __init__(self, row=None):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row


class FakeConnection:
    def __init__(self, computer=None, laboratory=None, duplicate=None):
        self.computer = computer or {"id": 7}
        self.laboratory = laboratory
        self.duplicate = duplicate
        self.statements = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.statements.append((sql, parameters or {}))
        if "FROM dbo.laboratories" in sql:
            return FakeResult(self.laboratory)
        if "FROM dbo.computers AS c" in sql:
            return FakeResult(self.computer)
        if "AND display_name = :display_name" in sql:
            return FakeResult(self.duplicate)
        if "FROM dbo.computers WITH" in sql:
            return FakeResult(self.computer)
        if "FROM dbo.computers" in sql:
            return FakeResult(self.duplicate)
        return FakeResult()


class FakeEngine:
    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def begin(self):
        yield self.connection

    @contextmanager
    def connect(self):
        yield self.connection


class ComputerConfigurationTests(unittest.TestCase):
    def test_admin_can_clear_laboratory_assignment(self):
        connection = FakeConnection()

        with patch.object(admin, "engine", FakeEngine(connection)):
            result = admin.configurar_computadora(
                7,
                admin.ComputadoraConfigurar(
                    display_name="LAB-PC-07",
                    laboratory_id=None
                ),
                {"id": 1, "role": "admin"}
            )

        update_sql, parameters = connection.statements[-1]
        self.assertIn("laboratory_id = :laboratory_id", update_sql)
        self.assertIsNone(parameters["laboratory_id"])
        self.assertIsNone(parameters["lab"])
        self.assertIsNone(result["computer"]["laboratory_id"])
        self.assertIsNone(result["computer"]["lab"])
        self.assertFalse(any(
            "FROM dbo.laboratories" in sql
            for sql, _ in connection.statements
        ))

    def test_admin_can_assign_existing_laboratory(self):
        laboratory = {"id": 3, "name": "Laboratorio A"}
        connection = FakeConnection(laboratory=laboratory)

        with patch.object(admin, "engine", FakeEngine(connection)):
            result = admin.configurar_computadora(
                7,
                admin.ComputadoraConfigurar(
                    display_name="LAB-PC-07",
                    laboratory_id=3
                ),
                {"id": 1, "role": "admin"}
            )

        self.assertEqual(
            result["computer"]["laboratory_id"],
            laboratory["id"]
        )
        self.assertEqual(result["computer"]["lab"], laboratory["name"])
        self.assertEqual(
            connection.statements[-1][1]["laboratory_id"],
            laboratory["id"]
        )

    def test_admin_cannot_assign_unknown_laboratory(self):
        connection = FakeConnection()

        with patch.object(admin, "engine", FakeEngine(connection)):
            with self.assertRaises(HTTPException) as error:
                admin.configurar_computadora(
                    7,
                    admin.ComputadoraConfigurar(
                        display_name="LAB-PC-07",
                        laboratory_id=44
                    ),
                    {"id": 1, "role": "admin"}
                )

        self.assertEqual(error.exception.status_code, 404)
        self.assertFalse(any(
            "UPDATE dbo.computers" in sql
            for sql, _ in connection.statements
        ))

    def test_agent_configuration_is_complete_when_laboratory_is_unassigned(self):
        computer = {
            "id": 7,
            "hostname": "HOST-07",
            "display_name": "LAB-PC-07",
            "laboratory_id": None,
            "laboratory_name": None,
        }
        connection = FakeConnection(computer=computer)

        with patch.object(agent_routes, "engine", FakeEngine(connection)):
            result = agent_routes.consultar_configuracion_agente(
                {"computer_id": 7}
            )

        self.assertTrue(result["configured"])
        self.assertIsNone(result["laboratory_id"])
        self.assertIsNone(result["laboratory_name"])


if __name__ == "__main__":
    unittest.main()
