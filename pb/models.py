"""Domain dataclasses used across pb."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Category:
    id: int
    name: str
    kind: str  # 'income' | 'expense' | 'savings'


@dataclass(frozen=True)
class Transaction:
    id: int
    occurred_on: date
    amount_cents: int
    category_id: int
    category_name: str
    category_kind: str
    note: str | None


@dataclass(frozen=True)
class Allocation:
    category_id: int
    category_name: str
    category_kind: str  # 'expense' | 'savings' — income is not allocatable
    percent: float


@dataclass(frozen=True)
class Goal:
    id: int
    name: str
    target_cents: int
    target_date: date | None


@dataclass(frozen=True)
class GoalProgress:
    id: int
    name: str
    target_cents: int
    target_date: date | None
    contributed_cents: int
    contribution_count: int

    @property
    def remaining_cents(self) -> int:
        return max(0, self.target_cents - self.contributed_cents)

    @property
    def percent(self) -> float:
        if self.target_cents == 0:
            return 0.0
        return 100 * self.contributed_cents / self.target_cents


@dataclass(frozen=True)
class Contribution:
    id: int
    goal_id: int
    goal_name: str
    txn_id: int
    amount_cents: int
    occurred_on: date
    note: str | None
