"""
Synthetic demonstration and performance-test data. NEVER run against a production database:
it refuses unless DJANGO_DEBUG=true or --i-understand-this-is-not-production is given.
All names and numbers are invented.
"""

import datetime
import random
from decimal import Decimal

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.patients.services import new_mrn
from apps.core.context import ActorContext
from apps.inventory.models import Item, Supplier
from apps.inventory.services import receive_purchase
from apps.patients.models import Patient

GIVEN_F = ["Almaz", "Tigist", "Hirut", "Meron", "Selam", "Bethlehem", "Hana", "Mekdes", "Liya", "Saba", "Aster",
           "Genet", "Tsion", "Rahel", "Lensa", "Chaltu", "Ayantu", "Sifan", "Hawi", "Kidist", "Eden", "Feven"]
GIVEN_M = ["Abebe", "Kebede", "Dawit", "Yonas", "Bereket", "Henok", "Samuel", "Tewodros", "Biruk", "Natnael",
           "Getachew", "Mulugeta", "Lemma", "Gemechu", "Tolosa", "Chala", "Abdi", "Ahmed", "Yared", "Ermias"]
FATHERS = GIVEN_M + ["Tadesse", "Alemu", "Girma", "Haile", "Wolde", "Desta", "Assefa", "Mengistu", "Bekele",
                     "Tesfaye", "Negash", "Fikre", "Gudeta", "Dinsa"]
CITIES = [("Oromia", "Adama"), ("Addis Ababa", "Addis Ababa"), ("Sidama", "Hawassa"), ("Amhara", "Bahir Dar"),
          ("Oromia", "Bishoftu"), ("Dire Dawa", "Dire Dawa"), ("Tigray", "Mekelle"), ("Oromia", "Jimma")]

# username, first, last, role, department code
# A dental clinic: no general doctor, nurse, laboratory or pharmacy accounts.
DEMO_STAFF = [("reception", "Hirut", "Desta", "receptionist", "reception"),
              ("cashier", "Liya", "Tadesse", "cashier", "finance"),
              ("store", "Yonas", "Fikre", "inventory_manager", "pharmacy"),
              ("manager", "Rahel", "Wolde", "clinic_admin", "administration"),
              ("director", "Tewodros", "Bekele", "clinic_director", "administration"),
              # Dental team
              ("dentist", "Selam", "Tesfaye", "dentist", "dental"),
              ("dentist2", "Natnael", "Assefa", "dentist", "dental"),
              ("assistant", "Hawi", "Gudeta", "dental_assistant", "dental"),
              ("hygienist", "Eden", "Mengistu", "dental_hygienist", "dental"),
              ("dentaltech", "Biruk", "Lemma", "dental_technician", "dental"),
              ("imaging", "Kidist", "Haile", "imaging_staff", "dental")]
DEMO_PASSWORD = "Demo-Clinic-2026"


# Plausible demo prices in ETB, so a plan or invoice looks believable. Synthetic: not a price list.
DEMO_DENTAL_PRICES = {
    "EX-EMG": 300, "EX-NEW": 500, "EX-REV": 300, "IMG-PA": 300, "IMG-BW": 400, "IMG-OPG": 1200,
    "PR-SCL": 1200, "PR-FLU": 500, "PR-SEAL": 600, "PE-EXAM": 600, "PE-SRP": 1500,
    "RS-TEMP": 500, "RS-GIC": 1000, "RS-COMP1": 1500, "RS-COMP2": 2500,
    "EN-PULP": 2500, "EN-RCT": 7000, "EN-RERCT": 9000, "OS-EXT": 1000, "OS-SEXT": 3500,
    "PS-CRPREP": 9000, "PS-CRFIT": 3000, "PS-BRIDGE": 25000, "PS-DENT": 15000, "PS-DREP": 2000,
    "IM-CONS": 800, "CO-WHITE": 6000,
    "OR-CONS": 800, "OR-REC": 2500, "OR-BOND": 12000, "OR-ADJ": 1200, "OR-DEBOND": 3000, "OR-RET": 4000,
}


def set_demo_dental_prices(only_unpriced: bool) -> int:
    from apps.dental.models import DentalProcedure

    changed = 0
    for code, price in DEMO_DENTAL_PRICES.items():
        qs = DentalProcedure.objects.filter(code=code)
        if only_unpriced:
            qs = qs.filter(price=0)
        changed += qs.update(price=Decimal(price))
    return changed


