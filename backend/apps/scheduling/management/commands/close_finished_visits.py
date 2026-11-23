from django.core.management.base import BaseCommand

from apps.scheduling.completion import close_finished_visits


class Command(BaseCommand):
    help = ("Close visits where everything is finished, if the clinic switched this on "
            "(Clinic settings > Waiting list > Close finished visits automatically). Run by the mrs-visits timer.")

    def handle(self, *args, **options):
        closed = close_finished_visits()
        if options["verbosity"] > 1 or closed:
            self.stdout.write(f"Closed {len(closed)} finished visit(s).")
