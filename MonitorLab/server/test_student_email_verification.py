import hashlib
import unittest
from contextlib import contextmanager
from datetime import datetime
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
            "email": "admin@example.com",
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
            result = auth.iniciar_sesion_dashboard(
                auth.LoginRequest(
                    username="admin@example.com",
                    password="password"
                )
            )

        self.assertEqual(result["access_token"], "admin-token")
        self.assertEqual(result["user"]["role"], "admin")
        self.assertIn("role = 'admin'", connection.statements[0][0])
        self.assertIn("email", connection.statements[0][0])

    def test_legacy_login_keeps_admin_username_compatibility(self):
        connection = FakeConnection(rows=[{
            "id": 3,
            "username": "admin",
            "password_hash": "stored-hash",
            "role": "admin",
            "full_name": "Administrator",
            "is_active": True,
            "email_verified": False,
            "teacher_approved": False
        }])
        with patch.object(auth, "engine", FakeEngine(connection)), patch.object(
            auth,
            "verificar_contrasena",
            return_value=True
        ), patch.object(auth, "crear_token", return_value="admin-token"):
            result = auth.iniciar_sesion(
                auth.LoginRequest(username="admin", password="password")
            )

        self.assertEqual(result["user"]["role"], "admin")
        self.assertIn("role IN ('admin', 'student')", connection.statements[0][0])

    def test_unapproved_teacher_cannot_login(self):
        connection = FakeConnection(rows=[{
            "id": 9,
            "username": "DOC-009",
            "password_hash": "stored-hash",
            "role": "teacher",
            "full_name": "Teacher",
            "is_active": True,
            "email_verified": True,
            "teacher_approved": False
        }])
        with patch.object(auth, "engine", FakeEngine(connection)), patch.object(
            auth,
            "verificar_contrasena",
            return_value=True
        ):
            with self.assertRaises(HTTPException) as error:
                auth.iniciar_sesion_docente(
                    auth.LoginRequest(
                        username="DOC-009",
                        password="password"
                    )
                )

        self.assertEqual(error.exception.status_code, 403)

    def test_teacher_registration_needs_no_email_and_starts_pending(self):
        connection = FakeConnection()
        token = "approval-token-for-test"
        datos = users.RegistroDocente(
            matricula="DOC-009",
            full_name="Docente de Prueba",
            password="password-seguro"
        )

        with patch.object(users, "engine", FakeEngine(connection)), patch.object(
            users,
            "generar_hash",
            return_value="secure-hash"
        ), patch.object(
            users,
            "obtener_administradores_con_correo",
            return_value=[{"id": 3, "email": "admin@example.com"}]
        ), patch(
            "app.routes.users.secrets.token_urlsafe",
            return_value=token
        ):
            result = users.registrar_docente(datos)

        insert_sql, parameters = connection.statements[1]
        self.assertIn("'teacher'", insert_sql)
        self.assertIn("teacher_approved", insert_sql)
        self.assertIn("NULL", insert_sql)
        self.assertEqual(parameters["matricula"], "DOC-009")
        self.assertEqual(result["approved"], False)
        self.assertEqual(result["role"], "teacher")
        token_sql, token_parameters = connection.statements[2]
        self.assertIn("teacher_approval_tokens", token_sql)
        self.assertEqual(
            token_parameters["token_hash"],
            hashlib.sha256(token.encode("ascii")).hexdigest()
        )
        self.assertNotIn(token, str(token_parameters))
        email_sql, email_parameters = connection.statements[3]
        self.assertIn("teacher_approval_email_notifications", email_sql)
        self.assertEqual(email_parameters["recipient"], "admin@example.com")
        self.assertIn(token, email_parameters["body"])
        self.assertIn("Campus Aguascalientes", email_parameters["body"])

    def test_teacher_approval_preview_only_returns_pending_account_details(self):
        token = "one-time-approval-token-0123456789"
        connection = FakeConnection(rows=[{
            "teacher_user_id": 37,
            "full_name": "Docente de Prueba",
            "teacher_id": "DOC-37",
            "expires_at": datetime(2026, 10, 21, 12, 0)
        }])
        with patch.object(auth, "engine", FakeEngine(connection)):
            result = auth.previsualizar_aprobacion_docente(
                auth.TeacherApprovalRequest(token=token)
            )

        self.assertEqual(result["teacher"]["full_name"], "Docente de Prueba")
        self.assertEqual(result["teacher"]["matricula"], "DOC-37")
        self.assertEqual(
            connection.statements[0][1]["token_hash"],
            hashlib.sha256(token.encode("ascii")).hexdigest()
        )

    def test_teacher_approval_confirm_consumes_tokens_and_records_admin(self):
        token = "one-time-approval-token-9876543210"
        connection = FakeConnection(rows=[{
            "token_id": 12,
            "teacher_user_id": 37,
            "administrator_user_id": 3,
            "teacher_approved": False
        }])
        with patch.object(auth, "engine", FakeEngine(connection)):
            result = auth.confirmar_aprobacion_docente(
                auth.TeacherApprovalRequest(token=token)
            )

        self.assertIn("autorizada", result["message"])
        self.assertIn("teacher_approved = 1", connection.statements[1][0])
        self.assertEqual(connection.statements[1][1]["administrator_user_id"], 3)
        self.assertIn("consumed_at = SYSUTCDATETIME()", connection.statements[2][0])

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

    def test_laboratory_name_update_also_updates_computer_labels(self):
        connection = FakeConnection(rows=[{"id": 2}, None, {
            "id": 2,
            "name": "Laboratorio actualizado",
            "created_at": None
        }])
        with patch.object(admin, "engine", FakeEngine(connection)):
            result = admin.actualizar_laboratorio(
                2,
                admin.LaboratorioActualizar(name="Laboratorio actualizado"),
                {"id": 1, "username": "admin"}
            )

        self.assertEqual(
            result["laboratory"]["name"],
            "Laboratorio actualizado"
        )
        self.assertEqual(len(connection.statements), 4)
        self.assertIn(
            "UPDATE dbo.computers",
            connection.statements[3][0]
        )
        self.assertEqual(
            connection.statements[3][1]["name"],
            "Laboratorio actualizado"
        )

    def test_laboratory_update_rejects_duplicate_names(self):
        connection = FakeConnection(rows=[{"id": 2}, {"id": 3}])
        with patch.object(admin, "engine", FakeEngine(connection)):
            with self.assertRaises(HTTPException) as error:
                admin.actualizar_laboratorio(
                    2,
                    admin.LaboratorioActualizar(name="Otro laboratorio"),
                    {"id": 1, "username": "admin"}
                )

        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(len(connection.statements), 2)

    def test_laboratory_delete_is_blocked_when_it_has_computers_or_reservations(self):
        connection = FakeConnection(rows=[{"id": 2}, {
            "computers": 1,
            "reservations": 0
        }])
        with patch.object(admin, "engine", FakeEngine(connection)):
            with self.assertRaises(HTTPException) as error:
                admin.eliminar_laboratorio(
                    2,
                    {"id": 1, "username": "admin"}
                )

        self.assertEqual(error.exception.status_code, 409)
        self.assertIn("computadora(s)", error.exception.detail)
        self.assertFalse(any(
            "DELETE FROM dbo.laboratories" in sql
            for sql, _ in connection.statements
        ))

    def test_unused_laboratory_can_be_deleted(self):
        connection = FakeConnection(rows=[{"id": 2}, {
            "computers": 0,
            "reservations": 0
        }])
        with patch.object(admin, "engine", FakeEngine(connection)):
            result = admin.eliminar_laboratorio(
                2,
                {"id": 1, "username": "admin"}
            )

        self.assertIn("eliminado", result["message"])
        self.assertIn(
            "DELETE FROM dbo.laboratories",
            connection.statements[2][0]
        )

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
