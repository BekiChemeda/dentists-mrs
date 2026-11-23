/**
 * FDI tooth numbering and surfaces for the dental chart. Mirrors backend/apps/dental/teeth.py; the server
 * validates everything again. Orientation: the patient's right is on the viewer's left (ADR 0008).
 */

export const UPPER_PERMANENT = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28];
export const LOWER_PERMANENT = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38];
export const UPPER_PRIMARY = [55, 54, 53, 52, 51, 61, 62, 63, 64, 65];
export const LOWER_PRIMARY = [85, 84, 83, 82, 81, 71, 72, 73, 74, 75];
export const ALL_TEETH = [...UPPER_PERMANENT, ...LOWER_PERMANENT, ...UPPER_PRIMARY, ...LOWER_PRIMARY];

export const SURFACE_NAMES: Record<string, string> = {
  M: "Mesial",
  D: "Distal",
  O: "Occlusal",
  I: "Incisal",
  B: "Buccal / labial",
  L: "Lingual / palatal",
};

export type Dentition = "permanent" | "primary" | "mixed";

export const isPrimary = (tooth: number) => Math.floor(tooth / 10) >= 5;
export const quadrant = (tooth: number) => Math.floor(tooth / 10);
export const isAnterior = (tooth: number) => tooth % 10 <= 3;
export const isUpper = (tooth: number) => [1, 2, 5, 6].includes(quadrant(tooth));
/** Teeth on the viewer's left (patient's right) have their mesial surface towards the right of the screen. */
export const mesialOnRight = (tooth: number) => [1, 4, 5, 8].includes(quadrant(tooth));

export function allowedSurfaces(tooth: number): string[] {
  return isAnterior(tooth) ? ["M", "D", "I", "B", "L"] : ["M", "D", "O", "B", "L"];
}

/** The usual way to write a combination: MO, DO, MOD, then B and L. */
export function orderSurfaces(letters: string): string {
  const have = new Set(letters.toUpperCase().split(""));
  const middle = ["O", "I"].filter((c) => have.has(c)).join("");
  let core = middle;
  if (have.has("M") && have.has("D")) core = `M${middle}D`;
  else if (have.has("M")) core = `M${middle}`;
  else if (have.has("D")) core = `D${middle}`;
  return core + ["B", "L"].filter((c) => have.has(c)).join("");
}

export function canHaveFurcation(tooth: number): boolean {
  const pos = tooth % 10;
  const q = quadrant(tooth);
  if (q >= 5) return pos >= 4;
  return pos >= 6 || (pos === 4 && (q === 1 || q === 2));
}

export const REGION_NAMES: Record<string, string> = {
  q1: "Upper right quadrant",
  q2: "Upper left quadrant",
  q3: "Lower left quadrant",
  q4: "Lower right quadrant",
  upper: "Upper arch",
  lower: "Lower arch",
  sextant_1: "Sextant 1 (upper right posterior)",
  sextant_2: "Sextant 2 (upper anterior)",
  sextant_3: "Sextant 3 (upper left posterior)",
  sextant_4: "Sextant 4 (lower left posterior)",
  sextant_5: "Sextant 5 (lower anterior)",
  sextant_6: "Sextant 6 (lower right posterior)",
};

export function rowsFor(dentition: Dentition): number[][] {
  if (dentition === "permanent") return [UPPER_PERMANENT, LOWER_PERMANENT];
  if (dentition === "primary") return [UPPER_PRIMARY, LOWER_PRIMARY];
  return [UPPER_PERMANENT, UPPER_PRIMARY, LOWER_PRIMARY, LOWER_PERMANENT];
}
