"""
Teeth, surfaces and regions: one place that decides what a valid tooth reference is.

FDI two-digit notation (ISO 3950). The first digit is the quadrant (1-4 permanent, 5-8 primary), the second the
position from the midline (1-8 permanent, 1-5 primary). Surfaces: M mesial, D distal, O occlusal (premolars and
molars), I incisal (incisors and canines), B buccal/labial, L lingual/palatal.

Clinical vocabulary is pending dentist review (docs/dental/clinical-review-log.md, R-02).
"""

from __future__ import annotations

PERMANENT = tuple(q * 10 + p for q in (1, 2, 3, 4) for p in range(1, 9))
PRIMARY = tuple(q * 10 + p for q in (5, 6, 7, 8) for p in range(1, 6))
ALL_TEETH = frozenset(PERMANENT + PRIMARY)

SURFACES = {"M": "Mesial", "D": "Distal", "O": "Occlusal", "I": "Incisal", "B": "Buccal / labial",
            "L": "Lingual / palatal"}

REGIONS = {
    "q1": "Upper right quadrant", "q2": "Upper left quadrant", "q3": "Lower left quadrant",
    "q4": "Lower right quadrant", "upper": "Upper arch", "lower": "Lower arch",
    "sextant_1": "Sextant 1 (upper right posterior)", "sextant_2": "Sextant 2 (upper anterior)",
    "sextant_3": "Sextant 3 (upper left posterior)", "sextant_4": "Sextant 4 (lower left posterior)",
    "sextant_5": "Sextant 5 (lower anterior)", "sextant_6": "Sextant 6 (lower right posterior)",
}

SCOPES = {"tooth": "Whole tooth", "surfaces": "Tooth surfaces", "region": "Region", "mouth": "Whole mouth"}

# Periodontal sites, six-site protocol (pending review R-04).
PERIO_SITES = ("MB", "B", "DB", "ML", "L", "DL")


class ToothError(ValueError):
    """A tooth, surface or region reference that is not valid. `field` names the input."""

    def __init__(self, message: str, field: str = "tooth"):
        super().__init__(message)
        self.field = field


def dentition(tooth: int) -> str:
    return "primary" if tooth // 10 >= 5 else "permanent"


def position(tooth: int) -> int:
    return tooth % 10


def is_anterior(tooth: int) -> bool:
    """Incisors and canines: positions 1-3 in both dentitions."""
    return position(tooth) <= 3


def is_upper(tooth: int) -> bool:
    return tooth // 10 in (1, 2, 5, 6)


def can_have_furcation(tooth: int) -> bool:
    """Molars, and maxillary first premolars (usually two roots). Primary molars too."""
    pos, quadrant = position(tooth), tooth // 10
    if quadrant >= 5:
        return pos >= 4
    return pos >= 6 or (pos == 4 and quadrant in (1, 2))


def check_tooth(value) -> int:
    try:
        tooth = int(value)
    except (TypeError, ValueError):
        raise ToothError("Use an FDI tooth number such as 36 or 75.") from None
    if tooth not in ALL_TEETH:
        raise ToothError(f"{value} is not an FDI tooth number (11-48 permanent, 51-85 primary).")
    return tooth


def allowed_surfaces(tooth: int) -> str:
    return "MDBLI" if is_anterior(tooth) else "MDBLO"


def normalise_surfaces(tooth: int, surfaces) -> str:
    """Accepts "dom", ["D", "O", "M"]...; returns the letters in a fixed order ("MOD"), validated for the tooth."""
    letters = "".join(surfaces) if isinstance(surfaces, (list, tuple)) else str(surfaces or "")
    letters = letters.upper().replace(" ", "").replace(",", "")
    if not letters:
        raise ToothError("Choose at least one surface.", "surfaces")
    unknown = set(letters) - set(SURFACES)
    if unknown:
        raise ToothError(f"Unknown surface: {''.join(sorted(unknown))}.", "surfaces")
    if len(set(letters)) != len(letters):
        raise ToothError("Each surface once only.", "surfaces")
    allowed = allowed_surfaces(tooth)
    bad = set(letters) - set(allowed)
    if bad:
        kind = "an incisor or canine" if is_anterior(tooth) else "a premolar or molar"
        raise ToothError(f"Tooth {tooth} is {kind}: surface {''.join(sorted(bad))} does not apply.", "surfaces")
    return order_surfaces(letters)


def order_surfaces(letters: str) -> str:
    """The usual way to write a surface combination: MO, DO, MOD (mesial, occlusal/incisal, distal), then B, L."""
    have = set(letters)
    middle = "".join(c for c in "OI" if c in have)
    if "M" in have and "D" in have:
        core = f"M{middle}D"
    elif "M" in have:
        core = f"M{middle}"
    elif "D" in have:
        core = f"D{middle}"
    else:
        core = middle
    return core + "".join(c for c in "BL" if c in have)


def clean_location(scope: str, tooth=None, surfaces="", region: str = "", *, tooth_required: bool = False,
                   allowed_scopes=None) -> dict:
    """
    Validate where a finding, diagnosis, plan item or procedure applies. Returns the fields to store:
    {"scope", "tooth", "surfaces", "region"} with the unused ones empty.
    """
    scope = scope or ("surfaces" if surfaces else "tooth" if tooth else "region" if region else "mouth")
    if scope not in SCOPES:
        raise ToothError("Choose whole tooth, surfaces, region or whole mouth.", "scope")
    if allowed_scopes is not None and scope not in allowed_scopes:
        raise ToothError(f"{SCOPES[scope]} does not apply here.", "scope")
    if tooth_required and scope not in ("tooth", "surfaces"):
        raise ToothError("This needs a tooth.", "tooth")
    if scope in ("tooth", "surfaces"):
        if tooth in (None, ""):
            raise ToothError("Choose the tooth.", "tooth")
        number = check_tooth(tooth)
        return {"scope": scope, "tooth": number,
                "surfaces": normalise_surfaces(number, surfaces) if scope == "surfaces" else "", "region": ""}
    if scope == "region":
        if region not in REGIONS:
            raise ToothError("Choose a quadrant, arch or sextant.", "region")
        return {"scope": scope, "tooth": None, "surfaces": "", "region": region}
    return {"scope": "mouth", "tooth": None, "surfaces": "", "region": ""}


def describe(scope: str, tooth=None, surfaces: str = "", region: str = "") -> str:
    """Plain words for screens, invoices and printouts: "36 MOD", "Upper arch", "Whole mouth"."""
    if scope == "surfaces" and tooth:
        return f"{tooth} {surfaces}"
    if scope == "tooth" and tooth:
        return str(tooth)
    if scope == "region":
        return REGIONS.get(region, region)
    return "Whole mouth"
