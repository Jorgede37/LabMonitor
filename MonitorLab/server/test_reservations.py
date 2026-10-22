import unittest
from datetime import date, datetime, time, timedelta, timezone

from fastapi import HTTPException
from pydantic import ValidationError

from app.dependencies import (
    docentes_o_administradores,
    solo_administradores,
    solo_docentes_aprobados
)
from app.routes import reservations
from app.routes.admin import convertir_fechas


class ReservationRulesTests(unittest.TestCase):
    def test_schedule_contains_nine_one_hour_slots(self):
        slots = reservations.horarios_disponibles()

        self.assertEqual(len(slots), 9)
        self.assertEqual(slots[0], (time(7), time(8)))
        self.assertEqual(slots[-1], (time(15), time(16)))

    def test_sunday_is_not_reservable(self):
        with self.assertRaises(HTTPException) as error:
            reservations.validar_fecha_reserva(date(2026, 10, 25))

        self.assertEqual(error.exception.status_code, 422)
        self.assertIn("domingos", error.exception.detail)

    def test_reservation_requires_a_subject(self):
        with self.assertRaises(ValidationError):
            reservations.ReservaCrear(
                laboratory_id=1,
                reservation_date="2026-10-26",
                start_time="07:00",
                end_time="09:00",
                subject="   "
            )

    def test_reservation_request_accepts_multiple_hours(self):
        data = reservations.ReservaCrear(
            laboratory_id=1,
            reservation_date="2026-10-26",
            start_time="07:00",
            end_time="09:00",
            subject="Matemáticas"
        )
        self.assertEqual(data.end_time, time(9))

    def test_recurring_admin_reservation_requires_selected_days(self):
        data = reservations.ReservaRecurrente(
            laboratory_id=3,
            teacher_user_id=14,
            start_date="2026-10-26",
            end_date="2026-11-06",
            start_time="07:00",
            end_time="09:00",
            subject="Matemáticas",
            weekdays=[0, 2, 4]
        )
        self.assertEqual(data.weekdays, [0, 2, 4])

    def test_recurring_dates_include_only_selected_weekdays(self):
        hoy = datetime.now(reservations.ZONA_LOCAL).date()
        dias_hasta_domingo = (6 - hoy.weekday()) % 7
        domingo = hoy + timedelta(
            days=dias_hasta_domingo if dias_hasta_domingo else 7
        )
        self.assertEqual(
            reservations.fechas_recurrentes(
                domingo,
                domingo + timedelta(days=6),
                [0, 2, 5]
            ),
            [
                domingo + timedelta(days=1),
                domingo + timedelta(days=3),
                domingo + timedelta(days=6)
            ]
        )

    def test_reservation_time_must_be_a_valid_hour_block(self):
        for invalid_time in (time(6), time(7, 30), time(15, 59), time(16)):
            with self.subTest(invalid_time=invalid_time):
                with self.assertRaises(HTTPException):
                    reservations.validar_hora_reserva(invalid_time)

        self.assertEqual(
            reservations.validar_hora_reserva(time(15)),
            time(15)
        )

    def test_reservation_can_span_consecutive_hours(self):
        self.assertEqual(
            reservations.validar_intervalo_reserva(time(7), time(9)),
            (time(7), time(9))
        )
        self.assertEqual(
            reservations.validar_intervalo_reserva(time(14), time(16)),
            (time(14), time(16))
        )

    def test_reservation_rejects_non_hour_end_or_out_of_bounds(self):
        invalid_intervals = (
            (time(7), time(7)),
            (time(7), time(8, 30)),
            (time(7), time(17)),
            (time(15), time(17)),
        )
        for start, end in invalid_intervals:
            with self.subTest(start=start, end=end):
                with self.assertRaises(HTTPException):
                    reservations.validar_intervalo_reserva(start, end)

    def test_reservation_overlap_is_interval_based(self):
        self.assertTrue(
            reservations.intervalos_se_solapan(
                time(8), time(10), time(9), time(11)
            )
        )
        self.assertFalse(
            reservations.intervalos_se_solapan(
                time(8), time(10), time(10), time(11)
            )
        )

    def test_reservation_overlap_query_is_scoped_to_laboratory(self):
        class Result:
            def scalar_one(self):
                return 0

            def first(self):
                return None

        class Connection:
            statements = []

            def execute(self, statement, parameters):
                self.statements.append((str(statement), parameters))
                return Result()

        connection = Connection()
        reservations.comprobar_sin_solapamiento(
            connection,
            8,
            date(2026, 10, 26),
            time(7),
            time(9)
        )
        query, parameters = connection.statements[-1]
        self.assertIn("laboratory_id = :laboratory_id", query)
        self.assertEqual(parameters["laboratory_id"], 8)

    def test_teacher_cancellation_is_scoped_to_the_owner(self):
        class Result:
            def first(self):
                return (21,)

        class Connection:
            statement = ""
            parameters = {}

            def execute(self, statement, parameters):
                self.statement = str(statement)
                self.parameters = parameters
                return Result()

        connection = Connection()
        reservations.cancelar_reserva(
            connection,
            21,
            {"id": 14, "role": "teacher"},
            propietario_requerido=True
        )
        self.assertIn("teacher_user_id = :teacher_user_id", connection.statement)
        self.assertEqual(connection.parameters["teacher_user_id"], 14)
        self.assertIn("status = 'cancelled'", connection.statement)

    def test_admin_may_access_booking_availability(self):
        usuario = {"role": "admin", "teacher_approved": False}

        self.assertIs(docentes_o_administradores(usuario), usuario)

    def test_only_admins_can_create_laboratories(self):
        administrador = {"role": "admin"}
        self.assertIs(solo_administradores(administrador), administrador)

        for role in ("teacher", "student"):
            with self.subTest(role=role):
                with self.assertRaises(HTTPException) as error:
                    solo_administradores({"role": role})
                self.assertEqual(error.exception.status_code, 403)

    def test_pending_teacher_cannot_book_or_view_availability(self):
        usuario = {"role": "teacher", "teacher_approved": False}

        with self.assertRaises(HTTPException) as error:
            docentes_o_administradores(usuario)
        self.assertEqual(error.exception.status_code, 403)

        with self.assertRaises(HTTPException) as error:
            solo_docentes_aprobados(usuario)
        self.assertEqual(error.exception.status_code, 403)

    def test_database_event_time_is_serialized_as_utc(self):
        result = convertir_fechas({
            "detected_at": datetime(2026, 10, 19, 21, 39, 58)
        })
        self.assertEqual(
            result["detected_at"],
            "2026-10-19T21:39:58Z"
        )

        horario_local = datetime(
            2026, 10, 19, 15, 39, 58,
            tzinfo=timezone(timedelta(hours=-6))
        )
        result = convertir_fechas({"detected_at": horario_local})
        self.assertEqual(
            result["detected_at"],
            "2026-10-19T21:39:58Z"
        )


if __name__ == "__main__":
    unittest.main()