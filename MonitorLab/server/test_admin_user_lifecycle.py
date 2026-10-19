import unittest
from contextlib import contextmanager
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.dependencies import solo_administradores
from app.routes import admin


class FakeResult:
    def __init__(self, row=None, rows=None, scalar=0):
        self.row = row
        self.rows = rows or []
        self.scalar = scalar

    def mappings(self):
        return self

    def first(self):
        return self.row

    def one(self):
        return self.row

    def all(self):
        return self.rows

    def scalar_one(self):
        return self.scalar


class FakeConnection:
    def __init__(
        self,
        user_row=None,
        duplicate=None,
        active_admins=2,
        output_row=None
    ):
        self.user_row = user_row
        self.duplicate = duplicate
        self.active_admins = active_admins
        self.output_row = output_row or {
            "id": 12,
            "full_name": "Cuenta actualizada",
            "username": "new_user",
            "student_id": "1234567890",
            "email": "user@gmail.com",
            "is_active": True,
            "created_at": None,
        }
        self.statements = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.statements.append((sql, parameters or {}))

        if "UPDATE dbo.users" in sql:
            return FakeResult(row=self.output_row)
        if "SELECT id, is_active" in sql:
            return FakeResult(row=self.user_row)
        if "SELECT COUNT(*)" in sql:
            return FakeResult(scalar=self.active_admins)
        if "SELECT TOP 1 id" in sql:
            return FakeResult(row=self.duplicate)
        if "SELECT id" in sql and "role = 'student'" in sql:
            return FakeResult(row=self.user_row)
        if "SELECT id" in sql and "role = 'admin'" in sql:
            return FakeResult(row=self.user_row)
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


