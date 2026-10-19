import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import assigned_access


class AssignedAccessTests(unittest.TestCase):
    def setUp(self):
        self.windows_patch = patch.object(
            assigned_access,
            "IS_WINDOWS",
            True
        )
        self.windows_patch.start()
        self.addCleanup(self.windows_patch.stop)

        self.server_patch = patch.object(
            assigned_access.config,
            "SERVER_URL",
            "https://lab.example"
        )
        self.server_patch.start()
        self.addCleanup(self.server_patch.stop)

    @patch.object(assigned_access.subprocess, "run")
    def test_home_edition_is_rejected_before_modifying_windows(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = "CoreSingleLanguage\n"

        with patch.object(assigned_access, "_verify_administrator") as verify:
            with self.assertRaisesRegex(
                RuntimeError,
                "requiere Windows Pro.*CoreSingleLanguage"
            ):
                assigned_access.cambiar_acceso_asignado(
                    "Apply",
                    "Prueba_Server",
                    "admin-session-token"
                )

        verify.assert_not_called()
        run.assert_called_once()

    @patch.object(Path, "is_file", return_value=True)
    @patch.object(assigned_access, "_get_installation_paths")
    @patch.object(assigned_access.subprocess, "run")
    @patch.object(assigned_access.requests, "get")
    def test_apply_validates_admin_and_targets_current_windows_account(
        self,
        get,
        run,
        get_paths,
        _file_exists
    ):
        with patch.object(assigned_access, "_verify_windows_edition"):
            self._test_apply_registered(
                get,
                run,
                get_paths
            )

    def _test_apply_registered(self, get, run, get_paths):
        get.return_value.raise_for_status.return_value = None
        run.return_value.returncode = 0
        script = Path(r"C:\LabMonitor\Tools\ConfigureAssignedAccess.ps1")
        student = Path(r"C:\LabMonitor\Student\LabMonitorStudent.exe")
        get_paths.return_value = (script, student)

        result = assigned_access.cambiar_acceso_asignado(
            "Apply",
            "Prueba_Server",
            "admin-session-token"
        )

        get.assert_called_once_with(
            "https://lab.example/admin/laboratories",
            headers={"Authorization": "Bearer admin-session-token"},
            timeout=10
        )
        command = run.call_args.args[0]
        self.assertIn("-RunAsSystem", command)
        self.assertIn("Prueba_Server", command)
        self.assertIn(str(student), command)
        self.assertEqual(result["operation"], "Apply")
        self.assertEqual(result["windows_account"], "Prueba_Server")

    @patch.object(assigned_access.requests, "get")
    def test_rejects_invalid_or_domain_windows_account_before_server_request(
        self,
        get
    ):
        for windows_account in ("", "DOMAIN\\student", "a" * 21):
            with self.subTest(windows_account=windows_account):
                with self.assertRaises(ValueError):
                    assigned_access.cambiar_acceso_asignado(
                        "Apply",
                        windows_account,
                        "admin-session-token"
                    )
        get.assert_not_called()

    @patch.object(assigned_access.requests, "get")
    def test_requires_server_verified_administrator(self, get):
        with patch.object(assigned_access, "_verify_windows_edition"):
            self._test_rejects_unprivileged_account(get)

    def _test_rejects_unprivileged_account(self, get):
        response = Mock()
        response.status_code = 403
        get.return_value.raise_for_status.side_effect = (
            assigned_access.requests.HTTPError(response=response)
        )

        with self.assertRaisesRegex(RuntimeError, "no tiene permisos"):
            assigned_access.cambiar_acceso_asignado(
                "Apply",
                "Prueba_Server",
                "student-token"
            )

    @patch.object(Path, "is_file", return_value=True)
    @patch.object(assigned_access, "_get_installation_paths")
    @patch.object(assigned_access.subprocess, "run")
    @patch.object(assigned_access.requests, "get")
    def test_reports_windows_policy_failure_without_success_fallback(
        self,
        get,
        run,
        get_paths,
        _file_exists
    ):
        with patch.object(assigned_access, "_verify_windows_edition"):
            self._test_windows_policy_failure(get, run, get_paths)

    def _test_windows_policy_failure(self, get, run, get_paths):
        get.return_value.raise_for_status.return_value = None
        run.return_value.returncode = 1
        run.return_value.stderr = "No hay administrador de recuperación."
        get_paths.return_value = (
            Path(r"C:\LabMonitor\Tools\ConfigureAssignedAccess.ps1"),
            Path(r"C:\LabMonitor\Student\LabMonitorStudent.exe")
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "No hay administrador de recuperación"
        ):
            assigned_access.cambiar_acceso_asignado(
                "Apply",
                "Prueba_Server",
                "admin-session-token"
            )

    @patch.object(assigned_access.requests, "get")
    def test_rejects_non_windows_hosts(self, get):
        with patch.object(assigned_access, "IS_WINDOWS", False):
            with self.assertRaisesRegex(RuntimeError, "solo se puede"):
                assigned_access.cambiar_acceso_asignado(
                    "Apply",
                    "Prueba_Server",
                    "admin-session-token"
                )
        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
