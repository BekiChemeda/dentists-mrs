"""Ethiopian calendar conversion (same algorithm as the frontend's lib/ethiopian.ts)."""
import datetime

EPOCH = 1724221            # JDN of Meskerem 1, year 1 (Amete Mihret)
CYCLE_EPOCH = EPOCH - 365  # counted from year 0, so each 4-year cycle ends with the leap year


def to_ethiopian(d: datetime.date) -> tuple[int, int, int]:
    jdn = d.toordinal() + 1721425
    r = (jdn - CYCLE_EPOCH) % 1461
    n = r % 365 + 365 * (r // 1460)
    return 4 * ((jdn - CYCLE_EPOCH) // 1461) + r // 365 - r // 1460, n // 30 + 1, n % 30 + 1


def from_ethiopian(year: int, month: int, day: int) -> datetime.date:
    jdn = EPOCH + 365 * (year - 1) + year // 4 + 30 * (month - 1) + day - 1
    return datetime.date.fromordinal(jdn - 1721425)
