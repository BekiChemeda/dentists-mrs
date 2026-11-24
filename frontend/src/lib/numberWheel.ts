// Browsers change the value of a focused number box when the mouse wheel turns over it. Staff type
// a price, then scroll down to reach Save, and the price drops by one per notch without anyone noticing
// (QA: 501 typed, 496 saved). Here the wheel scrolls the page instead and never edits the number.

export function isFocusedNumberInput(target: EventTarget | null): target is HTMLInputElement {
  return (
    target instanceof HTMLInputElement &&
    target.type === "number" &&
    target.ownerDocument.activeElement === target
  );
}

export function stopWheelEditing(doc: Document = document): () => void {
  const onWheel = (e: WheelEvent) => {
    if (isFocusedNumberInput(e.target)) {
      // Losing focus before the default action runs means the browser scrolls instead of stepping.
      e.target.blur();
    }
  };
  doc.addEventListener("wheel", onWheel, { capture: true, passive: true });
  return () => doc.removeEventListener("wheel", onWheel, { capture: true });
}
