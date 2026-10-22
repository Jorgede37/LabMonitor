from pathlib import Path
import tempfile
import unittest

from register import consumir_clave_inscripcion


class EnrollmentKeyFileTests(unittest.TestCase):
    def test_reads_and_deletes_key_file(self):
        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory) / "enrollment.txt"
            key_file.write_text(" one-time-code \n", encoding="utf-8")

            self.assertEqual(consumir_clave_inscripcion(key_file), "one-time-code")
            self.assertFalse(key_file.exists())

    def test_empty_file_is_deleted_and_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory) / "enrollment.txt"
            key_file.write_text("  \n", encoding="utf-8")

            with self.assertRaises(ValueError):
                consumir_clave_inscripcion(key_file)
            self.assertFalse(key_file.exists())


if __name__ == "__main__":
    unittest.main()
