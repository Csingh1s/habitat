from __future__ import annotations

import re
from dataclasses import dataclass

EXTERIOR = (
    "roof", "shingle", "eavestrough", "gutter", "downspout", "siding", "brick", "stucco",
    "mortar", "soffit", "fascia", "chimney", "grading", "driveway", "walkway", "porch",
    "deck", "garage door", "exterior", "landscap", "sod", "balcony", "foundation wall",
    "parging", "caulk", "flashing", "stoop", "fence", "lot ", "weeping tile", "window well",
)
INTERIOR = (
    "ceiling", "drywall", "floor", "baseboard", "trim", "cabinet", "countertop", "bathroom",
    "kitchen", "basement", "stair", "railing", "paint", "tile", "faucet", "sink", "toilet",
    "tub", "shower", "outlet", "switch", "furnace", "attic", "closet", "bedroom", "living room",
    "interior", "hallway", "laundry", "fireplace", "door", "crack", "nail pop",
)
# Weak words that appear in both contexts are intentionally omitted (e.g. "window").


@dataclass(frozen=True)
class Classification:
    area: str  # "exterior", "interior", or "needs_review"
    exterior_hits: tuple[str, ...]
    interior_hits: tuple[str, ...]


def _hits(text: str, words: tuple[str, ...]) -> tuple[str, ...]:
    lowered = f" {text.lower()} "
    return tuple(w for w in words if re.search(re.escape(w), lowered))


def classify(text: str, section: str = "") -> Classification:
    ext = _hits(text, EXTERIOR)
    inte = _hits(text, INTERIOR)
    ext_score = len(ext) + 2 * len(_hits(section, EXTERIOR))
    int_score = len(inte) + 2 * len(_hits(section, INTERIOR))
    if ext_score > int_score:
        area = "exterior"
    elif int_score > ext_score:
        area = "interior"
    else:
        area = "needs_review"
    return Classification(area, ext, inte)
