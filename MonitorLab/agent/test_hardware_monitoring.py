import tempfile
import unittest
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import hardware
import local_database
from local_monitor import comparar_inventario


def componente(tipo, identificador, modelo):
    return {
        "component_type": tipo,
        "hardware_identifier": identificador,
        "manufacturer": "Fabricante",
        "model": modelo,
        "serial_number": f"SERIE-{identificador}"
    }


def inventario(componentes, tipos, completo=False):
    return {
        "components": componentes,
        "complete": completo,
        "complete_types": tipos,
        "errors": []
    }


class HardwareMonitoringTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_db_path = local_database.DB_PATH
        local_database.DB_PATH = (
            Path(self.temp_dir.name) / "labmonitor_local.db"
        )
        self.connect_patch = patch.object(
            local_database,
            "conectar",
            side_effect=self.connect_and_close
        )
        self.monitor_connect_patch = patch(
            "local_monitor.conectar",
            side_effect=self.connect_and_close
        )
        self.connect_patch.start()
        self.monitor_connect_patch.start()

    def tearDown(self):
        self.monitor_connect_patch.stop()
        self.connect_patch.stop()
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

    def test_partial_scan_keeps_unqueried_hardware_active(self):
        ram = componente("ram", "RAM-1", "8 GB")
        teclado = componente("keyboard", "KEY-1", "Teclado USB")

        self.assertTrue(comparar_inventario(
            inventario([ram, teclado], ["ram", "keyboard"], True)
        ))

        parcial = inventario([], ["ram"])
        self.assertTrue(comparar_inventario(parcial))
        self.assertTrue(comparar_inventario(parcial))

        estado = {
            (fila["component_type"], fila["hardware_identifier"]):
                fila["status"]
            for fila in local_database.obtener_inventario_local()
        }
        pendientes = local_database.obtener_pendientes()

        self.assertEqual(estado[("ram", "RAM-1")], "removed")
        self.assertEqual(estado[("keyboard", "KEY-1")], "active")
        self.assertEqual(
            [evento["event_type"] for evento in pendientes],
            ["DEVICE_DISCONNECTED"]
        )

    def test_detects_added_hardware_and_changed_component_data(self):
        gpu_original = componente("gpu", "GPU-1", "Modelo A")

        self.assertTrue(comparar_inventario(
            inventario([gpu_original], ["gpu"], True)
        ))

        gpu_modificada = componente("gpu", "GPU-1", "Modelo B")
        gpu_nueva = componente("gpu", "GPU-2", "Modelo C")

        self.assertTrue(comparar_inventario(
            inventario(
                [gpu_modificada, gpu_nueva],
                ["gpu"],
                False
            )
        ))

        pendientes = local_database.obtener_pendientes()
        self.assertEqual(
            {evento["event_type"] for evento in pendientes},
            {"HARDWARE_CHANGED", "HARDWARE_ADDED"}
        )

    def test_wmi_inventory_accepts_missing_ram_capacity(self):
        sistema = SimpleNamespace(
            Win32_Processor=lambda: [
                SimpleNamespace(
                    ProcessorId="CPU-ID-1",
                    DeviceID="CPU0",
                    Manufacturer="Fabricante",
                    Name="Procesador virtual"
                )
            ],
            Win32_BaseBoard=lambda: [
                SimpleNamespace(
                    Manufacturer="Fabricante",
                    Product="Tarjeta virtual",
                    SerialNumber="BOARD-1"
                )
            ],
            Win32_PhysicalMemory=lambda: [
                SimpleNamespace(
                    SerialNumber="RAM-1",
                    Capacity=None,
                    Manufacturer="Fabricante",
                    Tag="DIMM0"
                )
            ],
            Win32_VideoController=lambda: [
                SimpleNamespace(
                    Name="GPU virtual",
                    PNPDeviceID="GPU-1"
                )
            ],
            Win32_DiskDrive=lambda: [
                SimpleNamespace(
                    Manufacturer="Fabricante",
                    Model="Disco virtual",
                    SerialNumber="DISK-1",
                    PNPDeviceID="DISK-1"
                )
            ],
            Win32_PointingDevice=lambda: [],
            Win32_Keyboard=lambda: [
                SimpleNamespace(
                    Name="Teclado virtual",
                    PNPDeviceID="KEY-1"
                )
            ],
            Win32_NetworkAdapter=lambda: [
                SimpleNamespace(
                    PhysicalAdapter=True,
                    MACAddress="00:11:22:33:44:55",
                    Manufacturer="Fabricante",
                    Name="Red virtual",
                    PNPDeviceID="NET-1"
                )
            ]
        )

        with patch.object(hardware.wmi, "WMI", return_value=sistema):
            resultado = hardware.obtener_inventario()

        self.assertTrue(resultado["complete"], resultado)
        self.assertEqual(
            set(resultado["complete_types"]),
            set(hardware.TIPOS_HARDWARE)
        )
        ram = next(
            elemento
            for elemento in resultado["components"]
            if elemento["component_type"] == "ram"
        )
        self.assertIsNone(ram["model"])


if __name__ == "__main__":
    unittest.main()
