"""
Periodontal chart (docs/dental/periodontal-chart.md; protocol pending dentist review R-04).

Raw values are stored exactly as entered; out-of-range values are refused, never adjusted. Calculated values (CAL,
percentages) are derived on every read, so a correction to the formula never leaves stale numbers behind.
"""

from __future__ import annotations

from django.db import transaction

from apps.audit.services import record_event
from apps.core.context import ActorContext
from apps.core.exceptions import BusinessValidationError, ConflictError
from apps.core.modules import is_enabled

from .. import teeth
from ..models import DentalEncounter, PeriodontalExam, PeriodontalSite, PeriodontalTooth
from .common import open_encounter

SITE_VALUES = ("probing_depth_mm", "gingival_margin_mm", "bleeding", "plaque", "suppuration")


def _int_in(value, lo, hi, field):
    """Whole millimetres within the plausible range. Out-of-range values are refused, never changed."""
    if value in (None, ""):
        return None
    bad = BusinessValidationError("Enter whole millimetres.", fields={field: ["Whole millimetres."]})
    if isinstance(value, bool):
        raise bad
    if isinstance(value, float):
        if not value.is_integer():
            raise bad
        number = int(value)
    elif isinstance(value, int):
        number = value
    else:
        try:
            number = int(str(value).strip())
        except ValueError:
            raise bad from None
    if not lo <= number <= hi:
        raise BusinessValidationError(f"{number} is outside {lo} to {hi}. Check the value.",
                                      fields={field: [f"Between {lo} and {hi}."]})
    return number


def _bool_or_none(value, field):
    if value is None or isinstance(value, bool):
        return value
    raise BusinessValidationError("Yes, no or blank.", fields={field: ["Yes, no or blank."]})


def _clean_tooth(row: dict) -> tuple[dict, list[dict]]:
    try:
        tooth = teeth.check_tooth(row.get("tooth"))
    except teeth.ToothError as exc:
        raise BusinessValidationError(str(exc), fields={"tooth": [str(exc)]}) from None
    label = f"Tooth {tooth}"
    missing, excluded = bool(row.get("missing")), bool(row.get("excluded"))
    reason = (row.get("exclusion_reason") or "").strip()[:120]
    if excluded and not reason:
        raise BusinessValidationError(f"{label}: say why it was excluded.", fields={f"{tooth}.exclusion_reason": ["Required."]})
    mobility = _int_in(row.get("mobility"), 0, 3, f"{tooth}.mobility")
    furcation = _int_in(row.get("furcation"), 0, 3, f"{tooth}.furcation")
    if furcation is not None and not teeth.can_have_furcation(tooth):
        raise BusinessValidationError(f"{label} has no furcation to grade.", fields={f"{tooth}.furcation": ["N/A."]})
    tooth_row = {"tooth": tooth, "missing": missing, "excluded": excluded, "exclusion_reason": reason if excluded else "",
                 "implant": bool(row.get("implant")), "mobility": None if missing else mobility,
                 "furcation": None if missing else furcation, "notes": (row.get("notes") or "").strip()[:255]}
    sites = []
    raw_sites = row.get("sites") or {}
    if not isinstance(raw_sites, dict):
        raise BusinessValidationError("Sites must be given by site code.", fields={f"{tooth}.sites": ["Invalid."]})
    unknown = set(raw_sites) - set(teeth.PERIO_SITES)
    if unknown:
        raise BusinessValidationError(f"Unknown site {', '.join(sorted(unknown))}.", fields={f"{tooth}.sites": ["Unknown site."]})
    if (missing or excluded) and any(any(v not in (None, "", False) for k, v in (s or {}).items()
                                         if k in SITE_VALUES) for s in raw_sites.values()):
        raise BusinessValidationError(f"{label} is marked missing or excluded but has measurements.",
                                      fields={f"{tooth}.sites": ["Remove the measurements or the mark."]})
    for site in teeth.PERIO_SITES:
        s = raw_sites.get(site)
        if not s or missing or excluded:
            continue
        key = f"{tooth}.{site}"
        not_measured = bool(s.get("not_measured"))
        values = {
            "probing_depth_mm": _int_in(s.get("probing_depth_mm"), 0, 15, f"{key}.probing_depth_mm"),
            "gingival_margin_mm": _int_in(s.get("gingival_margin_mm"), -10, 15, f"{key}.gingival_margin_mm"),
            "bleeding": _bool_or_none(s.get("bleeding"), f"{key}.bleeding"),
            "plaque": _bool_or_none(s.get("plaque"), f"{key}.plaque"),
            "suppuration": _bool_or_none(s.get("suppuration"), f"{key}.suppuration"),
        }
        if not_measured and any(v is not None for v in values.values()):
            raise BusinessValidationError(f"{label} {site} is marked not measured but has values.",
                                          fields={key: ["Clear the values or the mark."]})
        if not not_measured and all(v is None for v in values.values()):
            continue  # blank: stays blank (never zero)
        sites.append({"tooth": tooth, "site": site, "not_measured": not_measured,
                      "not_measured_reason": (s.get("not_measured_reason") or "").strip()[:120] if not_measured else "",
                      **values})
    return tooth_row, sites


