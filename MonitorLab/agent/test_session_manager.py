import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import local_database
import session_manager
from local_database import (
    confirmar_cierre_local,
    guardar_sesion_local,
    inicializar_sesiones_locales,
    obtener_sesion_local_activa,
    token_autoriza_cierre_offline,
)
from session_manager import (
    ServerConnectionError,
    SessionManagerError,
    cerrar_sesion_estudiante,
    registrar_actividad_estudiante,
)


class LocalLogoutAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_data_dir = local_database.DATA_DIR
        self.previous_db_path = local_database.DB_PATH
        local_database.DATA_DIR = Path(self.temp_dir.name)
        local_database.DB_PATH = (
            local_database.DATA_DIR / "test_sessions.db"
        )
        self.connect_patch = patch.object(
            local_database,
            "conectar",
            side_effect=self.connect_and_close
        )
        self.connect_patch.start()
        inicializar_sesiones_locales()
        guardar_sesion_local(
            server_session_id=31,
            user_id=9,
            computer_id=2,
            student_id="student-test",
            login_at="2026-10-17T00:00:00Z",
            student_token="token-initial"
        )

    def tearDown(self):
        self.connect_patch.stop()
        local_database.DATA_DIR = self.previous_data_dir
        local_database.DB_PATH = self.previous_db_path
        self.temp_dir.cleanup()

    @contextmanager
    def connect_and_close(self):
        connection = sqlite3.connect(local_database.DB_PATH)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def test_activity_keeps_current_and_previous_valid_tokens(self):
        with patch.object(
            session_manager,
            "solicitar_servidor",
            return_value={"access_token": "token-renewed"}
        ):
            registrar_actividad_estudiante(
                "token-initial",
                31
            )

        session = obtener_sesion_local_activa()
        self.assertTrue(
            token_autoriza_cierre_offline(
                session,
                "token-initial"
            )
        )
        self.assertTrue(
            token_autoriza_cierre_offline(
                session,
                "token-renewed"
            )
        )
        self.assertNotIn("token-renewed", str(session))

    def test_pending_close_discards_offline_token_fingerprints(self):
        session = obtener_sesion_local_activa()
        self.assertTrue(
            token_autoriza_cierre_offline(session, "token-initial")
        )

        local_database.marcar_cierre_pendiente(31)
        session = obtener_sesion_local_activa()

        self.assertFalse(
            token_autoriza_cierre_offline(session, "token-initial")
        )

    def test_closed_session_discards_offline_logout_fingerprints(self):
        confirmar_cierre_local(
            31,
            "2026-10-17T00:01:00Z",
            "manual"
        )

        self.assertIsNone(obtener_sesion_local_activa())

    def test_offline_logout_queues_only_a_previously_verified_token(self):
        session = obtener_sesion_local_activa()

        with patch.object(
            session_manager,
            "obtener_sesion_local_activa",
            return_value=session
        ), patch.object(
            session_manager,
            "validar_identidad_local",
            side_effect=ServerConnectionError("offline")
        ):
            result = cerrar_sesion_estudiante("token-initial")

        self.assertEqual(result["status"], "pending_close")
        pending = obtener_sesion_local_activa()
        self.assertEqual(pending["status"], "pending_close")
        self.assertIsNone(pending["logout_token_hash"])

    def test_offline_logout_rejects_unknown_token_without_queueing(self):
        session = obtener_sesion_local_activa()

        with patch.object(
            session_manager,
            "obtener_sesion_local_activa",
            return_value=session
        ), patch.object(
            session_manager,
            "validar_identidad_local",
            side_effect=ServerConnectionError("offline")
        ), patch.object(
            session_manager,
            "marcar_cierre_pendiente"
        ) as mark_pending:
            with self.assertRaises(SessionManagerError):
                cerrar_sesion_estudiante("forged-token")

        mark_pending.assert_not_called()

    def test_http_rejection_does_not_use_offline_authorization(self):
        session = obtener_sesion_local_activa()

        with patch.object(
            session_manager,
            "obtener_sesion_local_activa",
            return_value=session
        ), patch.object(
            session_manager,
            "validar_identidad_local",
            side_effect=SessionManagerError("HTTP 401")
        ), patch.object(
            session_manager,
            "token_autoriza_cierre_offline"
        ) as offline_authorization:
            with self.assertRaises(SessionManagerError):
                cerrar_sesion_estudiante("token-initial")

        offline_authorization.assert_not_called()


if __name__ == "__main__":
    unittest.main()
