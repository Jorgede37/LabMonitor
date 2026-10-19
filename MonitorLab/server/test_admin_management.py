import unittest
from contextlib import contextmanager
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.routes import admin
from app.dependencies import solo_administradores


class FakeResult:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def first(self):
        return self.row

    def mappings(self):
        return self

    def one(self):
        return self.row

    def all(self):
        return self.rows


class FakeConnection:
    def __init__(self, existing=None):
        self.existing = existing
        self.statements = []
        self.created = {
            "id": 21,
            "full_name": "New Admin",
            "username": "new_admin",
            "email": "new.admin@gmail.com",
            "is_active": True,
            "created_at": None,
        }

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.statements.append((sql, parameters or {}))
        if "SELECT TOP 1 id" in sql:
            return FakeResult(row=self.existing)
        if "SELECT id, full_name, username, email, is_active, created_at" in sql:
            return FakeResult(rows=[self.created])
        if "INSERT INTO dbo.users" in sql:
            return FakeResult(row=self.created)
        raise AssertionError(f"Unexpected SQL: {sql}")


class FakeEngine:
    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def begin(self):
        yield self.connection

    @contextmanager
    def connect(self):
        yield self.connection


class AdministratorManagementTests(unittest.TestCase):
    def test_create_admin_hashes_password_and_sets_admin_role(self):
        connection = FakeConnection()
        data = admin.AdministradorCrear(
            full_name=" New Admin ",
            username=" new_admin ",
            email="NEW.ADMIN@gmail.com",
            password="not-a-stored-secret",
        )
        with patch.object(admin, "engine", FakeEngine(connection)), patch.object(
            admin, "generar_hash", return_value="argon-hash"
        ) as hash_password:
            result = admin.crear_administrador(data, {"username": "root"})

        self.assertEqual(result["administrator"]["id"], 21)
        self.assertEqual(result["administrator"]["email"], "new.admin@gmail.com")
        hash_password.assert_called_once_with("not-a-stored-secret")
        insert_sql, values = connection.statements[-1]
        self.assertIn("'admin'", insert_sql)
        self.assertIn("NULL, :email, 1", insert_sql)
        self.assertEqual(values["password_hash"], "argon-hash")
        self.assertNotIn("password", result)

    def test_list_admins_returns_public_account_fields(self):
        connection = FakeConnection()
        with patch.object(admin, "engine", FakeEngine(connection)):
            result = admin.listar_administradores({"username": "root"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["administrators"][0]["email"], "new.admin@gmail.com")
        self.assertNotIn("password_hash", result["administrators"][0])
        self.assertIn("WHERE role = 'admin'", connection.statements[0][0])

    def test_create_admin_rejects_existing_username_or_email(self):
        connection = FakeConnection(existing={"id": 3})
        data = admin.AdministradorCrear(
            full_name="New Admin",
            username="new_admin",
            email="new.admin@gmail.com",
            password="long-enough-password",
        )
        with patch.object(admin, "engine", FakeEngine(connection)):
            with self.assertRaises(HTTPException) as error:
                admin.crear_administrador(data, {"username": "root"})
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(len(connection.statements), 1)

    def test_create_admin_rejects_invalid_email(self):
        with self.assertRaises(ValidationError):
            admin.AdministradorCrear(
                full_name="New Admin",
                username="new_admin",
                email="not-an-email",
                password="long-enough-password",
            )

    def test_admin_endpoints_require_admin_dependency(self):
        for path in ("/admin/administrators",):
            route = next(route for route in admin.router.routes if route.path == path)
            self.assertIn(
                solo_administradores,
                [dependency.call for dependency in route.dependant.dependencies],
            )
        create_route = next(
            route for route in admin.router.routes
            if route.path == "/admin/administrators" and "POST" in route.methods
        )
        self.assertIn(
            solo_administradores,
            [dependency.call for dependency in create_route.dependant.dependencies],
        )


if __name__ == "__main__":
    unittest.main()
