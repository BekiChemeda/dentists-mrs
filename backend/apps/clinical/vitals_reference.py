"""
Interpretation of vital signs.

Two kinds of limits are kept separate on purpose:

* Impossible values (typing errors such as 1200 for 120) are rejected by database constraints on
  VitalSigns. Those limits are wide so that no real, if extreme, measurement is refused.
* Abnormal and critical values are accepted, saved, and flagged here so staff notice them.

References (interpretation is only given where one of these applies; otherwise the value is
shown without a flag and staff use clinical judgement):

* Adults, 16 years and over: Royal College of Physicians, National Early Warning Score 2 (NEWS2),
  Chart 1 "The NEWS scoring system", 2017. A single-parameter score of 3 is shown as critical,
  1 or 2 as abnormal. The aggregate score and its risk band are computed when every NEWS2
  parameter was recorded.
  https://www.rcp.ac.uk/resources/national-early-warning-score-news-2/
* Adult blood pressure: WHO definition of hypertension, systolic >= 140 or diastolic >= 90 mmHg,
  shown as abnormal; >= 180 systolic or >= 120 diastolic shown as critical (severe).
* Children under 5 years: WHO Integrated Management of Childhood Illness (IMCI). Fast breathing:
  >= 60/min under 2 months, >= 50/min 2-11 months, >= 40/min 12-59 months. Fever: axillary
  temperature >= 37.5 C; low temperature < 35.5 C. SpO2 < 90 % needs urgent referral.
  https://www.ncbi.nlm.nih.gov/books/NBK154448/
* Children 5-15 years: only SpO2 < 90 % (WHO, oxygen therapy for children) is flagged.

These are defaults for screening, not diagnosis. They must be reviewed by the clinic's medical
director before use.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

NORMAL, ABNORMAL, CRITICAL = "normal", "abnormal", "critical"


def _age_in_months(birth_date: datetime.date, on: datetime.date) -> int:
    months = (on.year - birth_date.year) * 12 + (on.month - birth_date.month)
    if on.day < birth_date.day:
        months -= 1
    return max(months, 0)


def _band(score: int) -> str:
    return CRITICAL if score >= 3 else ABNORMAL if score >= 1 else NORMAL


# --- NEWS2 single-parameter scores (Chart 1) -----------------------------------------------------
def _news_rr(v: int) -> int:
    if v <= 8:
        return 3
    if v <= 11:
        return 1
    if v <= 20:
        return 0
    if v <= 24:
        return 2
    return 3


def _news_spo2(v: int) -> int:  # Scale 1 (patients without hypercapnic respiratory failure)
    if v <= 91:
        return 3
    if v <= 93:
        return 2
    if v <= 95:
        return 1
    return 0


def _news_sbp(v: int) -> int:
    if v <= 90:
        return 3
    if v <= 100:
        return 2
    if v <= 110:
        return 1
    if v <= 219:
        return 0
    return 3


def _news_hr(v: int) -> int:
    if v <= 40:
        return 3
    if v <= 50:
        return 1
    if v <= 90:
        return 0
    if v <= 110:
        return 1
    if v <= 130:
        return 2
    return 3


def _news_temp(v: Decimal) -> int:
    if v <= Decimal("35.0"):
        return 3
    if v <= Decimal("36.0"):
        return 1
    if v <= Decimal("38.0"):
        return 0
    if v <= Decimal("39.0"):
        return 1
    return 2


def _news_consciousness(v: str) -> int:
    return 0 if v == "alert" else 3


def _news_risk(total: int, any_three: bool) -> str:
    if total >= 7:
        return "high"
    if total >= 5:
        return "medium"
    if any_three:
        return "low-medium"
    return "low"


def interpret(values: dict, *, birth_date: datetime.date | None, on: datetime.date | None = None) -> dict:
    """
    Classify each recorded measurement. Returns
      {"reference": str, "flags": {field: {"level": ..., "text": ...}}, "news2": {...} | None,
       "worst": "normal" | "abnormal" | "critical"}
    """
    on = on or datetime.date.today()
    flags: dict[str, dict] = {}
    news2 = None

    def flag(field: str, level: str, text: str) -> None:
        if level != NORMAL:
            flags[field] = {"level": level, "text": text}

    if birth_date is None:
        return {"reference": "none", "flags": {}, "news2": None, "worst": NORMAL}
    months = _age_in_months(birth_date, on)
    sbp, dbp = values.get("systolic"), values.get("diastolic")
    temp, hr, rr, spo2 = values.get("temperature_c"), values.get("heart_rate"), values.get("respiratory_rate"), \
        values.get("spo2")
    consciousness = values.get("consciousness") or ""

    if months >= 16 * 12:
        reference = "NEWS2 (adult)"
        scores = {}
        if rr is not None:
            scores["respiratory_rate"] = _news_rr(int(rr))
            flag("respiratory_rate", _band(scores["respiratory_rate"]),
                 "Respiratory rate very abnormal" if scores["respiratory_rate"] == 3 else "Respiratory rate abnormal")
        if spo2 is not None:
            scores["spo2"] = _news_spo2(int(spo2))
            flag("spo2", _band(scores["spo2"]), "Low oxygen saturation")
        if sbp is not None:
            scores["systolic"] = _news_sbp(int(sbp))
            flag("systolic", _band(scores["systolic"]),
                 "Systolic pressure very abnormal" if scores["systolic"] == 3 else "Low systolic pressure")
        if hr is not None:
            scores["heart_rate"] = _news_hr(int(hr))
            flag("heart_rate", _band(scores["heart_rate"]),
                 "Very slow heart rate" if int(hr) <= 40 else "Slow heart rate" if int(hr) <= 50 else "Fast heart rate")
        if temp is not None:
            scores["temperature_c"] = _news_temp(Decimal(str(temp)))
            flag("temperature_c", _band(scores["temperature_c"]),
                 "Low temperature" if Decimal(str(temp)) <= 36 else "Fever")
        if consciousness:
            scores["consciousness"] = _news_consciousness(consciousness)
            flag("consciousness", _band(scores["consciousness"]), "Not fully alert (new confusion or worse)")
        # Hypertension is not part of NEWS2 but matters in outpatient care (WHO definition).
        if sbp is not None or dbp is not None:
            s, d = int(sbp or 0), int(dbp or 0)
            if s >= 180 or d >= 120:
                flags["systolic" if s >= 180 else "diastolic"] = {"level": CRITICAL, "text": "Severely raised blood pressure"}
            elif (s >= 140 or d >= 90) and "systolic" not in flags:
                flags["systolic" if s >= 140 else "diastolic"] = {"level": ABNORMAL, "text": "Raised blood pressure"}
        on_oxygen = values.get("on_oxygen")
        complete = all(k in scores for k in ("respiratory_rate", "spo2", "systolic", "heart_rate", "temperature_c",
                                             "consciousness")) and on_oxygen is not None
        total = sum(scores.values()) + (2 if on_oxygen else 0)
        news2 = {"total": total, "complete": complete, "risk": _news_risk(total, any(v == 3 for v in scores.values()))
                 if complete else None}
    elif months < 60:
        reference = "WHO IMCI (under 5 years)"
        if rr is not None:
            limit = 60 if months < 2 else 50 if months < 12 else 40
            if int(rr) >= limit:
                flag("respiratory_rate", ABNORMAL, f"Fast breathing for age (≥ {limit}/min)")
        if temp is not None:
            t = Decimal(str(temp))
            if t >= Decimal("37.5"):
                flag("temperature_c", ABNORMAL, "Fever (≥ 37.5 °C)")
            elif t < Decimal("35.5"):
                flag("temperature_c", ABNORMAL, "Low body temperature (< 35.5 °C)")
        if spo2 is not None and int(spo2) < 90:
            flag("spo2", CRITICAL, "Oxygen saturation below 90 %: urgent referral")
    else:
        reference = "WHO (children 5–15 years): oxygen saturation only"
        if spo2 is not None and int(spo2) < 90:
            flag("spo2", CRITICAL, "Oxygen saturation below 90 %")

    levels = [f["level"] for f in flags.values()]
    if news2 and news2.get("risk") == "high":
        levels.append(CRITICAL)
    worst = CRITICAL if CRITICAL in levels else ABNORMAL if levels else NORMAL
    return {"reference": reference, "flags": flags, "news2": news2, "worst": worst}
