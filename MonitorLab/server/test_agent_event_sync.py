import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException

from app.routes import agent_events


class FakeResult:
    def __init__(self, row=None, scalar=None):
        self.row = row
        self.scalar = scalar

    def mappings(self):
        return self

    def first(self):
        return self.row

    def scalar_one(self):
        return self.scalar


class FakeConnection:
    def __init__(self, student_session=None):
        self.statements = []
        self.student_session = student_session

    def execute(self, statement, parameters=None):
        sql = str(statement)
        parameters = parameters or {}
        self.statements.append((sql, parameters))

        if "FROM dbo.computers" in sql:
            return FakeResult(row={
                "id": 7,
                "friendly_name": "LAB-PC-07",
                "hostname": "LAB-PC-07",
                "lab": "Laboratorio"
            })

        if "FROM dbo.hardware_events" in sql:
            return FakeResult()

        if "FROM dbo.hardware_components" in sql:
            return FakeResult()

        if "FROM dbo.sessions AS s" in sql:
            return FakeResult(row=self.student_session)

        if "INSERT INTO dbo.hardware_components" in sql:
            return FakeResult(scalar=88)

        raise AssertionError(f"Unexpected SQL: {sql}")


class FakeEngine:
    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def begin(self):
        yield self.connection


class HardwareEventSyncTests(unittest.TestCase):
    def create_batch(self, event_type, detected_at=None):
        return agent_events.LoteEventos(events=[{
            "event_uuid": uuid4(),
            "component_type": "mouse",
            "hardware_identifier": "MOUSE-TEST",
            "event_type": event_type,
            "detected_at": detected_at or datetime.now(timezone.utc)
        }])

    def test_notification_identifies_student_and_matricula_from_event_time(self):
        detected_at = datetime(2026, 10, 19, 18, 30, tzinfo=timezone.utc)
        connection = FakeConnection(student_session={
            "session_id": 23,
            "user_id": 14,
            "full_name": "Ana Estudiante",
            "student_id": "1234567890"
        })

        with patch.object(
            agent_events,
            "engine",
            FakeEngine(connection)
        ), patch.object(
            agent_events,
            "obtener_destinatarios",
            return_value=["admin@example.test"]
        ), patch.object(
            agent_events,
            "registrar_evento",
            return_value=42
        ) as register_event, patch.object(
            agent_events,
            "registrar_notificacion"
        ) as register_notification:
            agent_events.sincronizar_eventos(
                self.create_batch("DEVICE_DISCONNECTED", detected_at),
                {"computer_id": 7}
            )

        register_event.assert_called_once()
        self.assertEqual(register_event.call_args.kwargs["session_id"], 23)
        self.assertEqual(register_event.call_args.kwargs["user_id"], 14)
        notification_body = register_notification.call_args.kwargs["mensaje"]
        self.assertIn("Ana Estudiante", notification_body)
        self.assertIn("1234567890", notification_body)
        self.assertNotIn("Sin sesión identificada", notification_body)
        session_query = next(
            (sql, parameters)
            for sql, parameters in connection.statements
            if "FROM dbo.sessions AS s" in sql
        )
        self.assertEqual(
            session_query[1]["event_at"],
            detected_at.replace(tzinfo=None)
        )
        self.assertIn("s.login_at <= :event_at", session_query[0])
        self.assertIn("s.logout_at >= :event_at", session_query[0])
        self.assertIn("s.computer_id = :computer_id", session_query[0])

    def test_missing_component_is_registered_for_disconnect_event(self):
        connection = FakeConnection()

        with patch.object(
            agent_events,
            "engine",
            FakeEngine(connection)
        ), patch.object(
            agent_events,
            "obtener_destinatarios",
            return_value=["admin@example.test", "second-admin@example.test"]
        ), patch.object(
            agent_events,
            "registrar_evento",
            return_value=42
        ) as register_event, patch.object(
            agent_events,
            "registrar_notificacion"
        ) as register_notification:
            result = agent_events.sincronizar_eventos(
                self.create_batch("DEVICE_DISCONNECTED"),
                {"computer_id": 7}
            )

        insert_sql, insert_parameters = next(
            (sql, parameters)
            for sql, parameters in connection.statements
            if "INSERT INTO dbo.hardware_components" in sql
        )
        self.assertIn("OUTPUT INSERTED.id", insert_sql)
        self.assertEqual(insert_parameters["status"], "removed")
        self.assertEqual(result["total"], 1)
        self.assertEqual(len(result["accepted"]), 1)
        self.assertEqual(
            register_event.call_args.kwargs["component_id"],
            88
        )
        self.assertIsNone(
            register_event.call_args.kwargs["session_id"]
        )
        self.assertIsNone(
            register_event.call_args.kwargs["user_id"]
        )
        self.assertEqual(register_notification.call_count, 2)
        self.assertIn(
            "Sin sesión identificada",
            register_notification.call_args.kwargs["mensaje"]
        )
        self.assertIn(
            "MATRÍCULA:\nNo disponible",
            register_notification.call_args.kwargs["mensaje"]
        )
        self.assertEqual(
            [call.kwargs["destinatario"] for call in register_notification.call_args_list],
            ["admin@example.test", "second-admin@example.test"]
        )

    def test_missing_component_for_change_event_is_rejected(self):
        connection = FakeConnection()

        with patch.object(
            agent_events,
            "engine",
            FakeEngine(connection)
        ), patch.object(
            agent_events,
            "obtener_destinatarios",
            return_value=["admin@example.test"]
        ):
            with self.assertRaises(HTTPException) as error:
                agent_events.sincronizar_eventos(
                    self.create_batch("HARDWARE_CHANGED"),
                    {"computer_id": 7}
                )

        self.assertEqual(error.exception.status_code, 409)
        self.assertFalse(any(
            "INSERT INTO dbo.hardware_components" in sql
            for sql, _ in connection.statements
        ))


if __name__ == "__main__":
    unittest.main()
