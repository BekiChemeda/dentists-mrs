/**
 * On a phone, data tables are shown as one card per row (see styles.css, "tables as cards").
 * Each cell needs its column heading as a label; this copies the <th> text into `data-label`
 * on every cell, and keeps it up to date as React re-renders.
 */
export function labelCells(root: ParentNode): void {
  root.querySelectorAll<HTMLTableElement>("table.data").forEach((table) => {
    const heads = table.tHead?.rows[0];
    if (!heads) return;
    const labels: string[] = [];
    for (const th of Array.from(heads.cells)) {
      const text = (th.textContent ?? "").trim();
      for (let i = 0; i < (th.colSpan || 1); i++) labels.push(text);
    }
    for (const body of [...Array.from(table.tBodies), ...(table.tFoot ? [table.tFoot] : [])]) {
      for (const row of Array.from(body.rows)) {
        let col = 0;
        const foot = body === table.tFoot;
        for (const cell of Array.from(row.cells)) {
          // In a totals row the first cell names the row ("Total"), so it gets no column label.
          const label = foot && col === 0 ? "" : (labels[col] ?? "");
          if (cell.getAttribute("data-label") !== label) cell.setAttribute("data-label", label);
          col += cell.colSpan || 1;
        }
      }
    }
  });
}

export function startTableLabels(): void {
  if (typeof window === "undefined" || typeof MutationObserver === "undefined") return;
  let queued = false;
  const run = () => {
    queued = false;
    labelCells(document);
  };
  new MutationObserver(() => {
    if (!queued) {
      queued = true;
      requestAnimationFrame(run);
    }
  }).observe(document.body, { childList: true, subtree: true, characterData: true });
  run();
}
