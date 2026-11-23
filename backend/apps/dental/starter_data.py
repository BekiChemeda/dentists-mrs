"""
Starter clinical content. EVERYTHING HERE IS PENDING REVIEW BY PRACTISING DENTISTS (docs/dental/clinical-review-log.md).

It gives a new clinic a working vocabulary to adapt; it is not a clinical recommendation. Prices are 0: the clinic
sets its own. Diagnosis codes are WHO ICD-10 (chapter XI, K00-K14, and S02.5); no codes are invented.
"""

# (code, name, kind, applies_to, symbol, colour, sort)
FINDING_TYPES = [
    # Tooth states
    ("missing", "Missing", "state", "tooth", "X", "#6b7280", 10),
    ("unerupted", "Unerupted", "state", "tooth", "UE", "#6b7280", 11),
    ("partially_erupted", "Partially erupted", "state", "tooth", "PE", "#6b7280", 12),
    ("impacted", "Impacted", "state", "tooth", "IMP", "#6b7280", 13),
    ("retained_primary", "Retained primary tooth", "state", "tooth", "RP", "#6b7280", 14),
    ("supernumerary", "Supernumerary tooth present", "state", "tooth", "SN", "#6b7280", 15),
    ("implant", "Implant", "state", "tooth", "IMPL", "#2563eb", 16),
    # Current conditions
    ("caries", "Caries", "condition", "either", "C", "#dc2626", 20),
    ("secondary_caries", "Secondary (recurrent) caries", "condition", "surface", "SC", "#dc2626", 21),
    ("fracture", "Fracture", "condition", "either", "FX", "#dc2626", 22),
    ("root_remnant", "Retained root", "condition", "tooth", "RR", "#dc2626", 23),
    ("periapical_lesion", "Periapical lesion", "condition", "tooth", "PA", "#dc2626", 24),
    ("mobility", "Mobile", "condition", "tooth", "MOB", "#d97706", 25),
    ("wear", "Wear (attrition, abrasion, erosion)", "condition", "either", "W", "#d97706", 26),
    ("discolouration", "Discolouration", "condition", "either", "DC", "#d97706", 27),
    ("defective_restoration", "Defective restoration", "condition", "either", "DR", "#dc2626", 28),
    ("calculus", "Calculus", "condition", "area", "CAL", "#d97706", 29),
    ("for_extraction", "Indicated for extraction", "condition", "tooth", "EXT?", "#dc2626", 30),
    # Existing treatment
    ("restoration_composite", "Composite restoration", "existing", "surface", "COM", "#2563eb", 40),
    ("restoration_amalgam", "Amalgam restoration", "existing", "surface", "AM", "#2563eb", 41),
    ("restoration_gic", "Glass ionomer restoration", "existing", "surface", "GIC", "#2563eb", 42),
    ("restoration_temporary", "Temporary restoration", "existing", "surface", "TMP", "#2563eb", 43),
    ("crown", "Crown", "existing", "tooth", "CR", "#2563eb", 44),
    ("bridge_abutment", "Bridge abutment", "existing", "tooth", "BA", "#2563eb", 45),
    ("bridge_pontic", "Bridge pontic", "existing", "tooth", "BP", "#2563eb", 46),
    ("root_canal_treated", "Root canal treated", "existing", "tooth", "RCT", "#2563eb", 47),
    ("sealant", "Fissure sealant", "existing", "surface", "FS", "#2563eb", 48),
    ("veneer", "Veneer", "existing", "tooth", "VEN", "#2563eb", 49),
    ("denture_tooth", "Replaced by a denture", "existing", "tooth", "DEN", "#2563eb", 50),
    ("extracted", "Extracted here", "existing", "tooth", "EXT", "#6b7280", 51),
]

