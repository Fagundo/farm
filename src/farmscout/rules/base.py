"""Rule abstraction. Each rule is one criterion; the engine composes them."""

from __future__ import annotations

from abc import ABC, abstractmethod

from farmscout.domain.models import PropertyFacts, RuleOutcome, Status


class Rule(ABC):
    """A single criterion evaluated against :class:`PropertyFacts`."""

    rule_id: str = "rule"
    hard: bool = False
    penalty: bool = False

    def __init__(self, max_points: float = 0.0) -> None:
        self.max_points = max_points

    @abstractmethod
    def evaluate(self, facts: PropertyFacts) -> RuleOutcome: ...

    # Small helpers so subclasses stay declarative.
    def _out(self, status: Status, fraction: float, reason: str) -> RuleOutcome:
        return RuleOutcome(
            rule_id=self.rule_id,
            status=status,
            points=round(self.max_points * fraction, 2),
            max_points=self.max_points,
            reason=reason,
            hard=self.hard,
            penalty=self.penalty,
        )

    def passed(self, reason: str) -> RuleOutcome:
        return self._out(Status.PASS, 1.0, reason)

    def partial(self, fraction: float, reason: str) -> RuleOutcome:
        return self._out(Status.PARTIAL, fraction, reason)

    def failed(self, reason: str) -> RuleOutcome:
        return self._out(Status.FAIL, 0.0, reason)

    def unknown(self, reason: str) -> RuleOutcome:
        return self._out(Status.UNKNOWN, 0.0, reason)


class HardRule(Rule):
    """Gate: a FAIL disqualifies the property. Carries no points."""

    hard = True


class PenaltyRule(Rule):
    """Red flag: when triggered, subtracts ``max_points`` from the score."""

    penalty = True

    def triggered(self, reason: str) -> RuleOutcome:
        return RuleOutcome(self.rule_id, Status.FAIL, -self.max_points, self.max_points,
                           reason, penalty=True)

    def clear(self, reason: str = "") -> RuleOutcome:
        return RuleOutcome(self.rule_id, Status.PASS, 0.0, self.max_points, reason, penalty=True)
