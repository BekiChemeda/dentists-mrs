# ADR 0006 — The odontogram is a list of dated findings, not a mutable tooth status

Date: 2026-11-23 · Status: accepted (clinical vocabulary pending dentist review)

## Decision

Each statement about a tooth, set of surfaces, region or the whole mouth is one `ToothFinding` row, recorded in
one dental examination. A finding is never edited. It can later be **resolved** (it stopped being true, e.g.
caries restored, tooth extracted; recorded in a later examination with a note) or **voided** (entered in error,
with a reason and `dental.amend`). The chart at any moment is computed: findings recorded by then, not voided,
not yet resolved.

## Alternatives considered

- *One status per tooth, overwritten:* loses history; rejected by the specification (§7.2, §29.4).
- *Full chart snapshot per examination:* easy to display but duplicates 52 teeth per visit, and the difference
  between two snapshots does not say *why* something changed. Snapshots can be produced from the event list at
  any time, so they are not stored.

## Consequences

- "Show the chart as of an examination" and "compare two dates" are a single query each.
- Findings from a signed examination are frozen; the only allowed changes are resolution and void, each set once.
- The UI distinguishes current pathology (`condition`), prior work (`existing`) and tooth state (`state`) by
  symbol and text, not colour alone.