class Command(BaseCommand):
    help = "Create synthetic demo data (patients, staff, stock). Development and testing only."

    def add_arguments(self, parser):
        parser.add_argument("--patients", type=int, default=200)
        parser.add_argument("--with-staff", action="store_true", help=f"Create demo staff (password {DEMO_PASSWORD})")
        parser.add_argument("--with-stock", action="store_true")
        parser.add_argument("--i-understand-this-is-not-production", action="store_true", dest="force")
        parser.add_argument("--seed", type=int, default=2026)

    def handle(self, *args, patients, with_staff, with_stock, force, seed, **options):
        if not (settings.DEBUG or force):
            raise CommandError("Refusing to create demo data outside development. See --help.")
        rng = random.Random(seed)
        call_command("load_starter_catalog", verbosity=0)
        call_command("load_dental_catalog", verbosity=0)
        self._dental_prices(rng)
        actor = User.objects.filter(is_active=True).order_by("created_at").first()
        if actor is None:
            raise CommandError("Create an administrator first (manage.py bootstrap_admin).")
        if with_staff:
            self._staff()
        if with_stock:
            self._stock(actor, rng)
        if patients:
            self._patients(patients, actor, rng)

    def _dental_prices(self, rng):
        """Demo prices for the starter procedures, which ship at 0 for the clinic to set. Synthetic only."""
        set_demo_dental_prices(only_unpriced=True)

    def _staff(self):
        from apps.accounts.models import Department, Room

        dental, _ = Department.objects.get_or_create(code="dental", defaults={"name": "Dental", "receives_triage": True})
        for order, name in enumerate(["Chair 1", "Chair 2", "Chair 3"]):
            Room.objects.get_or_create(name=name, defaults={"department": dental, "sort_order": order})

        for username, first, last, role, dept in DEMO_STAFF:
            user, created = User.objects.get_or_create(
                username=username, defaults={"first_name": first, "last_name": last, "must_change_password": False,
                                             "job_title": Role.objects.get(code=role).name})
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save()
                user.roles.add(Role.objects.get(code=role))
            if user.department_id is None:
                User.objects.filter(pk=user.pk).update(department=Department.objects.filter(code=dept).first(),
                                                       start_date=datetime.date(2025, 9, 11))
        self.stdout.write(f"Demo staff ready (password: {DEMO_PASSWORD}).")

    # code, name, category, unit, pack unit, units per pack, reorder level, selling price (synthetic demo values)
    DENTAL_ITEMS = [
        ("DEMO-COMP-A2", "Composite resin A2 (4 g syringe)", "restorative", "syringe", "box", 5, 4, 650),
        ("DEMO-BOND", "Bonding agent (5 ml)", "restorative", "bottle", "", None, 2, 900),
        ("DEMO-ETCH", "Etching gel 37% (3 ml)", "restorative", "syringe", "box", 3, 3, 250),
        ("DEMO-GIC", "Glass ionomer cement kit", "restorative", "kit", "", None, 1, 1800),
        ("DEMO-LIDO", "Lidocaine 2% with adrenaline (1.8 ml cartridge)", "anaesthetic", "cartridge", "box", 50, 50, 35),
        ("DEMO-NEEDLE", "Dental needle 27G short", "anaesthetic", "needle", "box", 100, 100, 8),
        ("DEMO-GP", "Gutta-percha points (assorted)", "endodontic", "box", "", None, 2, 450),
        ("DEMO-ALG", "Alginate impression material (450 g)", "impression", "bag", "", None, 2, 700),
        ("DEMO-GLOVE", "Examination gloves (pair)", "infection_control", "pair", "box", 50, 100, 6),
        ("DEMO-POUCH", "Sterilisation pouches", "sterilisation", "pouch", "box", 200, 200, 2),
        ("DEMO-MIRROR", "Mouth mirror", "instrument", "piece", "", None, 10, 120),
    ]

    def _dental_items(self):
        """Synthetic dental supplies, so procedure records can list materials in the demo."""
        for code, name, category, unit, pack, per_pack, reorder, price in self.DENTAL_ITEMS:
            Item.objects.get_or_create(code=code, defaults=dict(
                name=name, category=category, unit=unit, pack_unit=pack,
                units_per_pack=Decimal(per_pack) if per_pack else None, reorder_level=Decimal(reorder),
                selling_price=Decimal(price)))

    @transaction.atomic
    def _stock(self, actor, rng):
        self._dental_items()
        supplier, _ = Supplier.objects.get_or_create(name="Demo Pharmaceutical Supplier PLC")
        today = timezone.localdate()
        lines = []
        for item in Item.objects.filter(is_active=True):
            for n in range(2):
                lines.append({"item": item, "batch_number": f"D{today:%y%m}-{item.code}-{n}",
                              "expiry_date": today + datetime.timedelta(days=rng.choice([45, 200, 400, 720])),
                              "quantity": Decimal(rng.choice([40, 100, 250, 500])),
                              "unit_cost": (item.selling_price * Decimal("0.6")).quantize(Decimal("0.01"))})
        lines = [l for l in lines if not l["item"].batches.filter(batch_number=l["batch_number"]).exists()]
        if lines:
            receive_purchase(ActorContext(user=actor, user_agent="seed_demo"), supplier=supplier, purchase_date=today,
                             lines=lines, supplier_invoice_no="DEMO-001", notes="Synthetic demo stock")
        self.stdout.write(f"Demo stock received: {len(lines)} batches.")

    def _patients(self, count, actor, rng):
        batch = []
        for _ in range(count):
            sex = rng.choice(["female", "male"])
            region, city = rng.choice(CITIES)
            age_days = rng.randint(30, 85 * 365)
            batch.append(Patient(
                mrn=new_mrn(),
                first_name=rng.choice(GIVEN_F if sex == "female" else GIVEN_M), middle_name=rng.choice(FATHERS),
                last_name=rng.choice(FATHERS), sex=sex,
                birth_date=timezone.localdate() - datetime.timedelta(days=age_days),
                birth_date_estimated=rng.random() < 0.3, phone=f"09{rng.randint(10_000_000, 99_999_999)}",
                region=region, city=city, created_by=actor, updated_by=actor))
            if len(batch) == 1000:
                Patient.objects.bulk_create(batch)
                batch = []
        Patient.objects.bulk_create(batch)
        self.stdout.write(f"Created {count} synthetic patients (total {Patient.objects.count()}).")
