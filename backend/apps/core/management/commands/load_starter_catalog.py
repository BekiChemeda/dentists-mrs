from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.billing.models import ServicePrice
from apps.inventory.models import Item
from apps.laboratory.models import LabReferenceRange, LabTest

# Example prices in ETB. Every clinic must review and set its own prices before use.
SERVICES = [
    ("CONSULT", "General consultation", "consultation", "200"),
    ("FOLLOWUP", "Follow-up consultation", "consultation", "100"),
    ("DRESS", "Wound dressing", "procedure", "150"),
    ("INJ", "Injection administration", "procedure", "50"),
    ("SUTURE", "Suturing (minor)", "procedure", "400"),
    ("CERT", "Medical certificate", "other", "100"),
]

LAB_TESTS = [
    # code, name, category, specimen, type, unit, low, high, ref_text, choices, normal, price
    ("HGB", "Haemoglobin", "Haematology", "Whole blood (EDTA)", "numeric", "g/dL", "12", "17", "", "", "", "80"),
    ("WBC", "White blood cell count", "Haematology", "Whole blood (EDTA)", "numeric", "×10³/µL", "4", "11", "", "", "",
     "80"),
    ("PLT", "Platelet count", "Haematology", "Whole blood (EDTA)", "numeric", "×10³/µL", "150", "450", "", "", "", "80"),
    ("ESR", "Erythrocyte sedimentation rate", "Haematology", "Whole blood", "numeric", "mm/hr", "0", "20", "", "", "",
     "60"),
    ("BF", "Blood film for malaria", "Parasitology", "Whole blood", "choice", "", None, None, "",
     "Negative,P. falciparum,P. vivax,Mixed infection", "Negative", "70"),
    ("RBS", "Random blood sugar", "Chemistry", "Capillary/venous blood", "numeric", "mg/dL", "70", "140", "", "", "",
     "60"),
    ("FBS", "Fasting blood sugar", "Chemistry", "Venous blood", "numeric", "mg/dL", "70", "100", "", "", "", "60"),
    ("CREA", "Creatinine", "Chemistry", "Serum", "numeric", "mg/dL", "0.6", "1.3", "", "", "", "150"),
    ("ALT", "ALT (SGPT)", "Chemistry", "Serum", "numeric", "U/L", "0", "40", "", "", "", "150"),
    ("STOOL", "Stool examination", "Parasitology", "Stool", "text", "", None, None, "No ova or parasites seen", "", "",
     "60"),
    ("UA", "Urinalysis", "Urine", "Urine", "text", "", None, None, "", "", "", "80"),
    ("HCG", "Urine pregnancy test (hCG)", "Serology", "Urine", "choice", "", None, None, "", "Negative,Positive",
     "Negative", "80"),
    ("HIV", "HIV rapid test", "Serology", "Whole blood", "choice", "", None, None, "", "Non-reactive,Reactive",
     "Non-reactive", "0"),
    ("HPYL", "H. pylori stool antigen", "Serology", "Stool", "choice", "", None, None, "", "Negative,Positive",
     "Negative", "250"),
    ("WIDAL", "Widal test", "Serology", "Serum", "text", "", None, None, "Interpret with caution", "", "", "150"),
    ("BG", "Blood group and Rh", "Haematology", "Whole blood", "choice", "", None, None, "",
     "A+,A-,B+,B-,AB+,AB-,O+,O-", "", "80"),
]

# Age- and sex-specific lower limits for haemoglobin: WHO anaemia thresholds (g/dL), "Haemoglobin
# concentrations for the diagnosis of anaemia and assessment of severity", WHO 2011
# (WHO/NMH/NHD/MNM/11.1). Upper limits keep the test default. Critical limits are deliberately left
# empty: each laboratory director sets them.
HGB_RANGES = [
    # sex, age_min_days, age_max_days, low, high
    ("", 183, 1826, "11.0", None),      # 6-59 months
    ("", 1826, 4383, "11.5", None),     # 5-11 years
    ("", 4383, 5479, "12.0", None),     # 12-14 years
    ("female", 5479, None, "12.0", "17"),  # 15 years and over, non-pregnant women
    ("male", 5479, None, "13.0", "17"),    # 15 years and over, men
]

