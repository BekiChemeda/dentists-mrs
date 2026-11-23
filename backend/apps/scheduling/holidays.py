"""
Ethiopian public holidays for the clinic calendar.

Proclamation No. 1334/2024 (Public Holidays and Celebration of Public Holidays):
- Art. 4 national holidays, offices closed: New Year (Enkutatash), Adwa Victory Day (2 March),
  International Workers' Day (1 May), Patriots' Victory Day (5 May).
- Art. 5 memorial days, offices open: Martyrs' Day (20 February), Nations, Nationalities and Peoples'
  (Unity) Day (9 December).
- Art. 6 religious holidays: Meskel, Genna (7 January), Timket, Siklet (Good Friday), Fasika (Easter),
  Mawlid, Eid al-Fitr, Eid al-Adha.
- Art. 8(1): hospitals, health centres, clinics and pharmacies must keep operating on holidays.
  The calendar therefore marks holidays for planning; it never blocks bookings.

New Year, Meskel and Timket are kept by the Ethiopian calendar (Meskerem 1, Meskerem 17, Tir 11), so in the
Gregorian calendar they move by a day in some years (e.g. 12 and 28 September 2027). Siklet and Fasika follow
the Orthodox (Julian) Easter. The three Islamic holidays depend on moon sighting and are entered in the
Holiday table by the clinic (seeded as tentative).
"""
import datetime

from apps.core.ethiopian import from_ethiopian, to_ethiopian

from .models import Holiday


def orthodox_easter(year: int) -> datetime.date:
    """Orthodox Easter (Fasika) in the Gregorian calendar: Meeus' Julian algorithm + 13 days (valid 1900-2099)."""
    a, b, c = year % 4, year % 7, year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month, day = divmod(d + e + 114, 31)
    return datetime.date(year, month, day + 1) + datetime.timedelta(days=13)


def _rule_holidays(year: int) -> list[dict]:
    ec_year = to_ethiopian(datetime.date(year, 9, 30))[0]  # Ethiopian year that starts in this Gregorian year
    easter = orthodox_easter(year)
    rows = [
        (datetime.date(year, 1, 7), "Genna (Ethiopian Christmas)", "religious"),
        (from_ethiopian(ec_year - 1, 5, 11), "Timket (Epiphany)", "religious"),
        (datetime.date(year, 2, 20), "Martyrs' Day", "memorial"),
        (datetime.date(year, 3, 2), "Adwa Victory Day", "national"),
        (easter - datetime.timedelta(days=2), "Siklet (Good Friday)", "religious"),
        (easter, "Fasika (Easter)", "religious"),
        (datetime.date(year, 5, 1), "International Workers' Day", "national"),
        (datetime.date(year, 5, 5), "Patriots' Victory Day", "national"),
        (from_ethiopian(ec_year, 1, 1), "Enkutatash (Ethiopian New Year)", "national"),
        (from_ethiopian(ec_year, 1, 17), "Meskel", "religious"),
        (datetime.date(year, 12, 9), "Nations, Nationalities and Peoples' Day", "memorial"),
    ]
    return [{"date": d, "name": n, "kind": k, "tentative": False, "editable": False, "id": None, "note": ""}
            for d, n, k in rows]


def holidays_between(start: datetime.date, end: datetime.date) -> list[dict]:
    out = []
    for year in range(start.year, end.year + 1):
        out += [h for h in _rule_holidays(year) if start <= h["date"] <= end]
    for h in Holiday.objects.filter(date__range=(start, end)):
        out.append({"date": h.date, "name": h.name, "kind": h.kind, "tentative": h.tentative, "editable": True,
                    "id": h.pk, "note": h.note})
    for h in out:
        h["offices_closed"] = h["kind"] in ("national", "religious")
    return sorted(out, key=lambda h: (h["date"], h["name"]))
