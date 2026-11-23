/**
 * Ethiopian (Ge'ez) calendar conversion, via the Julian Day Number.
 *
 * The Ethiopian year has twelve 30-day months and Pagume (5 days, 6 in the year before a Gregorian
 * leap year). Year 1 begins at JDN 1724221 (the Amete Mihret epoch). Dates are calendar dates only;
 * the Ethiopian day is not shifted to start at 6 a.m. here.
 */
const EPOCH = 1724221;
// Same epoch counted from year 0, so each 4-year cycle ends with the leap year (years ≡ 3 mod 4).
const CYCLE_EPOCH = EPOCH - 365;

export const EC_MONTHS = [
  "Meskerem",
  "Tikimt",
  "Hidar",
  "Tahsas",
  "Tir",
  "Yekatit",
  "Megabit",
  "Miyazya",
  "Ginbot",
  "Sene",
  "Hamle",
  "Nehase",
  "Pagume",
];

export interface EcDate {
  year: number;
  month: number;
  day: number;
}

function gregorianToJdn(y: number, m: number, d: number): number {
  const a = Math.floor((14 - m) / 12);
  const yy = y + 4800 - a;
  const mm = m + 12 * a - 3;
  return (
    d +
    Math.floor((153 * mm + 2) / 5) +
    365 * yy +
    Math.floor(yy / 4) -
    Math.floor(yy / 100) +
    Math.floor(yy / 400) -
    32045
  );
}

function jdnToGregorian(jdn: number): { year: number; month: number; day: number } {
  const a = jdn + 32044;
  const b = Math.floor((4 * a + 3) / 146097);
  const c = a - Math.floor((146097 * b) / 4);
  const d = Math.floor((4 * c + 3) / 1461);
  const e = c - Math.floor((1461 * d) / 4);
  const m = Math.floor((5 * e + 2) / 153);
  return {
    day: e - Math.floor((153 * m + 2) / 5) + 1,
    month: m + 3 - 12 * Math.floor(m / 10),
    year: 100 * b + d - 4800 + Math.floor(m / 10),
  };
}

export function toEthiopian(y: number, m: number, d: number): EcDate {
  const jdn = gregorianToJdn(y, m, d);
  const r = (jdn - CYCLE_EPOCH) % 1461;
  const n = (r % 365) + 365 * Math.floor(r / 1460);
  return {
    year: 4 * Math.floor((jdn - CYCLE_EPOCH) / 1461) + Math.floor(r / 365) - Math.floor(r / 1460),
    month: Math.floor(n / 30) + 1,
    day: (n % 30) + 1,
  };
}

/** Days in an Ethiopian month: 30, or 5/6 for Pagume (6 when the Ethiopian year mod 4 is 3). */
export function ecMonthLength(year: number, month: number): number {
  if (month < 13) return 30;
  return year % 4 === 3 ? 6 : 5;
}

/** Ethiopian date to an ISO Gregorian date (YYYY-MM-DD). Returns null for an impossible date. */
export function fromEthiopian(year: number, month: number, day: number): string | null {
  if (!Number.isInteger(year) || !Number.isInteger(month) || !Number.isInteger(day)) return null;
  if (year < 1 || month < 1 || month > 13 || day < 1 || day > ecMonthLength(year, month)) return null;
  const jdn = EPOCH + 365 * (year - 1) + Math.floor(year / 4) + 30 * (month - 1) + day - 1;
  const g = jdnToGregorian(jdn);
  return `${g.year}-${String(g.month).padStart(2, "0")}-${String(g.day).padStart(2, "0")}`;
}

/** "Hidar 12, 2019 EC" for an ISO date or timestamp, read in Addis Ababa time. */
export function formatEc(value: string | Date | null | undefined): string {
  if (!value) return "";
  let iso: string;
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) iso = value;
  else iso = new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Addis_Ababa" }).format(new Date(value));
  const [y, m, d] = iso.split("-").map(Number);
  const ec = toEthiopian(y, m, d);
  return `${EC_MONTHS[ec.month - 1]} ${ec.day}, ${ec.year} EC`;
}
