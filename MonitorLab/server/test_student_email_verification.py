import hashlib
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from fastapi import HTTPException

from app.email_verification import emitir_codigo_verificacion
from app.routes import admin, auth, users


class FakeResult:
    def __init__(self, row=None, scalar=None):
        self.row = row
        self.scalar = scalar

    def mappings(self):
        return self

    def first(self):
        return self.row

    def one(self):
        return self.row

    def scalar_one(self):
        return self.scalar


class FakeConnection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.statements = []

    def execute(self, statement, parameters=None):
        self.statements.append((str(statement), parameters or {}))
        if self.rows:
            return FakeResult(row=self.rows.pop(0))
        return FakeResult(scalar=37)


class FakeEngine:
    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def begin(self):
        yield self.connection

    @contextmanager
    def connect(self):
        yield self.connection


class EmailVerificationTests(unittest.TestCase):
    def test_issue_email_code_stores_only_hash_and_sends_plain_code(self):
        connection = FakeConnection()
        with patch(
            "app.email_verification.secrets.randbelow",
            return_value=42
        ), patch(
            "app.email_verification.enviar_codigo_verificacion"
        ) as send:
            emitir_codigo_verificacion(
                connection,
                7,
                "student@example.com",
                "Student Name"
            )

        sql, parameters = connection.statements[0]
        self.assertIn("email_verified = 0", sql)
        self.assertEqual(
            parameters["code_hash"],
            hashlib.sha256(b"000042").hexdigest()
        )
        send.assert_called_once_with(
            destinatario="student@example.com",
            nombre="Student Name",
            codigo="000042"
        )
        self.assertNotIn("000042", str(parameters))

    def test_student_login_is_blocked_until_email_is_verified(self):
        connection = FakeConnection(rows=[{
            "id": 12,
            "username": "1234567890",
            "password_hash": "stored-hash",
            "role": "student",
            "full_name": "Student",
            "is_active": True,
            "email_verified": False
        }])
        with patch.object(auth, "engine", FakeEngine(connection)), patch.object(
            auth,
            "verificar_contrasena",
            return_value=True
        ):
            with self.assertRaises(HTTPException) as error:
                auth.iniciar_sesion(
                    auth.LoginRequest(
                        username="1234567890",
                        password="password"
                    )
                )

        self.assertEqual(error.exception.status_code, 403)

    def test_admin_login_is_not_subject_to_student_verification(self):
        connection = FakeConnection(rows=[{
            "id": 3,
            "username": "admin",
            "password_hash": "stored-hash",
            "role": "admin",
            "full_name": "Administrator",
            "is_active": True,
            "email_verified": False
        }])
        with patch.object(auth, "engine", FakeEngine(connection)), patch.object(
            auth,
            "verificar_contrasena",
            return_value=True
        ), patch.object(auth, "crear_token", return_value="admin-token"):
            result = auth.iniciar_sesion(
                auth.LoginRequest(username="admin", password="password")
            )

        self.assertEqual(result["access_token"], "admin-token")
        self.assertEqual(result["user"]["role"], "admin")

    def test_correct_code_verifies_student_email_once(self):
        code = "104283"
        connection = FakeConnection(rows=[{
            "id": 12,
            "email_verified": False,
            "email_verification_code_hash":
                hashlib.sha256(code.encode("ascii")).hexdigest(),
            "email_verification_attempts": 0,
            "code_is_valid": True
        }])
        with patch.object(auth, "engine", FakeEngine(connection)):
            result = auth.verificar_correo(
                auth.VerificationCodeRequest(
                    username="1234567890",
                    code=code
                )
            )

        self.assertIn("Correo verificado", result["message"])
        self.assertIn(
            "email_verified = 1",
            connection.statements[1][0]
        )
        self.assertEqual(
            connection.statements[1][1]["user_id"],
            12
        )

    def test_incorrect_code_increments_attempt_counter(self):
        connection = FakeConnection(rows=[{
            "id": 12,
            "email_verified": False,
            "email_verification_code_hash": "wrong-hash",
            "email_verification_attempts": 0,
            "code_is_valid": True
        }])
        with patch.object(auth, "engine", FakeEngine(connection)):
            with self.assertRaises(HTTPException) as error:
                auth.verificar_correo(
                    auth.VerificationCodeRequest(
                        username="1234567890",
                        code="104283"
                    )
                )

        self.assertEqual(error.exception.status_code, 400)
        self.assertIn(
            "email_verification_attempts =",
            connection.statements[1][0]
        )

    def test_admin_student_creation_sends_verification(self):
        connection = FakeConnection(rows=[None, {
            "id": 37,
            "full_name": "Student",
            "username": "1234567890",
            "student_id": "1234567890",
            "email": "student@example.com",
            "email_verified": False,
            "is_active": True,
            "created_at": None
        }])
        data = admin.EstudianteCrear(
            full_name="Student",
            student_id="1234567890",
            email="STUDENT@example.com",
            password="valid-password"
        )
        with patch.object(admin, "engine", FakeEngine(connection)), patch.object(
            admin,
            "generar_hash",
            return_value="password-hash"
        ), patch.object(admin, "emitir_codigo_verificacion") as send_code:
            result = admin.crear_estudiante(
                data,
                {"id": 1, "username": "admin"}
            )

        insert_sql, insert_parameters = connection.statements[1]
        self.assertIn("'student'", insert_sql)
        self.assertIn("email_verified", insert_sql)
        self.assertEqual(insert_parameters["email"], "student@example.com")
        send_code.assert_called_once_with(
            connection,
            37,
            "student@example.com",
            "Student"
        )
        self.assertFalse(result["student"]["email_verified"])

    def test_laboratory_names_are_rejected_case_insensitively(self):
        connection = FakeConnection(rows=[{"id": 1}])
        data = admin.LaboratorioCrear(name=" laboratorio A ")
        with patch.object(admin, "engine", FakeEngine(connection)):
            with self.assertRaises(HTTPException) as error:
                admin.crear_laboratorio(
                    data,
                    {"id": 1, "username": "admin"}
                )

        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(len(connection.statements), 1)

    def test_new_laboratory_is_still_allowed(self):
        connection = FakeConnection(rows=[None, {
            "id": 2,
            "name": "Laboratorio nuevo",
            "created_at": None
        }])
        data = admin.LaboratorioCrear(name="Laboratorio nuevo")
        with patch.object(admin, "engine", FakeEngine(connection)):
            result = admin.crear_laboratorio(
                data,
                {"id": 1, "username": "admin"}
            )

        self.assertEqual(
            result["laboratory"]["name"],
            "Laboratorio nuevo"
        )
        self.assertEqual(len(connection.statements), 2)

    def test_self_registration_sends_verification_code(self):
        connection = FakeConnection(rows=[None])
        connection.execute = self_registration_execute(connection)
        data = users.RegistroAlumno(
            student_id="1234567890",
            full_name="Student",
            email="STUDENT@example.com",
            password="valid-password"
        )
        with patch.object(users, "engine", FakeEngine(connection)), patch.object(
            users,
            "generar_hash",
            return_value="password-hash"
        ), patch.object(users, "emitir_codigo_verificacion") as send_code:
            result = users.registrar_alumno(data)

        self.assertIn("código de seguridad", result["message"])
        send_code.assert_called_once_with(
            connection,
            37,
            "student@example.com",
            "Student"
        )

    def test_self_registration_rejects_duplicate_matricula_or_email(self):
        connection = FakeConnection(rows=[{"id": 8}])
        data = users.RegistroAlumno(
            student_id="1234567890",
            full_name="Student",
            email="student@example.com",
            password="valid-password"
        )
        with patch.object(users, "engine", FakeEngine(connection)):
            with self.assertRaises(HTTPException) as error:
                users.registrar_alumno(data)

        self.assertEqual(error.exception.status_code, 409)
        self.assertIn(
            "LOWER(username) = LOWER(:matricula)",
            connection.statements[0][0]
        )
        self.assertEqual(len(connection.statements), 1)


def self_registration_execute(connection):
    def execute(statement, parameters=None):
        sql = str(statement)
        connection.statements.append((sql, parameters or {}))
        if "SELECT" in sql:
            return FakeResult(row=None)
        return FakeResult(scalar=37)

    return execute


if __name__ == "__main__":
    unittest.main()