# (code, term, category). WHO ICD-10 (2019). Review R-05.
DIAGNOSIS_TERMS = [
    ("K00.0", "Anodontia", "Development and eruption"),
    ("K00.6", "Disturbances in tooth eruption", "Development and eruption"),
    ("K01.0", "Embedded teeth", "Development and eruption"),
    ("K01.1", "Impacted teeth", "Development and eruption"),
    ("K02.0", "Caries limited to enamel", "Dental caries"),
    ("K02.1", "Caries of dentine", "Dental caries"),
    ("K02.2", "Caries of cementum", "Dental caries"),
    ("K02.3", "Arrested dental caries", "Dental caries"),
    ("K02.9", "Dental caries, unspecified", "Dental caries"),
    ("K03.0", "Excessive attrition of teeth", "Hard tissues"),
    ("K03.1", "Abrasion of teeth", "Hard tissues"),
    ("K03.2", "Erosion of teeth", "Hard tissues"),
    ("K03.6", "Deposits [accretions] on teeth", "Hard tissues"),
    ("K03.7", "Posteruptive colour changes of dental hard tissues", "Hard tissues"),
    ("K04.0", "Pulpitis", "Pulp and periapical"),
    ("K04.1", "Necrosis of pulp", "Pulp and periapical"),
    ("K04.4", "Acute apical periodontitis of pulpal origin", "Pulp and periapical"),
    ("K04.5", "Chronic apical periodontitis", "Pulp and periapical"),
    ("K04.6", "Periapical abscess with sinus", "Pulp and periapical"),
    ("K04.7", "Periapical abscess without sinus", "Pulp and periapical"),
    ("K04.8", "Radicular cyst", "Pulp and periapical"),
    ("K05.0", "Acute gingivitis", "Gingiva and periodontium"),
    ("K05.1", "Chronic gingivitis", "Gingiva and periodontium"),
    ("K05.2", "Acute periodontitis", "Gingiva and periodontium"),
    ("K05.3", "Chronic periodontitis", "Gingiva and periodontium"),
    ("K06.0", "Gingival recession", "Gingiva and periodontium"),
    ("K07.2", "Anomalies of dental arch relationship", "Dentofacial anomalies"),
    ("K07.3", "Anomalies of tooth position", "Dentofacial anomalies"),
    ("K07.6", "Temporomandibular joint disorders", "Dentofacial anomalies"),
    ("K08.1", "Loss of teeth due to accident, extraction or local periodontal disease", "Other disorders of teeth"),
    ("K08.3", "Retained dental root", "Other disorders of teeth"),
    ("K08.8", "Other specified disorders of teeth and supporting structures", "Other disorders of teeth"),
    ("K10.3", "Alveolitis of jaws", "Jaws"),
    ("K12.0", "Recurrent oral aphthae", "Oral mucosa"),
    ("K12.2", "Cellulitis and abscess of mouth", "Oral mucosa"),
    ("S02.5", "Fracture of tooth", "Injury"),
]
DIAGNOSIS_SOURCE = "WHO ICD-10 (2019)"