class AdminAccountLifecycleTests(unittest.TestCase):
    def test_admin_edit_hashes_optional_password_and_updates_fields(self):
        connection = FakeConnection(user_row={"id": 12, "is_active": True})
        data = admin.AdministradorActualizar(
            full_name="Cuenta actualizada",
            username="new_user",
            email="USER@gmail.com",
            password="password-seguro",
            is_active=True
        )

        with patch.object(admin, "engine", FakeEngine(connection)), patch.object(
            admin,
            "generar_hash",
            return_value="secure-hash"
        ) as generar_hash:
            result = admin.actualizar_administrador(
                12,
                data,
                {"id": 2, "username": "root"}
            )

        update_sql, params = next(
            (sql, params)
            for sql, params in connection.statements
            if "UPDATE dbo.users" in sql
        )
        self.assertIn("password_hash = :password_hash", update_sql)
        self.assertEqual(params["password_hash"], "secure-hash")
        self.assertEqual(params["email"], "user@gmail.com")
        self.assertEqual(result["administrator"]["id"], 12)
        generar_hash.assert_called_once_with("password-seguro")

    def test_admin_cannot_deactivate_own_account(self):
        data = admin.AdministradorActualizar(
            full_name="Admin",
            username="admin",
            email="admin@gmail.com",
            is_active=False
        )
        with self.assertRaises(HTTPException) as error:
            admin.actualizar_administrador(
                8,
                data,
                {"id": 8, "username": "admin"}
            )
        self.assertEqual(error.exception.status_code, 409)

    def test_last_active_admin_cannot_be_deactivated(self):
        connection = FakeConnection(
            user_row={"id": 12, "is_active": True},
            active_admins=1
        )
        data = admin.AdministradorActualizar(
            full_name="Other Admin",
            username="other",
            email="other@gmail.com",
            is_active=False
        )
        with patch.object(admin, "engine", FakeEngine(connection)):
            with self.assertRaises(HTTPException) as error:
                admin.actualizar_administrador(
                    12,
                    data,
                    {"id": 2, "username": "root"}
                )
        self.assertEqual(error.exception.status_code, 409)
        self.assertFalse(any(
            "UPDATE dbo.users" in sql
            for sql, _ in connection.statements
        ))

    def test_student_edit_updates_username_and_student_id_together(self):
        connection = FakeConnection(
            user_row={
                "id": 12,
                "email": "student@gmail.com",
                "email_verified": True
            },
            output_row={
                "id": 12,
                "full_name": "Estudiante",
                "username": "1234567890",
                "student_id": "1234567890",
                "email": "student@gmail.com",
                "is_active": True,
                "created_at": None,
            }
        )
        data = admin.EstudianteActualizar(
            full_name="Estudiante",
            student_id="1234567890",
            email="STUDENT@gmail.com",
            is_active=True
        )
        with patch.object(admin, "engine", FakeEngine(connection)):
            result = admin.actualizar_estudiante(
                12,
                data,
                {"id": 2, "username": "root"}
            )

        update_sql, params = next(
            (sql, params)
            for sql, params in connection.statements
            if "UPDATE dbo.users" in sql
        )
        self.assertIn("username = :student_id", update_sql)
        self.assertIn("student_id = :student_id", update_sql)
        self.assertEqual(params["student_id"], "1234567890")
        self.assertEqual(result["student"]["email"], "student@gmail.com")

    def test_changing_student_email_requires_new_verification(self):
        connection = FakeConnection(
            user_row={
                "id": 12,
                "full_name": "Estudiante",
                "email": "old.student@gmail.com",
                "email_verified": True
            },
            output_row={
                "id": 12,
                "full_name": "Estudiante",
                "username": "1234567890",
                "student_id": "1234567890",
                "email": "new.student@gmail.com",
                "email_verified": True,
                "is_active": True,
                "created_at": None,
            }
        )
        data = admin.EstudianteActualizar(
            full_name="Estudiante",
            student_id="1234567890",
            email="new.student@gmail.com",
            is_active=True
        )
        with patch.object(admin, "engine", FakeEngine(connection)), patch.object(
            admin,
            "emitir_codigo_verificacion"
        ) as send_code:
            result = admin.actualizar_estudiante(
                12,
                data,
                {"id": 2, "username": "root"}
            )

        send_code.assert_called_once_with(
            connection,
            12,
            "new.student@gmail.com",
            "Estudiante"
        )
        self.assertFalse(result["student"]["email_verified"])

    def test_deactivating_accounts_is_a_soft_delete(self):
        connection = FakeConnection(
            user_row={"id": 12},
            output_row={"id": 12}
        )
        with patch.object(admin, "engine", FakeEngine(connection)):
            result = admin.desactivar_estudiante(
                12,
                {"id": 2, "username": "root"}
            )

        update_sql, _ = next(
            (sql, params)
            for sql, params in connection.statements
            if "UPDATE dbo.users" in sql
        )
        self.assertIn("SET is_active = 0", update_sql)
        self.assertNotIn("DELETE FROM", update_sql)
        self.assertIn("conservó su historial", result["message"])

    def test_admin_deactivation_keeps_one_active_admin_and_preserves_history(self):
        connection = FakeConnection(
            user_row={"id": 12},
            active_admins=2,
            output_row={"id": 12}
        )
        with patch.object(admin, "engine", FakeEngine(connection)):
            result = admin.desactivar_administrador(
                12,
                {"id": 2, "username": "root"}
            )

        update_sql, _ = next(
            (sql, params)
            for sql, params in connection.statements
            if "UPDATE dbo.users" in sql
        )
        self.assertIn("SET is_active = 0", update_sql)
        self.assertIn("COUNT(*)", update_sql)
        self.assertIn("conservó su historial", result["message"])

    def test_invalid_student_id_is_rejected(self):
        with self.assertRaises(ValidationError):
            admin.EstudianteActualizar(
                full_name="Estudiante",
                student_id="123",
                email="student@gmail.com",
                is_active=True
            )

    def test_student_management_routes_require_admin(self):
        for path in (
            "/admin/students",
            "/admin/students/{user_id}",
        ):
            route = next(
                route
                for route in admin.router.routes
                if route.path == path
            )
            self.assertIn(
                solo_administradores,
                [dependency.call for dependency in route.dependant.dependencies]
            )


if __name__ == "__main__":
    unittest.main()
