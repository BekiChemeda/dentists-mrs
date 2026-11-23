"""Check that every dental image in the database has its file and that the file's SHA-256 matches (ADR 0007)."""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Verify dental image files against their database records."

    def handle(self, *args, **options):
        from apps.dental.services.imaging import storage_usage, verify_all

        problems = verify_all()
        usage = storage_usage()
        if problems:
            for p in problems[:200]:
                self.stderr.write(p)
            raise CommandError(f"{len(problems)} dental image problem(s) found.")
        if options["verbosity"]:
            self.stdout.write(f"Dental images OK: {usage['files']} files, {usage['bytes'] / 1e6:.1f} MB in {usage['path']}.")
