from copy import deepcopy
from datetime import datetime, time
from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from openpyxl import Workbook

from courts.models import Court, Venue
from .dataset_import import DatasetError, build_objects, import_core, read_core
from .models import Payment, Reservation


def sample_data():
    created = datetime(2026, 1, 1, 9)
    return {
        "Users": [{"user_id": 1, "full_name": "Usuario sintético", "email": "test@cancha-lista.test",
                   "created_at": created}],
        "Venues": [{"venue_id": 1, "venue_name": "Arena", "city": "Barranquilla", "address": "Ficticia",
                    "deposit_percentage": .3, "is_active": True}],
        "Courts": [{"court_id": 101, "venue_id": 1, "court_name": "Cancha 1",
                    "price_per_hour": 120000, "is_active": True}],
        "CourtSchedule": [{"schedule_id": 5001, "court_id": 101, "day_of_week": 5,
                           "start_time": time(8), "end_time": time(22),
                           "slot_duration_minutes": 60, "is_active": True}],
        "Reservations": [{"reservation_id": 100001, "court_id": 101, "user_id": 1,
                          "reservation_date": datetime(2026, 1, 2), "start_time": time(10),
                          "end_time": time(11), "total_amount": 120000, "deposit_required": 36000,
                          "remaining_amount": 84000, "reservation_status": "CONFIRMED",
                          "created_at": created, "hold_expires_at": None, "cancelled_at": None,
                          "data_source": "SYNTHETIC"}],
        "Payments": [{"payment_id": 800001, "reservation_id": 100001, "amount": 36000,
                      "payment_type": "DEPOSIT", "payment_status": "APPROVED", "provider": "SIMULATED",
                      "transaction_reference": "SIM-2026-800001", "created_at": created,
                      "approved_at": created}],
    }


class DatasetImportTests(TestCase):
    def setUp(self):
        self.data = sample_data()
        self.admin = User.objects.create_user(username="admin", password="existing", is_staff=True)

    def test_import_preserves_admin_maps_users_and_keeps_dates(self):
        counts = import_core(self.data, build_objects(self.data))
        self.assertEqual(counts["Reservation"], 1)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("existing"))
        reservation = Reservation.objects.get()
        self.assertNotEqual(reservation.user_id, self.admin.pk)
        self.assertEqual(reservation.user.username, "synthetic_v1_1_0001")
        self.assertFalse(reservation.user.has_usable_password())
        self.assertFalse(reservation.user.is_active)
        self.assertEqual(reservation.created_at, timezone.make_aware(datetime(2026, 1, 1, 9)))
        self.assertEqual(Payment.objects.get().created_at, reservation.created_at)
        self.assertEqual(Venue.objects.get().deposit_percentage, Decimal("30.00"))
        self.assertEqual(reservation.data_source, "SYNTHETIC")

    def test_second_import_creates_nothing_and_does_not_reset_expiration(self):
        self.data["Reservations"][0].update(reservation_status="PENDING_PAYMENT",
                                              hold_expires_at=datetime(2026, 1, 1, 9, 15))
        self.data["Payments"] = []
        import_core(self.data, build_objects(self.data))
        Reservation.objects.update(reservation_status="EXPIRED")
        counts = import_core(self.data, build_objects(self.data))
        self.assertEqual(sum(counts.values()), 0)
        self.assertEqual(Reservation.objects.get().reservation_status, "EXPIRED")

    def test_collision_rolls_back_every_insert(self):
        import_core(self.data, build_objects(self.data))
        changed = deepcopy(self.data)
        changed["Users"].append({"user_id": 2, "full_name": "Nuevo", "email": "new@test.test",
                                 "created_at": datetime(2026, 1, 1)})
        changed["Payments"][0]["amount"] = 40000
        with self.assertRaises(DatasetError):
            import_core(changed, build_objects(changed))
        self.assertFalse(User.objects.filter(username="synthetic_v1_1_0002").exists())
        self.assertEqual(Payment.objects.get().amount, Decimal("36000"))

    def test_existing_venue_is_not_overwritten(self):
        Venue.objects.create(pk=1, venue_name="Real", address="Real")
        with self.assertRaises(DatasetError):
            import_core(self.data, build_objects(self.data))
        self.assertEqual(Venue.objects.get().venue_name, "Real")
        self.assertEqual(User.objects.count(), 1)
        self.assertFalse(Court.objects.exists())

    def test_invalid_relations_states_amounts_and_overlap_rejected(self):
        for mutation in ("relation", "source", "money", "overlap", "payment", "weekday", "status"):
            data = deepcopy(self.data)
            if mutation == "relation":
                data["Reservations"][0]["court_id"] = 999
            elif mutation == "source":
                data["Reservations"][0]["data_source"] = "SYSTEM"
            elif mutation == "money":
                data["Reservations"][0]["remaining_amount"] = 1
            elif mutation == "overlap":
                other = dict(data["Reservations"][0], reservation_id=100002,
                             start_time=time(10, 30), end_time=time(11, 30),
                             reservation_status="PENDING_PAYMENT", hold_expires_at=datetime(2026, 1, 1, 9, 15))
                data["Reservations"].append(other)
            elif mutation == "payment":
                data["Payments"][0]["payment_status"] = "REJECTED"
            elif mutation == "weekday":
                data["CourtSchedule"][0]["day_of_week"] = 0
            else:
                data["Reservations"][0]["reservation_status"] = "UNKNOWN"
            with self.subTest(mutation=mutation), self.assertRaises(DatasetError):
                build_objects(data)

    def test_zip_dry_run_is_read_only_and_duplicate_ids_are_rejected(self):
        with TemporaryDirectory() as folder:
            excel = Path(folder) / "Cancha_Lista_Core_v1_1_Ajustado.xlsx"
            workbook = Workbook()
            workbook.remove(workbook.active)
            for name, rows in self.data.items():
                sheet = workbook.create_sheet(name)
                sheet.append(list(rows[0]))
                for row in rows:
                    sheet.append(list(row.values()))
            workbook.save(excel)
            archive = Path(folder) / "dataset.zip"
            with ZipFile(archive, "w") as zipped:
                zipped.write(excel, excel.name)
            parsed = read_core(archive)
            self.assertEqual(len(parsed["Reservations"]), 1)
            call_command("importar_dataset", str(archive), stdout=StringIO())
            self.assertFalse(Reservation.objects.exists())
            self.assertEqual(User.objects.count(), 1)
            workbook["Users"].append(list(self.data["Users"][0].values()))
            workbook.save(excel)
            with self.assertRaises(DatasetError):
                read_core(excel)
