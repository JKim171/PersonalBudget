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
