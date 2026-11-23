import { describe, expect, it } from "vitest";
import { ALL_TEETH, allowedSurfaces, canHaveFurcation, mesialOnRight, orderSurfaces, rowsFor } from "./teeth";

describe("FDI teeth", () => {
  it("has 32 permanent and 20 primary teeth", () => {
    expect(ALL_TEETH.length).toBe(52);
    expect(new Set(ALL_TEETH).size).toBe(52);
    expect(rowsFor("mixed").flat().length).toBe(52);
  });
  it("orders surfaces the way dentists write them", () => {
    expect(orderSurfaces("odm")).toBe("MOD");
    expect(orderSurfaces("od")).toBe("DO");
    expect(orderSurfaces("bom")).toBe("MOB");
    expect(orderSurfaces("ib")).toBe("IB");
  });
  it("offers occlusal on back teeth and incisal on front teeth", () => {
    expect(allowedSurfaces(36)).toContain("O");
    expect(allowedSurfaces(36)).not.toContain("I");
    expect(allowedSurfaces(11)).toContain("I");
    expect(allowedSurfaces(53)).toContain("I");
  });
  it("puts the mesial surface towards the midline", () => {
    expect(mesialOnRight(16)).toBe(true);
    expect(mesialOnRight(26)).toBe(false);
    expect(mesialOnRight(46)).toBe(true);
    expect(mesialOnRight(36)).toBe(false);
  });
  it("knows which teeth have a furcation", () => {
    expect(canHaveFurcation(16)).toBe(true);
    expect(canHaveFurcation(14)).toBe(true);
    expect(canHaveFurcation(34)).toBe(false);
    expect(canHaveFurcation(75)).toBe(true);
  });
});
