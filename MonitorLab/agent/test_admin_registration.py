import unittest
from unittest.mock import patch

import requests

import register


class FakeResponse:
    status_code = 201
    ok = True

    def json(self):
        return {
            "computer_id": 17,
            "hostname": "LAB-PC",
            "agent_token": "agent-secret"
        }


class AdminRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.agent_token_patch = patch.object(
            register.config,
            "AGENT_TOKEN",
            None
        )
        self.agent_token_patch.start()
        self.addCleanup(self.agent_token_patch.stop)

    @patch.object(register, "guardar_configuracion")
    @patch.object(register.requests, "post", return_value=FakeResponse())
    @patch.object(
        register,
        "obtener_datos_computadora",
        return_value={"hostname": "LAB-PC"}
    )
    def test_admin_registration_saves_agent_credential(
        self,
        _hardware,
        post,
        save_config
    ):
        result = register.registrar_computadora_con_administrador(
            "http://lab.example:8000",
            "admin-session-token"
        )

        self.assertEqual(
            post.call_args.args[0],
            "http://lab.example:8000/computers/register-admin"
        )
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"],
            "Bearer admin-session-token"
        )
        save_config.assert_called_once_with(
            "http://lab.example:8000",
            "agent-secret"
        )
        self.assertEqual(
            result,
            {"computer_id": 17, "hostname": "LAB-PC"}
        )

    @patch.object(
        register.requests,
        "post",
        side_effect=requests.ConnectionError("offline")
    )
    @patch.object(
        register,
        "obtener_datos_computadora",
        return_value={"hostname": "LAB-PC"}
    )
    def test_network_error_is_reported_without_saving_credentials(
        self,
        _hardware,
        _post
    ):
        with patch.object(register, "guardar_configuracion") as save_config:
            with self.assertRaisesRegex(
                RuntimeError,
                "No fue posible conectar"
            ):
                register.registrar_computadora_con_administrador(
                    "http://lab.example:8000",
                    "admin-session-token"
                )

        save_config.assert_not_called()

    @patch.object(register, "guardar_configuracion", side_effect=OSError("disk full"))
    @patch.object(register.requests, "post", return_value=FakeResponse())
    @patch.object(
        register,
        "obtener_datos_computadora",
        return_value={"hostname": "LAB-PC"}
    )
    def test_local_credential_write_error_is_explicit(
        self,
        _hardware,
        _post,
        _save_config
    ):
        with self.assertRaisesRegex(
            RuntimeError,
            "no pudo guardar su credencial local"
        ):
            register.registrar_computadora_con_administrador(
                "http://lab.example:8000",
                "admin-session-token"
            )


if __name__ == "__main__":
    unittest.main()