def _fill_unticked(exam: PeriodontalExam, cleaned: list, numbers: list[int]) -> None:
    """
    A ticked box means yes; an unticked box on a probed site means no, not "not assessed":
    - bleeding on probing is assessed whenever the site is probed;
    - plaque and suppuration count as assessed on probed sites once they are recorded anywhere in this chart.
    Sites that were not probed keep "not assessed", so percentages stay honest.
    """
    probed = [site for _, sites in cleaned for site in sites if site["probing_depth_mm"] is not None]
    for site in probed:
        if site["bleeding"] is None:
            site["bleeding"] = False
    for flag in ("plaque", "suppuration"):
        recorded = any(site[flag] for _, sites in cleaned for site in sites) or (
            PeriodontalSite.objects.filter(exam=exam, **{flag: True}).exclude(tooth__in=numbers).exists())
        if recorded:
            for site in probed:
                if site[flag] is None:
                    site[flag] = False


@transaction.atomic
def save_exam(ctx: ActorContext, encounter: DentalEncounter, data: dict, *, version: int | None) -> PeriodontalExam:
    """
    Create or update the examination's periodontal chart. `teeth` rows replace the stored rows for those teeth
    (only while the examination is a draft). `version` must match the stored chart's version.
    """
    if not is_enabled("periodontal"):
        raise ConflictError("The periodontal chart module is switched off for this clinic.")
    enc = open_encounter(encounter)
    exam = PeriodontalExam.objects.select_for_update().filter(encounter=enc).first()
    if exam is None:
        if version not in (None, 0):
            raise ConflictError("This periodontal chart no longer exists. Reload the page.")
        exam = PeriodontalExam.objects.create(patient=enc.patient, encounter=enc, examiner=ctx.user)
    elif version is not None and version != exam.version:
        raise ConflictError("Someone else saved this periodontal chart while you were entering values. Reload it "
                            "and enter your changes again.", extra={"current_version": exam.version})
    rows = data.get("teeth") or []
    if not isinstance(rows, list):
        raise BusinessValidationError("Send the teeth as a list.", fields={"teeth": ["Invalid."]})
    cleaned = [_clean_tooth(r or {}) for r in rows]
    numbers = [t["tooth"] for t, _ in cleaned]
    if len(numbers) != len(set(numbers)):
        raise BusinessValidationError("A tooth appears twice.", fields={"teeth": ["Duplicate tooth."]})
    _fill_unticked(exam, cleaned, numbers)
    if numbers:
        PeriodontalSite.objects.filter(exam=exam, tooth__in=numbers).delete()
        PeriodontalTooth.objects.filter(exam=exam, tooth__in=numbers).delete()
    for tooth_row, sites in cleaned:
        PeriodontalTooth.objects.create(exam=exam, **tooth_row)
        PeriodontalSite.objects.bulk_create([PeriodontalSite(exam=exam, **s) for s in sites])
    if "notes" in data:
        exam.notes = (data.get("notes") or "").strip()
    exam.version += 1
    exam.examiner = ctx.user if exam.examiner_id is None else exam.examiner
    exam.save()
    record_event(ctx, action="dental_perio.save", object_type="dental_encounter", object_id=enc.pk,
                 details={"exam": str(exam.pk), "teeth": numbers, "version": exam.version})
    return exam


