import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import HTTPException

from app.routes import admin
from app.routes import agent_routes
from app.routes.agent_routes import (
    ComponenteHardware,
    InventarioHardware
)


class FakeResult:
    def __init__(self, rows=None):
        self.rows = rows or []

    def mappings(self):
        return self

    def all(self):
        return self.rows


class FakeConnection:
    def __init__(self, existing=None, events=None):
        self.existing = existing or []
        self.events = events or []
        self.statements = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.statements.append((sql, parameters or {}))

        if "FROM dbo.hardware_components" in sql:
            return FakeResult(self.existing)

        return FakeResult(self.events)


class FakeEngine:
    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def begin(self):
        yield self.connection

    @contextmanager
    def connect(self):
        yield self.connection


class HardwareDashboardTests(unittest.TestCase):
    def test_partial_inventory_does_not_remove_unqueried_types(self):
        connection = FakeConnection(existing=[
            {
                "id": 1,
                "component_type": "gpu",
                "hardware_identifier": "GPU-1",
                "status": "active"
            },
            {
                "id": 2,
                "component_type": "keyboard",
                "hardware_identifier": "KEY-1",
                "status": "active"
            }
        ])
        inventory = InventarioHardware(
            components=[
                ComponenteHardware(
                    component_type="gpu",
                    hardware_identifier="GPU-1",
                    manufacturer="Fabricante",
                    model="GPU virtual",
                    serial_number=None
                )
            ],
            complete=False,
            complete_types=["gpu"]
        )

        with patch.object(
            agent_routes,
            "engine",
            FakeEngine(connection)
        ):
            result = agent_routes.sincronizar_hardware(
                inventory,
                {"computer_id": 7}
            )

        self.assertEqual(result["complete_types"], ["gpu"])
        self.assertFalse(any(
            "SET status = 'removed'" in statement
            for statement, _ in connection.statements
        ))

    def test_dashboard_returns_mail_status_with_recent_events(self):
        connection = FakeConnection(events=[{
            "id": 4,
            "computer_id": 7,
            "hostname": "LAB-PC-07",
            "lab": "Laboratorio",
            "component_type": "gpu",
            "model": "GPU virtual",
            "hardware_identifier": "GPU-1",
            "event_type": "HARDWARE_CHANGED",
            "previous_value": "model=Modelo A",
            "new_value": "model=Modelo B",
            "detected_at": datetime(2026, 10, 17, tzinfo=timezone.utc),
            "notification_count": 1,
            "pending_notifications": 0,
            "sent_notifications": 1,
            "failed_notifications": 0,
            "email_sent_at": datetime(2026, 10, 17, tzinfo=timezone.utc),
            "email_status": "sent"
        }])

        with patch.object(
            admin,
            "engine",
            FakeEngine(connection)
        ), patch.object(
            admin,
            "obtener_estado_configuracion_correo",
            return_value={
                "smtp_configured": True,
                "recipient_count": 1,
                "ready": True
            }
        ), patch.object(
            admin,
            "worker_correo_activo",
            return_value=True
        ):
            result = admin.listar_eventos_hardware(
                administrador={"username": "admin"},
                from_date=None,
                to_date=None
            )

        self.assertEqual(result["total"], 1)
        self.assertEqual(
            result["events"][0]["email_status"],
            "sent"
        )
        self.assertTrue(result["email"]["worker_running"])
        self.assertIn(
            "LEFT JOIN dbo.email_notifications",
            connection.statements[0][0]
        )

    def test_computer_listing_marks_heartbeat_status_and_filters_event_dates(self):
        connection = FakeConnection(existing=[{
            "id": 7,
            "hostname": "LAB-PC-07",
            "last_seen": datetime(2026, 10, 21, tzinfo=timezone.utc),
            "is_online": True,
            "matching_event_count": 2,
            "total_events": 9,
        }])

        with patch.object(
            admin,
            "engine",
            FakeEngine(connection)
        ):
            result = admin.listar_computadoras(
                events_from=datetime(2026, 10, 1).date(),
                events_to=datetime(2026, 10, 21).date(),
                administrador={"username": "admin"}
            )

        statement, parameters = connection.statements[0]
        self.assertIn("AS is_online", statement)
        self.assertIn("EXISTS", statement)
        self.assertEqual(
            parameters["heartbeat_timeout"],
            admin.TIMEOUT_SIN_HEARTBEAT
        )
        self.assertEqual(
            parameters["events_from"].isoformat(),
            "2026-10-01"
        )
        self.assertTrue(result["computers"][0]["is_online"])
        self.assertEqual(
            result["computers"][0]["last_seen"],
            "2026-10-21T00:00:00Z"
        )

    def test_hardware_events_accept_date_filters(self):
        connection = FakeConnection(events=[])

        with patch.object(
            admin,
            "engine",
            FakeEngine(connection)
        ), patch.object(
            admin,
            "obtener_estado_configuracion_correo",
            return_value={"ready": True}
        ), patch.object(
            admin,
            "worker_correo_activo",
            return_value=True
        ):
            result = admin.listar_eventos_hardware(
                from_date=datetime(2026, 10, 1).date(),
                to_date=datetime(2026, 10, 21).date(),
                administrador={"username": "admin"}
            )

        statement, parameters = connection.statements[0]
        self.assertIn("he.detected_at >= :from_date", statement)
        self.assertIn("DATEADD(DAY, 1, :to_date)", statement)
        self.assertNotIn("TOP 100", statement)
        self.assertEqual(parameters["from_date"].isoformat(), "2026-10-01")
        self.assertEqual(parameters["to_date"].isoformat(), "2026-10-21")
        self.assertEqual(result["events"], [])

    def test_inventory_rejects_untrusted_partial_type(self):
        inventory = InventarioHardware(
            components=[],
            complete=False,
            complete_types=["unknown"]
        )

        with self.assertRaises(HTTPException) as error:
            agent_routes.sincronizar_hardware(
                inventory,
                {"computer_id": 7}
            )

        self.assertEqual(error.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
