"""Persistence: remembers every property seen so reruns only surface what's new."""

from __future__ import annotations

import json
import sqlite3
import urllib.parse
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from farmscout.domain.models import Evaluation, PropertyFacts, RuleOutcome, Status

_TRACKING = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "gclid", "fbclid"}


def normalize_url(url: str) -> str:
    p = urllib.parse.urlparse(url.strip())
    query = urllib.parse.urlencode(
        sorted((k, v) for k, v in urllib.parse.parse_qsl(p.query) if k.lower() not in _TRACKING)
    )
    host = p.netloc.lower().removeprefix("www.")
    return urllib.parse.urlunparse(("https", host, p.path.rstrip("/"), "", query, ""))


@dataclass
class StoredCandidate:
    evaluation: Evaluation
    first_seen: str
    last_seen: str


class CandidateRepository(ABC):
    @abstractmethod
    def has(self, url: str) -> bool: ...

    @abstractmethod
    def save(self, evaluation: Evaluation) -> bool:
        """Upsert; return True if the property is new."""

    @abstractmethod
    def all(self) -> list[StoredCandidate]: ...


class SqliteCandidateRepository(CandidateRepository):
    def __init__(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path))
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS candidates (
                url_key TEXT PRIMARY KEY, url TEXT, first_seen TEXT, last_seen TEXT,
                score REAL, disqualified INTEGER, facts_json TEXT, outcomes_json TEXT)"""
        )
        self._db.commit()

    def has(self, url: str) -> bool:
        row = self._db.execute("SELECT 1 FROM candidates WHERE url_key=?", (normalize_url(url),)).fetchone()
        return row is not None

    def save(self, evaluation: Evaluation) -> bool:
        key = normalize_url(evaluation.facts.url)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        is_new = not self.has(evaluation.facts.url)
        outcomes = [
            {**o.__dict__, "status": o.status.value} for o in evaluation.outcomes
        ]
        self._db.execute(
            """INSERT INTO candidates VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(url_key) DO UPDATE SET last_seen=excluded.last_seen, score=excluded.score,
               disqualified=excluded.disqualified, facts_json=excluded.facts_json,
               outcomes_json=excluded.outcomes_json""",
            (key, evaluation.facts.url, now, now, evaluation.score, int(evaluation.disqualified),
             json.dumps(evaluation.facts.to_dict()), json.dumps(outcomes)),
        )
        self._db.commit()
        return is_new

    def all(self) -> list[StoredCandidate]:
        rows = self._db.execute(
            "SELECT facts_json, outcomes_json, score, disqualified, first_seen, last_seen FROM candidates"
        ).fetchall()
        out = []
        for facts_json, outcomes_json, score, dq, first, last in rows:
            outcomes = [RuleOutcome(**{**o, "status": Status(o["status"])}) for o in json.loads(outcomes_json)]
            ev = Evaluation(PropertyFacts.from_dict(json.loads(facts_json)), outcomes, score, bool(dq))
            out.append(StoredCandidate(ev, first, last))
        return out
