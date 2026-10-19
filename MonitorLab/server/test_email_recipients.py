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


if __name__ == "__main__":
    unittest.main()
