"""
Protection against two people overwriting each other's edits ("lost updates").

How it works
------------
* Each editable record carries a `row_version` number.
* A PostgreSQL trigger adds 1 to it whenever one of the record's *editable* columns really changes,
  whatever code made the change (a form, a script, a bulk update). Columns that change on their own,
  such as a user's last sign-in time, do not count, so they never cause false conflicts.
* The web app sends back the `row_version` it loaded (in the body, or an `If-Match` header). If the
  record has changed since, the save is refused with HTTP 409 `edit_conflict`, naming who saved the
  newer version and when. Nothing is overwritten; the person reloads and re-applies their change.

Changes the trigger cannot see (permissions or roles held in link tables) call `bump_version`.

Requests that send no version (older scripts) are still accepted, as before; the web app always
sends one.
"""

from contextlib import contextmanager

from django.db import models, transaction
from django.shortcuts import get_object_or_404

from .exceptions import ConflictError

FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION mrs_bump_row_version() RETURNS trigger AS $$
BEGIN
    NEW.row_version := OLD.row_version + 1;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;
"""


def trigger_sql(table: str, columns: list[str]) -> str:
    """SQL that installs the version trigger on `table`, watching `columns` (database column names)."""
    old = ", ".join(f'OLD."{c}"' for c in columns)
    new = ", ".join(f'NEW."{c}"' for c in columns)
    name = f"{table}_row_version"
    return (
        FUNCTION_SQL
        + f'DROP TRIGGER IF EXISTS "{name}" ON "{table}";\n'
        + f'CREATE TRIGGER "{name}" BEFORE UPDATE ON "{table}" FOR EACH ROW\n'
        + f"    WHEN (ROW({old}) IS DISTINCT FROM ROW({new}))\n"
        + "    EXECUTE FUNCTION mrs_bump_row_version();\n"
    )


def drop_trigger_sql(table: str) -> str:
    return f'DROP TRIGGER IF EXISTS "{table}_row_version" ON "{table}";'


class Versioned(models.Model):
    """Adds `row_version`. The number is owned by the database trigger; Python only reads it back."""

    row_version = models.PositiveIntegerField(default=1, editable=False)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        updating = not self._state.adding
        if updating and kwargs.get("update_fields") is not None:
            # Never write a stale in-memory number over the database's.
            kwargs["update_fields"] = [f for f in kwargs["update_fields"] if f != "row_version"]
        super().save(*args, **kwargs)
        if updating:
            self.refresh_version()

    def refresh_version(self) -> None:
        current = type(self).objects.filter(pk=self.pk).values_list("row_version", flat=True).first()
        if current is not None:
            self.row_version = current


def bump_version(obj: Versioned) -> None:
    """Count a change the trigger cannot see, such as new permissions on a role."""
    type(obj).objects.filter(pk=obj.pk).update(row_version=models.F("row_version") + 1)
    obj.refresh_version()


class EditConflict(ConflictError):
    code = "edit_conflict"


def expected_version(request) -> int | None:
    """The version the client loaded: `row_version` in the body, or an `If-Match: "7"` header."""
    raw = None
    data = getattr(request, "data", None)
    if hasattr(data, "get"):
        raw = data.get("row_version")
    if raw in (None, ""):
        header = request.headers.get("If-Match", "").strip()
        if header and header != "*":
            raw = header.removeprefix("W/").strip('"')
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        from rest_framework import serializers

        raise serializers.ValidationError({"row_version": ["Must be a whole number."]}) from None


def _last_change(object_type: str, object_id) -> tuple[str | None, str | None]:
    from apps.audit.models import AuditEvent

    event = (AuditEvent.objects.filter(object_type=object_type, object_id=str(object_id))
             .exclude(action__endswith=".view").order_by("-occurred_at").select_related("actor").first())
    if event is None:
        return None, None
    who = event.actor.full_name if getattr(event, "actor", None) else (event.actor_username or None)
    return who, event.occurred_at.isoformat()


def check_version(obj: Versioned, expected: int | None, *, object_type: str, label: str = "record") -> None:
    """Call after loading `obj` with select_for_update. Raises EditConflict when the client is behind."""
    if expected is None or expected == obj.row_version:
        return
    who, when = _last_change(object_type, obj.pk)
    by = f" by {who}" if who else ""
    raise EditConflict(
        f"This {label} was changed{by} while you were editing it, so your changes were not saved. "
        "Load the latest version, check it, and make your change again.",
        extra={"current_version": obj.row_version, "your_version": expected, "changed_by": who, "changed_at": when},
    )


@contextmanager
def guarded_edit(model, pk, request, *, object_type: str, label: str = "record"):
    """
    Lock the row, compare versions and keep the lock until the edit inside the block commits:

        with guarded_edit(Patient, pk, request, object_type="patient", label="patient record") as patient:
            services.update_patient(ctx, patient, data)

    A conflict found here aborts before anything is written.
    """
    with transaction.atomic():
        obj = get_object_or_404(model.objects.select_for_update(), pk=pk)
        check_version(obj, expected_version(request), object_type=object_type, label=label)
        yield obj
