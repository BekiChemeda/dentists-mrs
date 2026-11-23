import csv

from django.core.management.base import BaseCommand, CommandError

from apps.clinical.models import IcdCode


class Command(BaseCommand):
    help = "Load ICD-10 codes from a CSV file with columns: code,title. Existing codes are updated."

    def add_arguments(self, parser):
        parser.add_argument("csv_path")

    def handle(self, *args, csv_path, **options):
        count = 0
        try:
            with open(csv_path, newline="", encoding="utf-8-sig") as fh:
                for row in csv.DictReader(fh):
                    code, title = row["code"].strip().upper(), row["title"].strip()
                    if code and title:
                        IcdCode.objects.update_or_create(code=code, defaults={"title": title[:255]})
                        count += 1
        except (OSError, KeyError) as exc:
            raise CommandError(f"Cannot read {csv_path}: {exc}") from exc
        self.stdout.write(self.style.SUCCESS(f"Loaded {count} ICD-10 codes."))
