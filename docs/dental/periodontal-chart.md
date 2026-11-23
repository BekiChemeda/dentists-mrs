# Periodontal chart

**Pending dentist review (R-04).** The protocol below is a common six-site chart; it must be confirmed.

## What is recorded

Per examination (`PeriodontalExam`, part of a dental examination), per tooth and per site.

| Level | Values | Allowed range |
| --- | --- | --- |
| Tooth | missing, excluded (reason), implant, mobility, furcation | mobility 0–3; furcation 0–3, only on molars and maxillary first premolars |
| Site (MB, B, DB, ML, L, DL) | probing depth (mm), gingival margin (mm), bleeding on probing, plaque, suppuration, not measured (reason) | PD 0–15; GM −10 to 15 |

Values outside the range are **refused** with a message, never changed. A site can be marked *not measured*
(with a reason) and then holds no values; sites simply left blank count as not measured in summaries and are
shown as blank, never as zero.

## Calculations (not stored; always recomputed from raw values)

- **Clinical attachment level (CAL)** = probing depth + gingival margin, where the gingival margin is the distance
  from the cemento-enamel junction (CEJ) to the gingival margin, **positive when the margin is apical to the CEJ
  (recession)** and negative when coronal (enlargement). CAL is shown only when both values exist.
- **Bleeding on probing %** = sites with bleeding ÷ sites probed (an unticked box on a probed site means no bleeding).
  **Plaque %** and **suppuration %** likewise, once plaque or suppuration is recorded anywhere in the chart; before that
  they show as not recorded rather than 0%.
  Both are shown with the count of sites assessed.
- **Counts** of sites with PD ≥ 4 mm and ≥ 6 mm.

These are descriptive numbers. The system does not classify periodontitis or suggest treatment.

## Comparison

Two examinations of the same patient side by side: per site the earlier and later probing depth and CAL and the
difference; teeth missing in one but not the other are flagged.

## Editing

Only while the examination is a draft. The whole chart is saved in one request (all sites of a tooth or of the
mouth) with the exam's version; a concurrent save by someone else is refused with the usual conflict message.
