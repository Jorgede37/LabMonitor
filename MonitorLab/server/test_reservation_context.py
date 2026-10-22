import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

from app.routes import admin
from app.reservation_context import obtener_reserva_en_hora
from app.hardware_events import registrar_evento


class FakeResult:
    def __init__(self, row=None, scalar=None, rows=None):
        self.row = row
        self.scalar = scalar
        self.rows = rows or []

    def mappings(self):
        return self

    def first(self):
        return self.row

    def scalar_one(self):
        return self.scalar

    def all(self):
        return self.rows


class FakeConnection:
    def __init__(self, reservation=None):
        self.reservation = reservation
        self.statements = []

    def execute(self, statement, parameters=None):
        self.statements.append((str(statement), parameters or {}))
        if "FROM dbo.lab_reservations AS r" in str(statement):
            return FakeResult(row=self.reservation)
        return FakeResult(scalar=87)


class FakeDetailConnection(FakeConnection):
    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.statements.append((sql, parameters or {}))
        if "FROM dbo.computers" in sql:
            return FakeResult(row={
                "id": 7,
                "hostname": "LAB-PC-07",
                "laboratory_id": 3
            })
        if "FROM dbo.hardware_components" in sql:
            return FakeResult(rows=[])
        if "FROM dbo.laboratories" in sql:
            return FakeResult(rows=[])
        if "FROM dbo.hardware_events he" in sql:
            return FakeResult(rows=[{
                "id": 42,
                "reserved_teacher_name": "Docente Histórico",
                "reservation_was_active": True
            }])
        if "FROM dbo.lab_reservations AS r" in sql:
            return FakeResult(row=self.reservation)
        raise AssertionError(f"Unexpected SQL: {sql}")


class FakeEngine:
    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def connect(self):
        yield self.connection


class ReservationContextTests(unittest.TestCase):
    def test_reservation_lookup_uses_aguascalientes_local_date_and_time(self):
        connection = FakeConnection(reservation={
            "reservation_id": 12,
            "teacher_name": "Docente",
            "subject": "Química"
        })

        result = obtener_reserva_en_hora(
            connection,
            laboratory_id=3,
            fecha=datetime(2026, 10, 19, 18, 30, tzinfo=timezone.utc)
        )

        self.assertEqual(result["reservation_id"], 12)
        _, parameters = connection.statements[0]
        self.assertEqual(parameters["reservation_date"].isoformat(), "2026-10-19")
        self.assertEqual(parameters["reservation_time"].strftime("%H:%M"), "12:30")

    def test_reservation_lookup_skips_computer_without_laboratory(self):
        connection = FakeConnection()

        self.assertIsNone(obtener_reserva_en_hora(
            connection,
            laboratory_id=None,
            fecha=datetime(2026, 10, 19, 18, 30, tzinfo=timezone.utc)
        ))
        self.assertEqual(connection.statements, [])

    def test_reservation_lookup_rejects_naive_datetime(self):
        with self.assertRaises(ValueError):
            obtener_reserva_en_hora(
                FakeConnection(),
                laboratory_id=3,
                fecha=datetime(2026, 10, 19, 12, 30)
            )

    def test_event_insert_persists_reservation_snapshot(self):
        connection = FakeConnection()
        reservation = {
            "reservation_id": 12,
            "teacher_user_id": 8,
            "teacher_name": "Docente",
            "teacher_matricula": "DOC123",
            "subject": "Química"
        }

        registrar_evento(
            connection=connection,
            computer_id=7,
            component_id=22,
            event_type="HARDWARE_CHANGED",
            detected_at=datetime(2026, 10, 19, 18, 30, tzinfo=timezone.utc),
            reservation=reservation
        )

        sql, parameters = connection.statements[0]
        self.assertIn("reservation_was_active", sql)
        self.assertEqual(parameters["reservation_id"], 12)
        self.assertEqual(parameters["reserved_teacher_user_id"], 8)
        self.assertEqual(parameters["reserved_teacher_name"], "Docente")
        self.assertEqual(parameters["reserved_teacher_matricula"], "DOC123")
        self.assertEqual(parameters["reservation_subject"], "Química")
        self.assertTrue(parameters["reservation_was_active"])

    def test_event_without_reservation_is_explicitly_snapshotted(self):
        connection = FakeConnection()

        registrar_evento(
            connection=connection,
            computer_id=7,
            component_id=22,
            event_type="HARDWARE_CHANGED",
            detected_at=datetime(2026, 10, 19, 18, 30, tzinfo=timezone.utc)
        )

        parameters = connection.statements[0][1]
        self.assertIsNone(parameters["reservation_id"])
        self.assertIsNone(parameters["reserved_teacher_name"])
        self.assertFalse(parameters["reservation_was_active"])

    def test_computer_detail_returns_current_and_historical_reservation_context(self):
        reservation = {
            "reservation_id": 12,
            "teacher_user_id": 8,
            "teacher_name": "Docente Actual",
            "teacher_matricula": "DOC123",
            "subject": "Química",
            "start_time": "12:00",
            "end_time": "13:00"
        }
        connection = FakeDetailConnection(reservation=reservation)

        with patch.object(admin, "engine", FakeEngine(connection)):
            result = admin.detalle_computadora(
                computer_id=7,
                administrador={"username": "admin"}
            )

        self.assertEqual(
            result["current_reservation"]["teacher_name"],
            "Docente Actual"
        )
        self.assertEqual(
            result["recent_events"][0]["reserved_teacher_name"],
            "Docente Histórico"
        )
        self.assertTrue(
            result["recent_events"][0]["reservation_was_active"]
        )
        event_query = next(
            sql for sql, _ in connection.statements
            if "FROM dbo.hardware_events he" in sql
        )
        self.assertIn("he.reserved_teacher_name", event_query)


if __name__ == "__main__":
    unittest.main()
