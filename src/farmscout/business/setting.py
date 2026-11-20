"""Secluded vs. roadside: a quiet setting suits a sauna/spa/retreat; highway frontage does not."""

from __future__ import annotations

import re
from collections.abc import Iterable

SECLUDED = "secluded"
ROADSIDE = "roadside"

DEFAULT_SECLUDED = (
    r"seclu(?:ded|sion)", r"\bprivate (?:setting|retreat|oasis|acreage|location)", r"\bprivacy\b",
    r"end of (?:the )?(?:road|lane)", r"dead[- ]end", r"tucked (?:away|back)", r"off[- ]grid",
    r"(?:borders?|adjoins?|adjacent to|backs (?:up )?(?:on)?to) (?:the )?(?:\w+ )?(?:national|state|public) (?:forest|land|park)",
    r"surrounded by (?:forest|trees|timber)", r"peaceful|tranquil|serene|quiet (?:country )?(?:road|setting)",
)
DEFAULT_ROADSIDE = (
    r"(?:highway|hwy|freeway|interstate|I-\d+|state route|SR[- ]?\d+|US[- ]?\d+)(?:[ -]?\d+)? frontage",
    r"frontage (?:on|along) (?:the )?(?:highway|hwy|freeway|interstate|I-\d+|SR[- ]?\d+|US[- ]?\d+)",
    r"\b(?:on|along|fronting) (?:hwy|highway|I-|US[- ]|SR[- ]|state route )\s?\d+",
    r"high[- ]traffic", r"traffic count", r"(?:visible|visibility) from (?:the )?(?:highway|hwy|freeway|interstate)",
)


class SettingDetector:
    """Classifies listing text as secluded, roadside or unknown. Roadside wins when both appear,
    since highway frontage is a hard fact while "peaceful" is marketing."""

    def __init__(self, secluded: Iterable[str] = DEFAULT_SECLUDED, roadside: Iterable[str] = DEFAULT_ROADSIDE) -> None:
        self._secluded = [re.compile(p, re.I) for p in secluded]
        self._roadside = [re.compile(p, re.I) for p in roadside]

    def detect(self, *texts: str | None) -> str | None:
        text = " ".join(t for t in texts if t)
        if any(p.search(text) for p in self._roadside):
            return ROADSIDE
        if any(p.search(text) for p in self._secluded):
            return SECLUDED
        return None
