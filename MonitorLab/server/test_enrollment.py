import hashlib
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi import HTTPException

from app.routes import computers, enrollment
from app.routes.computers import RegistroComputadora


class Result:
    def __init__(self, rows=None, scalar=None, rowcount=0):
        self.rows = rows or []
        self.scalar = scalar
        self.rowcount = rowcount

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows

    def scalar_one(self):
        return self.scalar


class EnrollmentDB:
    def __init__(self, now=None):
        self.now = now or datetime.now()
        self.code = None
        self.computers = []
        self.credentials = {}
        self.statements = []
        self.next_id = 1

    def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}
        self.statements.append((sql, params))

        if "INSERT INTO dbo.agent_enrollment_codes" in sql:
            self.code = {
                "code_hash": params["code_hash"],
                "expires_at": self.now + timedelta(seconds=params["ttl_seconds"]),
                "consumed_at": None,
                "bound_identity_hash": None,
                "bound_computer_id": None,
            }
            return Result(scalar=self.code["expires_at"])
        if "FROM dbo.agent_enrollment_codes WITH" in sql:
            if (self.code and self.code["code_hash"] == params["code_hash"]
                    and self.code["expires_at"] > self.now):
                return Result([dict(self.code)])
            return Result()
        if "FROM dbo.computers WITH" in sql:
            found = [row for row in self.computers if (
                (params["machine_uuid"] and row.get("machine_uuid") == params["machine_uuid"])
                or (params["serial_number"] and row.get("serial_number") == params["serial_number"])
                or row["mac_address"] == params["mac_address"]
            )]
            return Result([dict(row) for row in found])
        if "INSERT INTO dbo.computers" in sql:
            row = dict(params)
            row.update({"id": self.next_id, "is_active": True, "lab": None, "laboratory_id": None})
            self.computers.append(row)
            self.next_id += 1
            return Result(scalar=row["id"])
        if "UPDATE dbo.computers" in sql:
            row = next(r for r in self.computers if r["id"] == params["computer_id"])
            for key in ("hostname", "mac_address", "ip_address", "operating_system"):
                row[key] = params[key]
            for key in ("serial_number", "machine_uuid"):
                row[key] = params[key] or row[key]
            return Result(rowcount=1)
        if "UPDATE dbo.agent_credentials" in sql:
            cid = params["computer_id"]
            if cid in self.credentials:
                self.credentials[cid] = params["token_hash"]
                return Result(rowcount=1)
            return Result(rowcount=0)
        if "INSERT INTO dbo.agent_credentials" in sql:
            self.credentials[params["computer_id"]] = params["token_hash"]
            return Result(rowcount=1)
        if "UPDATE dbo.agent_enrollment_codes" in sql:
            self.code.update({
                "consumed_at": self.now,
                "bound_identity_hash": params["identity_hash"],
                "bound_computer_id": params["computer_id"],
            })
            return Result(rowcount=1)
        raise AssertionError(f"Unexpected SQL: {sql}")


class FakeEngine:
    def __init__(self, db):
        self.db = db

    @contextmanager
    def begin(self):
        yield self.db


class EnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.db = EnrollmentDB()
        self.engine_patch = patch.object(computers, "engine", FakeEngine(self.db))
        self.engine_patch.start()
        self.addCleanup(self.engine_patch.stop)

    def register(self, code, mac="00:11:22:33:44:55", hostname="LAB-PC", uuid="uuid-a"):
        return computers.registrar_computadora(
            RegistroComputadora(
                hostname=hostname,
                mac_address=mac,
                machine_uuid=uuid,
                serial_number="serial-a",
                ip_address="192.0.2.10",
                operating_system="Windows"
            ),
            x_enrollment_key=code
        )

    def test_admin_code_issuance_returns_plaintext_once_and_persists_hash(self):
        with patch.object(enrollment, "engine", FakeEngine(self.db)):
            result = enrollment.crear_codigo_inscripcion({"id": 4})
        self.assertIn("enrollment_code", result)
        self.assertEqual(result["expires_in_seconds"], 900)
        self.assertEqual(
            self.db.code["code_hash"],
            hashlib.sha256(result["enrollment_code"].encode()).hexdigest()
        )
        self.assertNotEqual(self.db.code["code_hash"], result["enrollment_code"])

    def test_new_enrollment_and_same_machine_retry_reuse_row_and_rotate_token(self):
        self.db.code = {
            "code_hash": hashlib.sha256(b"ONE-TIME").hexdigest(),
            "expires_at": self.db.now + timedelta(minutes=15),
            "consumed_at": None,
            "bound_identity_hash": None,
            "bound_computer_id": None,
        }
        first = self.register("one-time")
        old_hash = self.db.credentials[1]
        second = self.register("ONE-TIME", hostname="LAB-PC-RENAMED")

        self.assertEqual(first["computer_id"], second["computer_id"])
        self.assertEqual(len(self.db.computers), 1)
        self.assertNotEqual(first["agent_token"], second["agent_token"])
        self.assertNotEqual(old_hash, self.db.credentials[1])
        self.assertEqual(self.db.computers[0]["hostname"], "LAB-PC-RENAMED")
        self.assertIsNone(self.db.computers[0]["lab"])
        update_sql = next(sql for sql, _ in self.db.statements if "UPDATE dbo.computers" in sql)
        self.assertNotIn("laboratory_id", update_sql)
        self.assertNotIn("lab =", update_sql)

    def test_consumed_code_cannot_enroll_different_hardware(self):
        self.db.code = {
            "code_hash": hashlib.sha256(b"ONE-TIME").hexdigest(),
            "expires_at": self.db.now + timedelta(minutes=15),
            "consumed_at": None,
            "bound_identity_hash": None,
            "bound_computer_id": None,
        }
        self.register("ONE-TIME")
        with self.assertRaises(HTTPException) as caught:
            self.register("ONE-TIME", mac="00:11:22:33:44:66", uuid="uuid-b")
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(len(self.db.computers), 1)

    def test_expired_or_unknown_code_rejected_before_computer_insert(self):
        with self.assertRaises(HTTPException) as caught:
            self.register("missing")
        self.assertEqual(caught.exception.status_code, 401)
        self.assertEqual(self.db.computers, [])

    def test_admin_session_registers_computer_without_enrollment_code(self):
        datos = RegistroComputadora(
            hostname="LAB-PC",
            mac_address="00:11:22:33:44:55",
            machine_uuid="uuid-a",
            serial_number="serial-a",
            ip_address="192.0.2.10",
            operating_system="Windows"
        )

        result = computers.registrar_computadora_con_administrador(
            datos,
            {"id": 4, "role": "admin"}
        )

        self.assertEqual(result["computer_id"], 1)
        self.assertEqual(len(self.db.computers), 1)
        self.assertEqual(len(self.db.credentials), 1)
        self.assertEqual(
            self.db.credentials[1],
            hashlib.sha256(
                result["agent_token"].encode("utf-8")
            ).hexdigest()
        )

    def test_admin_registration_reuses_hardware_and_rotates_agent_token(self):
        datos = RegistroComputadora(
            hostname="LAB-PC",
            mac_address="00:11:22:33:44:55",
            machine_uuid="uuid-a",
            serial_number="serial-a",
            ip_address="192.0.2.10",
            operating_system="Windows"
        )
        first = computers.registrar_computadora_con_administrador(
            datos,
            {"id": 4, "role": "admin"}
        )
        second = computers.registrar_computadora_con_administrador(
            datos.model_copy(update={"hostname": "LAB-PC-RENAMED"}),
            {"id": 4, "role": "admin"}
        )

        self.assertEqual(first["computer_id"], second["computer_id"])
        self.assertEqual(len(self.db.computers), 1)
        self.assertNotEqual(first["agent_token"], second["agent_token"])
        self.assertEqual(self.db.computers[0]["hostname"], "LAB-PC-RENAMED")


if __name__ == "__main__":
    unittest.main()
