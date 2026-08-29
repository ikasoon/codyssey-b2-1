"""애플리케이션의 데이터 모델과 값 검증 함수."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Mapping
from uuid import uuid4

from budget_app.errors import DataFormatError, ValidationError


TRANSACTION_TYPES = ("income", "expense")
STORAGE_TRANSACTION_FIELDS = (
    "id",
    "date",
    "type",
    "category",
    "amount",
    "memo",
    "tags",
)
EXCHANGE_TRANSACTION_FIELDS = (
    "date",
    "type",
    "category",
    "amount",
    "memo",
    "tags",
)


def validate_date(value: str, field_name: str = "날짜") -> str:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            f"{field_name} 형식이 올바르지 않습니다: {value!r}",
            "YYYY-MM-DD 형식으로 입력해 주세요.",
        ) from exc
    if parsed.isoformat() != value:
        raise ValidationError(
            f"{field_name} 형식이 올바르지 않습니다: {value!r}",
            "YYYY-MM-DD 형식으로 입력해 주세요.",
        )
    return value


def validate_month(value: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}", value):
        raise ValidationError(
            f"월 형식이 올바르지 않습니다: {value!r}",
            "YYYY-MM 형식으로 입력해 주세요.",
        )
    try:
        date.fromisoformat(f"{value}-01")
    except ValueError as exc:
        raise ValidationError(
            f"존재하지 않는 월입니다: {value!r}",
            "YYYY-MM 형식의 실제 월을 입력해 주세요.",
        ) from exc
    return value


def validate_type(value: str) -> str:
    if value not in TRANSACTION_TYPES:
        raise ValidationError(
            f"거래 타입은 income 또는 expense여야 합니다: {value!r}",
            "수입은 income, 지출은 expense로 입력해 주세요.",
        )
    return value


def validate_amount(value: int | str, field_name: str = "금액") -> int:
    try:
        amount = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            f"{field_name}은 정수여야 합니다: {value!r}",
            "0보다 큰 정수로 입력해 주세요.",
        ) from exc
    if isinstance(value, bool) or amount <= 0:
        raise ValidationError(
            f"{field_name}은 0보다 커야 합니다: {value!r}",
            "0보다 큰 정수로 입력해 주세요.",
        )
    return amount


def validate_category_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise ValidationError("카테고리 이름은 비워 둘 수 없습니다.")
    if "\n" in name or "\r" in name:
        raise ValidationError(
            "카테고리 이름에는 줄바꿈을 넣을 수 없습니다.",
            "한 줄의 카테고리 이름을 입력해 주세요.",
        )
    return name


def parse_tags(value: str | tuple[str, ...] | list[str]) -> tuple[str, ...]:
    raw_tags = value.split(",") if isinstance(value, str) else value
    tags: list[str] = []
    for raw_tag in raw_tags:
        tag = str(raw_tag).strip()
        if not tag or tag in tags:
            continue
        if "\n" in tag or "\r" in tag:
            raise ValidationError("태그에는 줄바꿈을 넣을 수 없습니다.")
        tags.append(tag)
    return tuple(tags)


@dataclass(frozen=True, slots=True)
class Transaction:
    id: str
    date: str
    type: str
    category: str
    amount: int
    memo: str = ""
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValidationError("거래 id는 비워 둘 수 없습니다.")
        object.__setattr__(self, "date", validate_date(self.date))
        object.__setattr__(self, "type", validate_type(self.type))
        object.__setattr__(self, "category", validate_category_name(self.category))
        object.__setattr__(self, "amount", validate_amount(self.amount))
        object.__setattr__(self, "memo", self.memo.strip())
        object.__setattr__(self, "tags", parse_tags(self.tags))

    @classmethod
    def create(
        cls,
        *,
        date: str,
        type: str,
        category: str,
        amount: int | str,
        memo: str = "",
        tags: str | tuple[str, ...] | list[str] = (),
    ) -> Transaction:
        return cls(
            id=str(uuid4()),
            date=date,
            type=type,
            category=category,
            amount=validate_amount(amount),
            memo=memo,
            tags=parse_tags(tags),
        )

    @classmethod
    def from_storage_row(cls, row: Mapping[str, str]) -> Transaction:
        try:
            return cls(
                id=row["id"],
                date=row["date"],
                type=row["type"],
                category=row["category"],
                amount=validate_amount(row["amount"]),
                memo=row.get("memo", ""),
                tags=parse_tags(row.get("tags", "")),
            )
        except (KeyError, ValidationError) as exc:
            raise DataFormatError(
                f"거래 저장 행의 형식이 올바르지 않습니다: {dict(row)!r}",
                "transactions.csv를 복구하거나 올바른 헤더와 값으로 수정해 주세요.",
            ) from exc

    def to_storage_row(self) -> dict[str, str]:
        return {
            "id": self.id,
            "date": self.date,
            "type": self.type,
            "category": self.category,
            "amount": str(self.amount),
            "memo": self.memo,
            "tags": ",".join(self.tags),
        }

    def to_exchange_row(self) -> dict[str, str]:
        row = self.to_storage_row()
        return {field: row[field] for field in EXCHANGE_TRANSACTION_FIELDS}


@dataclass(frozen=True, slots=True)
class MonthlySummary:
    month: str
    count: int
    income: int
    expense: int
    balance: int
    category_expenses: tuple[tuple[str, int], ...]
    budget: int | None

    @property
    def budget_usage(self) -> float | None:
        if self.budget is None:
            return None
        return self.expense / self.budget * 100

    @property
    def is_over_budget(self) -> bool:
        return self.budget is not None and self.expense > self.budget
