import threading
import time
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import teacher_approval_email_worker


class RecordingConnection:
    def __init__(self):
        self.statement = ""
        self.parameters = {}

    def execute(self, statement, parameters=None):
        self.statement = str(statement)
        self.parameters = parameters or {}


class FakeEngine:
    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def begin(self):
        yield self.connection


class TeacherApprovalEmailWorkerTests(unittest.TestCase):
    def test_worker_starts_recovers_and_stops(self):
        detener = threading.Event()
        worker = threading.Thread(
            target=teacher_approval_email_worker.iniciar_worker_aprobaciones,
            args=(detener,)
        )

        with patch.object(
            teacher_approval_email_worker,
            "recuperar_aprobaciones_interrumpidas"
        ) as recuperar, patch.object(
            teacher_approval_email_worker,
            "obtener_notificacion_aprobacion",
            return_value=None
        ):
            worker.start()
            limite = time.monotonic() + 2
            while (
                not teacher_approval_email_worker.worker_aprobaciones_activo()
                or not recuperar.called
            ):
                self.assertLess(time.monotonic(), limite)
                time.sleep(0.01)

            detener.set()
            worker.join(timeout=2)

        recuperar.assert_called_once()
        self.assertFalse(worker.is_alive())
        self.assertFalse(teacher_approval_email_worker.worker_aprobaciones_activo())

    def test_sent_notice_clears_approval_link_from_queue(self):
        connection = RecordingConnection()
        with patch.object(
            teacher_approval_email_worker,
            "engine",
            FakeEngine(connection)
        ):
            teacher_approval_email_worker.marcar_aprobacion_enviada(11)

        self.assertIn("body = N''", connection.statement)
        self.assertEqual(connection.parameters["id"], 11)


if __name__ == "__main__":
    unittest.main()
