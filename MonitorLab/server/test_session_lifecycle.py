import os
import secrets
import unittest
from contextlib import contextmanager
from unittest.mock import patch


os.environ.setdefault(
    "JWT_SECRET_KEY",
    secrets.token_urlsafe(48)
)

from fastapi import HTTPException

from app.routes import sessions
from app.routes.sessions import RegistrarActividadRequest
import session_worker
from session_worker import (
    cerrar_sesiones_inactivas,
    cerrar_sesiones_sin_heartbeat,
    obtener_entero_entorno,
    obtener_filtro_computadora,
)


class FakeResult:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row

    def all(self):
        return []


class FakeConnection:
    def __init__(self, row):
        self.row = row
        self.statement = None
        self.parameters = None

    def execute(self, statement, parameters):
        self.statement = str(statement)
        self.parameters = parameters
        return FakeResult(self.row)


class FakeEngine:
    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def begin(self):
        yield self.connection


class SessionActivityTests(unittest.TestCase):
    def test_activity_is_bound_to_student_computer_and_active_session(self):
        connection = FakeConnection({
            "id": 23,
            "last_activity_at": None
        })

        with patch.object(
            sessions,
            "engine",
            FakeEngine(connection)
        ):
            resultado = sessions.registrar_actividad(
                RegistrarActividadRequest(session_id=23),
                {"id": 7},
                {"computer_id": 4}
            )

        self.assertEqual(resultado["session_id"], 23)
        self.assertIn("user_id = :user_id", connection.statement)
        self.assertIn("computer_id = :computer_id", connection.statement)
        self.assertIn("logout_at IS NULL", connection.statement)
        self.assertEqual(connection.parameters, {
            "session_id": 23,
            "user_id": 7,
            "computer_id": 4
        })

    def test_activity_rejects_closed_or_foreign_session(self):
        connection = FakeConnection(None)

        with patch.object(
            sessions,
            "engine",
            FakeEngine(connection)
        ):
            with self.assertRaises(HTTPException) as error:
                sessions.registrar_actividad(
                    RegistrarActividadRequest(session_id=23),
                    {"id": 7},
                    {"computer_id": 4}
                )

        self.assertEqual(error.exception.status_code, 409)


class SessionWorkerTests(unittest.TestCase):
    def test_idle_timeout_is_configurable_and_rejects_zero(self):
        with patch.dict(
            os.environ,
            {"LABMONITOR_IDLE_TIMEOUT_SECONDS": "15"}
        ):
            self.assertEqual(
                obtener_entero_entorno(
                    "LABMONITOR_IDLE_TIMEOUT_SECONDS",
                    300
                ),
                15
            )

        with patch.dict(
            os.environ,
            {"LABMONITOR_IDLE_TIMEOUT_SECONDS": "0"}
        ):
            with self.assertRaises(ValueError):
                obtener_entero_entorno(
                    "LABMONITOR_IDLE_TIMEOUT_SECONDS",
                    300
                )

    def test_computer_filter_defaults_to_vm_and_all_is_explicit(self):
        self.assertEqual(obtener_filtro_computadora("2"), 2)
        self.assertIsNone(obtener_filtro_computadora("all"))
        self.assertIsNone(obtener_filtro_computadora(""))

    def test_idle_close_uses_server_time_and_records_reason(self):
        connection = FakeConnection(None)

        with patch("session_worker.engine", FakeEngine(connection)):
            with patch.object(
                session_worker,
                "TIMEOUT_INACTIVIDAD",
                15
            ):
                cerrar_sesiones_inactivas()

        self.assertIn(
            "close_reason = 'inactivity'",
            connection.statement
        )
        self.assertIn(
            "s.last_activity_at < DATEADD",
            connection.statement
        )
        self.assertIn(
            "SYSUTCDATETIME()",
            connection.statement
        )
        self.assertEqual(
            connection.parameters["timeout_inactividad"],
            15
        )

    def test_heartbeat_timeout_closes_open_sessions_for_scoped_computer(self):
        connection = FakeConnection(None)

        with patch("session_worker.engine", FakeEngine(connection)):
            with patch.object(
                session_worker,
                "COMPUTADORA_PRUEBA_ID",
                2
            ), patch.object(
                session_worker,
                "TIMEOUT_SIN_HEARTBEAT",
                120
            ):
                cerrar_sesiones_sin_heartbeat()

        self.assertIn(
            "close_reason = 'heartbeat_lost'",
            connection.statement
        )
        self.assertIn(
            "c.last_seen < DATEADD",
            connection.statement
        )
        self.assertIn(
            "s.login_at < DATEADD",
            connection.statement
        )
        self.assertEqual(
            connection.parameters,
            {"computer_id": 2, "timeout": 120}
        )


if __name__ == "__main__":
    unittest.main()
