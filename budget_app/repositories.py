"""CSV 영구 저장소. 조회는 제너레이터, 변경은 전체 재작성을 사용한다."""

from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence

from budget_app.errors import DataFormatError, NotFoundError, ValidationError
from budget_app.models import (
    STORAGE_TRANSACTION_FIELDS,
    Transaction,
    validate_amount,
    validate_category_name,
    validate_month,
)


DEFAULT_CATEGORIES = ("food", "transport", "rent", "salary", "leisure", "other")
CATEGORY_FIELDS = ("name",)
BUDGET_FIELDS = ("month", "amount")


def _ensure_csv(
    path: Path,
    fields: Sequence[str],
    rows: Iterable[Mapping[str, object]] = (),
) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        file.flush()
        os.fsync(file.fileno())


def _iter_dict_rows(path: Path, fields: Sequence[str]) -> Iterator[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if tuple(reader.fieldnames or ()) != tuple(fields):
            raise DataFormatError(
                f"{path.name} 헤더가 올바르지 않습니다: {reader.fieldnames!r}",
                f"헤더를 {','.join(fields)} 순서로 맞춰 주세요.",
            )
        for line_number, row in enumerate(reader, start=2):
            if None in row:
                raise DataFormatError(
                    f"{path.name} {line_number}행의 열 개수가 올바르지 않습니다.",
                    "CSV 인용 부호와 열 개수를 확인해 주세요.",
                )
            yield {key: value or "" for key, value in row.items()}


def _write_csv(
    path: Path,
    fields: Sequence[str],
    rows: Iterable[Mapping[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class TransactionRepository:
    """날짜와 id의 내림차순을 유지하는 거래 CSV 저장소."""

    def __init__(self, path: Path) -> None:
        self.path = path
        _ensure_csv(path, STORAGE_TRANSACTION_FIELDS)

    @staticmethod
    def _sort_key(transaction: Transaction) -> tuple[str, str]:
        return transaction.date, transaction.id

    def iter_all(self) -> Iterator[Transaction]:
        """파일을 한 행씩 읽으며 최신 거래부터 반환한다."""
        for row in _iter_dict_rows(self.path, STORAGE_TRANSACTION_FIELDS):
            yield Transaction.from_storage_row(row)

    def get(self, transaction_id: str) -> Transaction | None:
        for transaction in self.iter_all():
            if transaction.id == transaction_id:
                return transaction
        return None

    def add(self, transaction: Transaction) -> None:
        self.add_many((transaction,))

    def add_many(self, transactions: Iterable[Transaction]) -> int:
        additions = sorted(transactions, key=self._sort_key, reverse=True)
        if not additions:
            return 0
        addition_ids = {item.id for item in additions}
        if len(addition_ids) != len(additions):
            raise ValidationError("추가할 거래 id가 서로 중복됩니다.")

        existing = list(self.iter_all())
        duplicate = next(
            (current for current in existing if current.id in addition_ids), None
        )
        if duplicate is not None:
            raise ValidationError(
                f"이미 존재하는 거래 id입니다: {duplicate.id}",
                "새 id로 거래를 다시 추가해 주세요.",
            )
        combined = sorted(
            (*existing, *additions), key=self._sort_key, reverse=True
        )
        _write_csv(
            self.path,
            STORAGE_TRANSACTION_FIELDS,
            (item.to_storage_row() for item in combined),
        )
        return len(additions)

    def update(self, transaction_id: str, replacement: Transaction) -> None:
        transactions = list(self.iter_all())
        for index, current in enumerate(transactions):
            if current.id == transaction_id:
                transactions[index] = replacement
                break
        else:
            raise NotFoundError(
                f"거래를 찾을 수 없습니다: {transaction_id}",
                "list 명령으로 id를 확인해 주세요.",
            )
        transactions.sort(key=self._sort_key, reverse=True)
        _write_csv(
            self.path,
            STORAGE_TRANSACTION_FIELDS,
            (item.to_storage_row() for item in transactions),
        )

    def delete(self, transaction_id: str) -> None:
        transactions = list(self.iter_all())
        remaining = [item for item in transactions if item.id != transaction_id]
        if len(remaining) == len(transactions):
            raise NotFoundError(
                f"거래를 찾을 수 없습니다: {transaction_id}",
                "list 명령으로 id를 확인해 주세요.",
            )
        _write_csv(
            self.path,
            STORAGE_TRANSACTION_FIELDS,
            (item.to_storage_row() for item in remaining),
        )

    def uses_category(self, category: str) -> bool:
        return any(item.category == category for item in self.iter_all())


class CategoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        default_rows = ({"name": name} for name in DEFAULT_CATEGORIES)
        _ensure_csv(path, CATEGORY_FIELDS, default_rows)
        if not any(self.iter_all()):
            _write_csv(
                self.path,
                CATEGORY_FIELDS,
                ({"name": name} for name in DEFAULT_CATEGORIES),
            )

    def iter_all(self) -> Iterator[str]:
        for row in _iter_dict_rows(self.path, CATEGORY_FIELDS):
            try:
                yield validate_category_name(row["name"])
            except ValidationError as exc:
                raise DataFormatError(
                    f"categories.csv에 잘못된 카테고리가 있습니다: {row!r}",
                    "빈 카테고리나 줄바꿈을 제거해 주세요.",
                ) from exc

    def contains(self, category: str) -> bool:
        return any(name == category for name in self.iter_all())

    def add(self, category: str) -> str:
        category = validate_category_name(category)
        categories = list(self.iter_all())
        if any(name.casefold() == category.casefold() for name in categories):
            raise ValidationError(
                f"이미 존재하는 카테고리입니다: {category}",
                "category list로 등록된 이름을 확인해 주세요.",
            )
        categories.append(category)
        categories.sort(key=str.casefold)
        _write_csv(
            self.path,
            CATEGORY_FIELDS,
            ({"name": name} for name in categories),
        )
        return category

    def remove(self, category: str) -> None:
        categories = list(self.iter_all())
        if category not in categories:
            raise NotFoundError(
                f"카테고리를 찾을 수 없습니다: {category}",
                "category list로 이름을 확인해 주세요.",
            )
        _write_csv(
            self.path,
            CATEGORY_FIELDS,
            ({"name": name} for name in categories if name != category),
        )


class BudgetStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        _ensure_csv(path, BUDGET_FIELDS)

    def iter_all(self) -> Iterator[tuple[str, int]]:
        for row in _iter_dict_rows(self.path, BUDGET_FIELDS):
            try:
                yield validate_month(row["month"]), validate_amount(
                    row["amount"], "예산"
                )
            except ValidationError as exc:
                raise DataFormatError(
                    f"budgets.csv에 잘못된 값이 있습니다: {row!r}",
                    "월은 YYYY-MM, 예산은 양의 정수로 수정해 주세요.",
                ) from exc

    def get(self, month: str) -> int | None:
        month = validate_month(month)
        for stored_month, amount in self.iter_all():
            if stored_month == month:
                return amount
        return None

    def set(self, month: str, amount: int | str) -> int:
        month = validate_month(month)
        normalized_amount = validate_amount(amount, "예산")
        values = {
            stored_month: stored_amount
            for stored_month, stored_amount in self.iter_all()
        }
        values[month] = normalized_amount
        _write_csv(
            self.path,
            BUDGET_FIELDS,
            (
                {"month": stored_month, "amount": str(values[stored_month])}
                for stored_month in sorted(values, reverse=True)
            ),
        )
        return normalized_amount


class CsvStores:
    """모든 CSV 저장 파일 경로와 저장소 객체를 한곳에서 초기화한다."""

    def __init__(self, data_dir: Path | str) -> None:
        self.data_dir = Path(data_dir).expanduser()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.transactions_path = self.data_dir / "transactions.csv"
        self.categories_path = self.data_dir / "categories.csv"
        self.budgets_path = self.data_dir / "budgets.csv"
        self.transactions = TransactionRepository(self.transactions_path)
        self.categories = CategoryStore(self.categories_path)
        self.budgets = BudgetStore(self.budgets_path)

    @property
    def persistent_paths(self) -> tuple[Path, ...]:
        return (
            self.transactions_path,
            self.categories_path,
            self.budgets_path,
        )
