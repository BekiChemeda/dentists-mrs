// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { stopWheelEditing } from "./numberWheel";

describe("stopWheelEditing", () => {
  it("takes focus off a number box when the wheel turns over it", () => {
    const stop = stopWheelEditing(document);
    const input = document.createElement("input");
    input.type = "number";
    input.value = "501";
    document.body.appendChild(input);
    input.focus();
    input.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: 100 }));
    expect(document.activeElement).not.toBe(input);
    expect(input.value).toBe("501");
    stop();
    input.remove();
  });

  it("leaves text boxes alone", () => {
    const stop = stopWheelEditing(document);
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();
    input.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: 100 }));
    expect(document.activeElement).toBe(input);
    stop();
    input.remove();
  });
});