# (code, name, category, minutes, tooth requirement, surfaces allowed, sessions, billing mode,
#  follow-up kind, follow-up days, consumes stock). Prices 0: set by the clinic. Review R-06.
PROCEDURES = [
    ("EX-NEW", "New patient examination", "consultation", 30, "none", False, 1, "on_completion", "", None, False),
    ("EX-REV", "Review examination", "consultation", 20, "none", False, 1, "on_completion", "", None, False),
    ("EX-EMG", "Emergency consultation", "consultation", 20, "optional", False, 1, "on_completion", "", None, False),
    ("PR-SCL", "Scaling and polishing", "preventive", 45, "none", False, 1, "on_completion", "preventive", 180, True),
    ("PR-FLU", "Fluoride application", "preventive", 15, "none", False, 1, "on_completion", "", None, True),
    ("PR-SEAL", "Fissure sealant (per tooth)", "preventive", 15, "required", True, 1, "on_completion", "", None, True),
    ("RS-COMP1", "Composite restoration, one surface", "restorative", 30, "required", True, 1, "on_completion",
     "", None, True),
    ("RS-COMP2", "Composite restoration, two or more surfaces", "restorative", 45, "required", True, 1,
     "on_completion", "", None, True),
    ("RS-GIC", "Glass ionomer restoration", "restorative", 30, "required", True, 1, "on_completion", "", None, True),
    ("RS-TEMP", "Temporary restoration", "restorative", 20, "required", True, 1, "on_completion", "", None, True),
    ("EN-PULP", "Pulpotomy / pulp therapy", "endodontics", 45, "required", False, 1, "on_completion",
     "post_op", 14, True),
    ("EN-RCT", "Root canal treatment", "endodontics", 60, "required", False, 3, "per_session",
     "rct_continuation", 7, True),
    ("EN-RERCT", "Root canal retreatment", "endodontics", 75, "required", False, 3, "per_session",
     "rct_continuation", 7, True),
    ("OS-EXT", "Simple extraction", "oral_surgery", 30, "required", False, 1, "on_completion", "post_op", 7, True),
    ("OS-SEXT", "Surgical extraction", "oral_surgery", 60, "required", False, 1, "on_completion", "post_op", 7, True),
    ("PE-EXAM", "Periodontal examination", "periodontics", 30, "none", False, 1, "on_completion", "", None, False),
    ("PE-SRP", "Scaling and root planing (per quadrant)", "periodontics", 45, "none", False, 1, "on_completion",
     "perio_review", 42, True),
    ("PS-CRPREP", "Crown preparation and impression", "prosthodontics", 60, "required", False, 1, "on_completion",
     "crown_bridge", 14, True),
    ("PS-CRFIT", "Crown fitting", "prosthodontics", 30, "required", False, 1, "on_completion", "post_op", 14, True),
    ("PS-BRIDGE", "Bridge (preparation, fitting)", "prosthodontics", 90, "optional", False, 2, "on_completion",
     "crown_bridge", 14, True),
    ("PS-DENT", "Denture (impressions to fitting)", "prosthodontics", 45, "none", False, 4, "on_completion",
     "post_op", 7, True),
    ("PS-DREP", "Denture repair or reline", "prosthodontics", 30, "none", False, 1, "on_completion", "", None, True),
    ("OR-CONS", "Orthodontic consultation", "orthodontics", 30, "none", False, 1, "on_completion", "", None, False),
    ("OR-ADJ", "Orthodontic adjustment", "orthodontics", 20, "none", False, 1, "per_session", "ortho_adjustment", 28,
     True),
    ("IM-CONS", "Implant consultation", "implants", 30, "optional", False, 1, "on_completion", "", None, False),
    ("CO-WHITE", "Tooth whitening", "cosmetic", 60, "none", False, 1, "on_completion", "", None, True),
    ("IMG-PA", "Periapical radiograph", "imaging", 10, "optional", False, 1, "on_completion", "", None, False),
    ("IMG-BW", "Bitewing radiographs", "imaging", 10, "none", False, 1, "on_completion", "", None, False),
    ("IMG-OPG", "Panoramic radiograph (OPG)", "imaging", 15, "none", False, 1, "on_completion", "", None, False),
]

# (code, name, category, minutes)
APPOINTMENT_TYPES = [
    ("new-patient", "New patient dental consultation", "consultation", 30),
    ("examination", "Dental examination", "consultation", 20),
    ("urgent", "Toothache or urgent dental visit", "consultation", 20),
    ("filling", "Filling / restoration", "procedure", 45),
    ("extraction", "Extraction", "procedure", 30),
    ("root-canal", "Root canal session", "procedure", 60),
    ("scaling", "Scaling and polishing", "procedure", 45),
    ("perio-review", "Periodontal review", "review", 30),
    ("crown-prep", "Crown or bridge preparation", "procedure", 60),
    ("crown-fit", "Crown or bridge fitting", "procedure", 30),
    ("denture", "Denture consultation or fitting", "procedure", 45),
    ("ortho", "Orthodontic consultation or adjustment", "procedure", 30),
    ("follow-up", "Follow-up", "review", 15),
    ("post-op", "Post-procedure review", "review", 15),
    ("imaging", "Dental imaging", "imaging", 15),
]

# Medical risk review questions. Review R-08. Answers are yes / no / unknown with a free-text detail.
RISK_QUESTIONS = [
    ("cardiovascular", "Heart or blood-pressure condition"),
    ("diabetes", "Diabetes"),
    ("bleeding", "Bleeding disorder, or taking blood thinners"),
    ("immune", "Condition or treatment that weakens the immune system"),
    ("pregnancy", "Pregnant or possibly pregnant"),
    ("anaesthesia_reaction", "Previous reaction to local anaesthetic or dental treatment"),
    ("surgery_hospital", "Relevant surgery or hospital admission"),
    ("other", "Other condition the dentist should know about"),
]
RISK_QUESTION_KEYS = tuple(k for k, _ in RISK_QUESTIONS)
RISK_ANSWERS = ("yes", "no", "unknown", "not_applicable")
