import unittest
from contextlib import contextmanager
from unittest.mock import patch

from app import email_service


class FakeScalars:
    def all(self):
        return [
            " Admin@Gmail.com ",
            "admin@gmail.com",
            "second@example.test",
            "bad address",
            "",
            None,
        ]


class FakeResult:
    def scalars(self):
        return FakeScalars()


class FakeConnection:
    def __init__(self):
        self.sql = ""

    def execute(self, statement):
        self.sql = str(statement)
        return FakeResult()


class FakeEngine:
    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def connect(self):
        yield self.connection


class ActiveAdministratorRecipientTests(unittest.TestCase):
    def test_recipients_are_active_admin_emails_deduplicated_case_insensitively(self):
        connection = FakeConnection()
        with patch.object(email_service, "engine", FakeEngine(connection)):
            recipients = email_service.obtener_correos_administradores()

        self.assertEqual(recipients, ["Admin@Gmail.com", "second@example.test"])
        self.assertIn("role = 'admin'", connection.sql)
        self.assertIn("is_active = 1", connection.sql)
        self.assertNotIn("ADMIN_ALERT_EMAILS", connection.sql)

    def test_outgoing_mail_includes_institutional_signature_once(self):
        smtp = email_service.smtplib.SMTP
        with patch.object(
            email_service,
            "obtener_configuracion",
            return_value={
                "host": "smtp.example.test",
                "port": 587,
                "user": "sender@example.test",
                "password": "test-secret",
                "from_email": "sender@example.test",
                "from_name": "LabMonitor",
                "use_tls": True
            }
        ), patch.object(email_service.smtplib, "SMTP") as smtp:
            servidor = smtp.return_value.__enter__.return_value
            email_service.enviar_correo(
                "admin@example.test",
                "Nueva reserva",
                "Se registró una reserva."
            )

        correo = servidor.send_message.call_args.args[0]
        contenido = correo.get_content()
        self.assertIn("Departamento de Sistemas", contenido)
        self.assertIn("Universidad de Durango", contenido)
        self.assertIn("Campus Aguascalientes", contenido)
        self.assertEqual(contenido.count("Departamento de Sistemas"), 1)

    def test_outgoing_mail_does_not_duplicate_existing_signature(self):
        with patch.object(
            email_service,
            "obtener_configuracion",
            return_value={
                "host": "smtp.example.test",
                "port": 587,
                "user": "sender@example.test",
                "password": "test-secret",
                "from_email": "sender@example.test",
                "from_name": "LabMonitor",
                "use_tls": True
            }
        ), patch.object(email_service.smtplib, "SMTP") as smtp:
            servidor = smtp.return_value.__enter__.return_value
            email_service.enviar_correo(
                "admin@example.test",
                "Nueva reserva",
                "Mensaje\n\nDepartamento de Sistemas\nCampus Aguascalientes"
            )

        contenido = servidor.send_message.call_args.args[0].get_content()
        self.assertEqual(contenido.count("Departamento de Sistemas"), 1)


if __name__ == "__main__":
    unittest.main()
