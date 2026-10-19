import threading
import time
import unittest
from unittest.mock import patch

import email_worker


class EmailWorkerTests(unittest.TestCase):
    def test_worker_starts_and_stops(self):
        recuperaciones = []
        detener = threading.Event()
        worker = threading.Thread(
            target=email_worker.iniciar_worker_email,
            args=(detener,)
        )

        with patch.object(
            email_worker,
            "recuperar_interrumpidos",
            side_effect=lambda: recuperaciones.append(True)
        ), patch.object(
            email_worker,
            "obtener_notificacion",
            return_value=None
        ):
            worker.start()

            limite = time.monotonic() + 2
            while (
                not email_worker.worker_correo_activo()
                or not recuperaciones
            ):
                self.assertLess(time.monotonic(), limite)
                time.sleep(0.01)

            self.assertEqual(recuperaciones, [True])

            detener.set()
            worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertFalse(email_worker.worker_correo_activo())


if __name__ == "__main__":
    unittest.main()
