# Odontogram

## What it records

A finding is a statement about **one tooth**, **one or more surfaces of a tooth**, a **region** (quadrant, arch,
sextant) or the **whole mouth**, recorded in a dental examination by a named person at a time. See ADR 0006.

- Tooth numbers: FDI. Permanent 11–18, 21–28, 31–38, 41–48; primary 51–55, 61–65, 71–75, 81–85.
- Surfaces: M mesial, D distal, O occlusal (premolars and molars), I incisal (incisors and canines),
  B buccal/labial, L lingual/palatal.
- Kinds of finding (from the catalogue, each with a short printed symbol):
  - **State** — missing, unerupted, partially erupted, retained primary, impacted, implant present…
  - **Condition** — caries, fracture, wear, discolouration, mobility, periapical lesion…
  - **Existing work** — restoration, crown, bridge abutment/pontic, root canal treated, sealant, veneer…

## Screen

- Upper arch on top. The patient's right is on the viewer's left: `18 … 11 | 21 … 28` above
  `48 … 41 | 31 … 38`. Primary teeth in their own rows (`55 … 51 | 61 … 65`, `85 … 81 | 71 … 75`).
  *Dentition* switch: Permanent, Primary, Mixed (both).
- Each tooth is a button showing its number, a five-surface diagram, and the symbols of its current findings.
  Keyboard: Tab between teeth, Enter to open; touch targets at least 44 px.
- Opening a tooth shows its current findings, its full history (including resolved and entered-in-error, struck
  through with the reason) and a form: scope (whole tooth / surfaces), surface toggles, finding, note, diagnosis.
- **As of**: choose a previous examination to see the chart as it was then (read-only). **Compare**: list what
  was added and resolved between two examinations.
- Legend under the chart lists every symbol in use and its meaning. Colour is a secondary cue only; printing in
  grayscale keeps symbols and text.

## Rules

- Findings can be added only to a **draft** examination of an **open** visit, by `dental.chart.record`.
- A finding added in the current draft can be removed while the draft is unsigned (a typing slip). After
  signing: *Resolve* (in a later examination, with a note) or *Entered in error* (`dental.amend`, reason).
- No finding implies a diagnosis or treatment automatically.
- A procedure record can be linked to the findings it addressed; the dentist chooses whether to resolve them
  and whether to record the new restoration.

## API

`GET /api/v1/dental/patients/{id}/chart/?as_of=<ISO time>|&encounter=<id>` — teeth with current findings.
`GET /api/v1/dental/patients/{id}/chart/history/?tooth=36` — every finding for the tooth.
`GET /api/v1/dental/patients/{id}/chart/compare/?from=<encounter>&to=<encounter>`.
`POST /api/v1/dental/encounters/{id}/findings/` — record. `POST /api/v1/dental/findings/{id}/resolve/`,
`/void/`, `DELETE /api/v1/dental/findings/{id}/` (draft only).
