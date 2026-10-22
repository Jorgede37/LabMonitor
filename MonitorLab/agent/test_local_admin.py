import base64
import unittest
from unittest.mock import patch

import win32crypt

import config
import local_bridge
import register
from session_manager import SessionManagerError


class LocalAdminTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        secret = win32crypt.CryptProtectData(
            b"Local-test-Secret-2026!",
            "LabMonitor test credential",
            local_bridge.ENTROPIA_ADMIN_LOCAL,
            None,
            None,
            0x4
        )
        cls.original_secret = config.LOCAL_ADMIN_SECRET
        config.LOCAL_ADMIN_SECRET = base64.b64encode(
            secret
        ).decode("ascii")

    @classmethod
    def tearDownClass(cls):
        config.LOCAL_ADMIN_SECRET = cls.original_secret

    def setUp(self):
        local_bridge.intentos_admin_locales.clear()
        local_bridge.admin_local_bloqueado_hasta = 0

    def test_local_password_authenticates(self):
        local_bridge.autenticar_admin_local(
            "Sistemas_Admin",
            "Local-test-Secret-2026!"
        )

    def test_wrong_local_password_is_rejected(self):
        with self.assertRaises(SessionManagerError):
            local_bridge.autenticar_admin_local(
                "Sistemas_Admin",
                "incorrect"
            )

    def test_repeated_failures_temporarily_block_access(self):
        for _ in range(local_bridge.MAX_INTENTOS_ADMIN_LOCAL):
            with self.assertRaises(SessionManagerError):
                local_bridge.autenticar_admin_local(
                    "Sistemas_Admin",
                    "incorrect"
                )

        with self.assertRaisesRegex(
            SessionManagerError,
            "Demasiados intentos"
        ):
            local_bridge.autenticar_admin_local(
                "Sistemas_Admin",
                "Local-test-Secret-2026!"
            )

    def test_server_change_uses_local_authentication(self):
        with patch.object(local_bridge, "guardar_nuevo_servidor") as save:
            result = local_bridge.cambiar_servidor_con_admin_local({
                "local_admin_username": "Sistemas_Admin",
                "local_admin_password": "Local-test-Secret-2026!",
                "server_url": "http://127.0.0.1:9000",
            })

        save.assert_called_once_with("http://127.0.0.1:9000")
        self.assertEqual(
            result,
            {
                "server_url": "http://127.0.0.1:9000",
                "configured": False,
            }
        )

    def test_saved_server_preserves_secret_and_clears_old_agent_token(self):
        previous_url = config.SERVER_URL
        previous_token = config.AGENT_TOKEN
        previous_secret = config.LOCAL_ADMIN_SECRET
        config.LOCAL_ADMIN_SECRET = "protected-local-secret"
        config.AGENT_TOKEN = "old-server-token"
        try:
            with (
                patch.object(register, "preparar_directorio"),
                patch.object(register, "escribir_archivo") as write,
            ):
                register.guardar_nuevo_servidor(
                    "http://127.0.0.1:9000"
                )

            self.assertEqual(write.call_count, 2)
            private_content = write.call_args_list[1].args[1]
            self.assertIn(
                "LABMONITOR_LOCAL_ADMIN_SECRET=protected-local-secret",
                private_content
            )
            self.assertNotIn("old-server-token", private_content)
            self.assertIsNone(config.AGENT_TOKEN)
            self.assertEqual(config.SERVER_URL, "http://127.0.0.1:9000")
        finally:
            config.LOCAL_ADMIN_SECRET = previous_secret
            config.actualizar_credenciales(
                previous_url,
                previous_token
            )

    def test_named_pipe_client_initializes_and_closes_com(self):
        pipe = object()
        with (
            patch.object(local_bridge.pythoncom, "CoInitialize") as initialize,
            patch.object(local_bridge.pythoncom, "CoUninitialize") as uninitialize,
            patch.object(local_bridge, "atender_cliente") as handle,
            patch.object(local_bridge, "cerrar_pipe") as close_pipe,
            patch.object(local_bridge.clientes_disponibles, "release") as release,
        ):
            local_bridge.ejecutar_cliente(pipe)

        initialize.assert_called_once_with()
        handle.assert_called_once_with(pipe)
        uninitialize.assert_called_once_with()
        close_pipe.assert_called_once_with(pipe)
        release.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
