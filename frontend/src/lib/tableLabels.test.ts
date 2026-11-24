// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { labelCells } from "./tableLabels";

describe("labelCells", () => {
  it("copies column headings onto cells, honouring colspan", () => {
    document.body.innerHTML = `<table class="data"><thead><tr><th>Date</th><th colspan="2">Patient</th><th></th></tr></thead>
      <tbody><tr><td>1</td><td>2</td><td>3</td><td>4</td></tr><tr><td colspan="3">wide</td><td>x</td></tr></tbody></table>`;
    labelCells(document);
    const cells = Array.from(document.querySelectorAll("td")).map((c) => c.getAttribute("data-label"));
    expect(cells).toEqual(["Date", "Patient", "Patient", "", "Date", ""]);
  });
});

describe("totals rows", () => {
  it("leave a short totals row unlabelled", () => {
    document.body.innerHTML = `<table class="data"><thead><tr><th>Item</th><th>Qty</th><th>Cost</th></tr></thead>
      <tbody><tr><td>a</td><td>1</td><td>2</td></tr></tbody>
      <tfoot><tr><td colspan="2">Total</td><td>2</td></tr></tfoot></table>`;
    labelCells(document);
    const foot = Array.from(document.querySelectorAll("tfoot td")).map((c) => c.getAttribute("data-label"));
    expect(foot).toEqual(["", ""]);
  });
});
