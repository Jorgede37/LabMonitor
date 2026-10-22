import unittest
from contextlib import contextmanager
from unittest.mock import patch

from fastapi import HTTPException

from app.dependencies import solo_administradores
from app.routes import admin


class FakeResult:
    def __init__(self, row=None, scalar=0):
        self.row = row
        self.scalar = scalar

    def mappings(self):
        return self

    def first(self):
        return self.row

    def scalar_one(self):
        return self.scalar


class FakeConnection:
    def __init__(self, account=None, active_admins=1):
        self.account = account
        self.active_admins = active_admins
        self.statements = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.statements.append((sql, parameters or {}))
        if "SELECT id, role, email, is_active" in sql:
            return FakeResult(row=self.account)
        if "AND id <> :user_id" in sql and "role = 'admin'" in sql:
            return FakeResult(scalar=self.active_admins)
        return FakeResult()


class FakeEngine:
    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def begin(self):
        yield self.connection


class PermanentAccountDeletionTests(unittest.TestCase):
    def test_student_deletion_anonymizes_history_before_deleting_account(self):
        connection = FakeConnection(
            account={
                "id": 8,
                "role": "student",
                "email": "student@example.com",
                "is_active": True,
            }
        )

        with patch.object(admin, "engine", FakeEngine(connection)):
            result = admin.eliminar_estudiante_permanentemente(
                8,
                {"id": 1}
            )

        sql_statements = [sql for sql, _ in connection.statements]
        self.assertIn("eliminado permanentemente", result["message"])
        self.assertTrue(any("UPDATE dbo.hardware_events" in sql for sql in sql_statements))
        self.assertTrue(any("UPDATE dbo.sessions" in sql for sql in sql_statements))
        self.assertTrue(any("UPDATE dbo.audit_logs" in sql for sql in sql_statements))
        self.assertTrue(any("UPDATE dbo.email_notifications" in sql for sql in sql_statements))
        self.assertLess(
            next(i for i, sql in enumerate(sql_statements) if "UPDATE dbo.sessions" in sql),
            next(i for i, sql in enumerate(sql_statements) if "DELETE FROM dbo.users" in sql)
        )

    def test_admin_cannot_delete_self(self):
        connection = FakeConnection()

        with patch.object(admin, "engine", FakeEngine(connection)):
            with self.assertRaises(HTTPException) as error:
                admin.eliminar_administrador_permanentemente(1, {"id": 1})

        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(connection.statements, [])

    def test_cannot_delete_last_active_admin(self):
        connection = FakeConnection(
            account={
                "id": 8,
                "role": "admin",
                "email": "admin@example.com",
                "is_active": True,
            },
            active_admins=0,
        )

        with patch.object(admin, "engine", FakeEngine(connection)):
            with self.assertRaises(HTTPException) as error:
                admin.eliminar_administrador_permanentemente(8, {"id": 1})

        self.assertEqual(error.exception.status_code, 409)
        self.assertFalse(
            any("DELETE FROM dbo.users" in sql for sql, _ in connection.statements)
        )

    def test_permanent_delete_routes_require_admin_dependency(self):
        paths = {
            "/admin/administrators/{user_id}/permanent",
            "/admin/students/{user_id}/permanent",
        }
        for route in admin.router.routes:
            if route.path in paths:
                self.assertIn(
                    solo_administradores,
                    [dependency.call for dependency in route.dependant.dependencies],
                )