# ---------------------------------------------------------------------------
# Calculations (descriptive only; no diagnosis is inferred)
# ---------------------------------------------------------------------------
def cal(site: PeriodontalSite) -> int | None:
    """Clinical attachment level = probing depth + gingival margin (margin positive when apical to the CEJ)."""
    if site.probing_depth_mm is None or site.gingival_margin_mm is None:
        return None
    return site.probing_depth_mm + site.gingival_margin_mm


def summary(exam: PeriodontalExam) -> dict:
    sites = list(exam.sites.all())
    teeth_rows = list(exam.teeth.all())
    charted = [t for t in teeth_rows if not (t.missing or t.excluded)]

    def pct(flag):
        assessed = [s for s in sites if getattr(s, flag) is not None]
        positive = sum(1 for s in assessed if getattr(s, flag))
        return {"positive": positive, "assessed": len(assessed),
                "percent": round(100 * positive / len(assessed), 1) if assessed else None}

    depths = [s.probing_depth_mm for s in sites if s.probing_depth_mm is not None]
    return {
        "teeth_charted": len(charted), "teeth_missing": sum(1 for t in teeth_rows if t.missing),
        "teeth_excluded": sum(1 for t in teeth_rows if t.excluded),
        "sites_with_values": sum(1 for s in sites if not s.not_measured),
        "sites_not_measured": sum(1 for s in sites if s.not_measured),
        "sites_possible": len(charted) * len(teeth.PERIO_SITES),
        "bleeding": pct("bleeding"), "plaque": pct("plaque"), "suppuration": pct("suppuration"),
        "pd_4_or_more": sum(1 for d in depths if d >= 4), "pd_6_or_more": sum(1 for d in depths if d >= 6),
        "deepest_pd": max(depths) if depths else None,
        "formula": "CAL = probing depth + gingival margin (margin measured from the CEJ, positive when apical). "
                   "Bleeding: of the sites probed. Plaque and suppuration: of the sites probed, once recorded in this chart. "
                   "Pending dentist review.",
    }


def compare(earlier: PeriodontalExam, later: PeriodontalExam) -> dict:
    if earlier.patient_id != later.patient_id:
        raise BusinessValidationError("The two charts belong to different patients.")
    a = {(s.tooth, s.site): s for s in earlier.sites.all()}
    b = {(s.tooth, s.site): s for s in later.sites.all()}
    rows = []
    for key in sorted(a.keys() | b.keys()):
        sa, sb = a.get(key), b.get(key)
        pd_a = sa.probing_depth_mm if sa else None
        pd_b = sb.probing_depth_mm if sb else None
        cal_a, cal_b = (cal(sa) if sa else None), (cal(sb) if sb else None)
        rows.append({"tooth": key[0], "site": key[1], "pd_before": pd_a, "pd_after": pd_b,
                     "pd_change": None if pd_a is None or pd_b is None else pd_b - pd_a,
                     "cal_before": cal_a, "cal_after": cal_b,
                     "cal_change": None if cal_a is None or cal_b is None else cal_b - cal_a})
    ta = {t.tooth: t for t in earlier.teeth.all()}
    tb = {t.tooth: t for t in later.teeth.all()}
    missing_changed = sorted(n for n in ta.keys() & tb.keys() if ta[n].missing != tb[n].missing)
    return {"sites": rows, "missing_changed": missing_changed,
            "earlier": {"id": str(earlier.pk), "date": earlier.created_at, "summary": summary(earlier)},
            "later": {"id": str(later.pk), "date": later.created_at, "summary": summary(later)}}