MEDICINES = [
    # code, name, generic, form, strength, unit, reorder, price
    ("AMOX500", "Amoxicillin", "Amoxicillin", "Capsule", "500 mg", "capsule", "200", "3.00"),
    ("PCM500", "Paracetamol", "Paracetamol", "Tablet", "500 mg", "tablet", "300", "0.50"),
    ("AL2012", "Artemether/Lumefantrine", "Artemether + Lumefantrine", "Tablet", "20/120 mg", "tablet", "120", "6.00"),
    ("MET500", "Metformin", "Metformin", "Tablet", "500 mg", "tablet", "200", "1.50"),
    ("AML5", "Amlodipine", "Amlodipine", "Tablet", "5 mg", "tablet", "200", "1.20"),
    ("OME20", "Omeprazole", "Omeprazole", "Capsule", "20 mg", "capsule", "150", "2.00"),
    ("CIP500", "Ciprofloxacin", "Ciprofloxacin", "Tablet", "500 mg", "tablet", "100", "2.50"),
    ("MTZ250", "Metronidazole", "Metronidazole", "Tablet", "250 mg", "tablet", "200", "1.00"),
    ("IBU400", "Ibuprofen", "Ibuprofen", "Tablet", "400 mg", "tablet", "200", "1.00"),
    ("ALB400", "Albendazole", "Albendazole", "Tablet", "400 mg", "tablet", "50", "5.00"),
    ("COT960", "Cotrimoxazole", "Sulfamethoxazole + Trimethoprim", "Tablet", "960 mg", "tablet", "100", "1.50"),
    ("ORS", "Oral rehydration salts", "ORS", "Sachet", "20.5 g/L", "sachet", "50", "8.00"),
    ("CTX1G", "Ceftriaxone", "Ceftriaxone", "Injection", "1 g", "vial", "30", "45.00"),
    ("SALB", "Salbutamol inhaler", "Salbutamol", "Inhaler", "100 mcg/dose", "inhaler", "10", "180.00"),
    ("DZP5", "Diazepam", "Diazepam", "Tablet", "5 mg", "tablet", "20", "1.50"),
]

# code: (route, therapeutic category, allergy groups, controlled class, warnings)
MEDICINE_DETAILS = {
    "AMOX500": ("oral", "Antibiotic", "Penicillin, Beta-lactam", "", ""),
    "PCM500": ("oral", "Analgesic", "", "", "Do not exceed 4 g a day"),
    "AL2012": ("oral", "Antimalarial", "", "", "Take with food or milk"),
    "MET500": ("oral", "Antidiabetic", "", "", "Take with meals"),
    "AML5": ("oral", "Antihypertensive", "", "", ""),
    "OME20": ("oral", "Antiulcer", "", "", "Take before food"),
    "CIP500": ("oral", "Antibiotic", "Fluoroquinolone", "", ""),
    "MTZ250": ("oral", "Antibiotic / antiprotozoal", "", "", "Avoid alcohol"),
    "IBU400": ("oral", "Analgesic (NSAID)", "NSAID", "", "Take with food"),
    "ALB400": ("oral", "Anthelmintic", "", "", ""),
    "COT960": ("oral", "Antibiotic", "Sulfonamide, Sulfa", "", ""),
    "ORS": ("oral", "Rehydration", "", "", ""),
    "CTX1G": ("IV/IM", "Antibiotic", "Cephalosporin, Beta-lactam", "", ""),
    "SALB": ("inhaled", "Bronchodilator", "", "", ""),
    # Diazepam is a psychotropic substance; prescribing and dispensing follow EFDA Directive 1121/2025.
    "DZP5": ("oral", "Anxiolytic", "Benzodiazepine", "psychotropic", "May cause drowsiness; avoid alcohol"),
}


def dec(v):
    return Decimal(v) if v is not None else None


class Command(BaseCommand):
    help = "Create a starter price list, laboratory test catalogue and medicine catalogue (no stock). Idempotent."

    @transaction.atomic
    def handle(self, *args, **options):
        for code, name, cat, price in SERVICES:
            ServicePrice.objects.get_or_create(code=code, defaults={"name": name, "category": cat, "price": dec(price)})
        for (code, name, cat, spec, rtype, unit, low, high, ref_text, choices, normal, price) in LAB_TESTS:
            LabTest.objects.get_or_create(code=code, defaults=dict(
                name=name, category=cat, specimen_type=spec, result_type=rtype, unit=unit, ref_low=dec(low),
                ref_high=dec(high), ref_text=ref_text, choices=choices, normal_choice=normal, price=dec(price)))
        hgb = LabTest.objects.filter(code="HGB").first()
        if hgb and not hgb.ranges.exists():
            for sex, lo_days, hi_days, low, high in HGB_RANGES:
                LabReferenceRange.objects.create(test=hgb, sex=sex, age_min_days=lo_days, age_max_days=hi_days,
                                                 ref_low=dec(low), ref_high=dec(high))
        for code, name, generic, form, strength, unit, reorder, price in MEDICINES:
            route, category, groups, controlled, warnings = MEDICINE_DETAILS.get(code, ("", "", "", "", ""))
            item, created = Item.objects.get_or_create(code=code, defaults=dict(
                name=name, generic_name=generic, category=Item.Category.MEDICINE, dosage_form=form, strength=strength,
                unit=unit, reorder_level=dec(reorder), selling_price=dec(price), route=route,
                therapeutic_category=category, allergy_groups=groups, controlled_class=controlled, warnings=warnings))
            if not created and not item.route:  # fill details added after the first install, never overwrite
                Item.objects.filter(pk=item.pk).update(route=route, therapeutic_category=category,
                                                       allergy_groups=item.allergy_groups or groups,
                                                       warnings=item.warnings or warnings)
        self.stdout.write(self.style.SUCCESS(
            f"Catalogue ready: {ServicePrice.objects.count()} services, {LabTest.objects.count()} lab tests, "
            f"{Item.objects.count()} items. Review all prices before use."))
