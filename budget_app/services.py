"""CLI와 CSV 저장소 사이의 업무 규칙."""

from __future__ import annotations

import csv
from calendar import monthrange
from dataclasses import replace
from itertools import islice
from pathlib import Path
from typing import Iterator

from budget_app.errors import DataFormatError, NotFoundError, ValidationError
from budget_app.models import (
    EXCHANGE_TRANSACTION_FIELDS,
    MonthlySummary,
    Transaction,
    parse_tags,
    validate_amount,
    validate_category_name,
    validate_date,
    validate_month,
    validate_type,
)
from budget_app.repositories import CsvStores


class BudgetService:
    def __init__(self, data_dir: Path | str = "data") -> None:
        self.stores = CsvStores(data_dir)

    def _require_category(self, category: str) -> str:
        category = validate_category_name(category)
        if not self.stores.categories.contains(category):
            raise ValidationError(
                f"등록되지 않은 카테고리입니다: {category}",
                "category list로 확인하거나 category add로 먼저 등록해 주세요.",
            )
        return category

    def add_transaction(
        self,
        *,
        date: str,
        type: str,
        category: str,
        amount: int | str,
        memo: str = "",
        tags: str = "",
    ) -> Transaction:
        transaction = Transaction.create(
            date=validate_date(date),
            type=validate_type(type),
            category=self._require_category(category),
            amount=validate_amount(amount),
            memo=memo,
            tags=parse_tags(tags),
        )
        self.stores.transactions.add(transaction)
        return transaction

    def list_transactions(self, limit: int = 20) -> Iterator[Transaction]:
        if limit <= 0:
            raise ValidationError("--limit은 0보다 커야 합니다.")
        yield from islice(self.stores.transactions.iter_all(), limit)

    def search_transactions(
        self,
        *,
        from_date: str | None = None,
        to_date: str | None = None,
        category: str | None = None,
        transaction_type: str | None = None,
        query: str | None = None,
        tag: str | None = None,
    ) -> Iterator[Transaction]:
        if from_date is not None:
            validate_date(from_date, "시작 날짜")
        if to_date is not None:
            validate_date(to_date, "종료 날짜")
        if from_date and to_date and from_date > to_date:
            raise ValidationError(
                "--from이 --to보다 늦습니다.",
                "시작 날짜가 종료 날짜보다 빠르거나 같게 입력해 주세요.",
            )
        if category is not None:
            category = self._require_category(category)
        if transaction_type is not None:
            validate_type(transaction_type)
        normalized_query = query.casefold() if query else None

        for transaction in self.stores.transactions.iter_all():
            if from_date and transaction.date < from_date:
                continue
            if to_date and transaction.date > to_date:
                continue
            if category and transaction.category != category:
                continue
            if transaction_type and transaction.type != transaction_type:
                continue
            if normalized_query and normalized_query not in transaction.memo.casefold():
                continue
            if tag and tag not in transaction.tags:
                continue
            yield transaction

    def update_transaction(
        self,
        transaction_id: str,
        *,
        date: str | None = None,
        type: str | None = None,
        category: str | None = None,
        amount: int | str | None = None,
        memo: str | None = None,
        tags: str | None = None,
    ) -> Transaction:
        current = self.stores.transactions.get(transaction_id)
        if current is None:
            raise NotFoundError(
                f"거래를 찾을 수 없습니다: {transaction_id}",
                "list 명령으로 id를 확인해 주세요.",
            )
        replacement = replace(
            current,
            date=validate_date(date) if date is not None else current.date,
            type=validate_type(type) if type is not None else current.type,
            category=self._require_category(category)
            if category is not None
            else current.category,
            amount=validate_amount(amount) if amount is not None else current.amount,
            memo=memo if memo is not None else current.memo,
            tags=parse_tags(tags) if tags is not None else current.tags,
        )
        self.stores.transactions.update(transaction_id, replacement)
        return replacement

    def delete_transaction(self, transaction_id: str) -> None:
        self.stores.transactions.delete(transaction_id)

    def monthly_summary(self, month: str, top: int = 3) -> MonthlySummary:
        month = validate_month(month)
        if top <= 0:
            raise ValidationError("--top은 0보다 커야 합니다.")
        income = 0
        expense = 0
        count = 0
        categories: dict[str, int] = {}
        for transaction in self.stores.transactions.iter_all():
            if not transaction.date.startswith(f"{month}-"):
                continue
            count += 1
            if transaction.type == "income":
                income += transaction.amount
            else:
                expense += transaction.amount
                categories[transaction.category] = (
                    categories.get(transaction.category, 0) + transaction.amount
                )
        top_categories = tuple(
            sorted(categories.items(), key=lambda item: (-item[1], item[0]))[:top]
        )
        return MonthlySummary(
            month=month,
            count=count,
            income=income,
            expense=expense,
            balance=income - expense,
            category_expenses=top_categories,
            budget=self.stores.budgets.get(month),
        )

    def set_budget(self, month: str, amount: int | str) -> int:
        return self.stores.budgets.set(month, amount)

    def get_budget(self, month: str) -> int | None:
        return self.stores.budgets.get(month)

    def list_budgets(self) -> Iterator[tuple[str, int]]:
        yield from self.stores.budgets.iter_all()

    def list_categories(self) -> Iterator[str]:
        yield from self.stores.categories.iter_all()

    def add_category(self, category: str) -> str:
        return self.stores.categories.add(category)

    def remove_category(self, category: str) -> None:
        category = validate_category_name(category)
        if self.stores.transactions.uses_category(category):
            raise ValidationError(
                f"사용 중인 카테고리는 삭제할 수 없습니다: {category}",
                "해당 거래의 카테고리를 update한 뒤 다시 시도해 주세요.",
            )
        self.stores.categories.remove(category)

    def import_csv(self, source: Path | str) -> int:
        source_path = Path(source).expanduser()
        transactions: list[Transaction] = []
        try:
            with source_path.open("r", encoding="utf-8-sig", newline="") as file:
                reader = csv.DictReader(file)
                if tuple(reader.fieldnames or ()) != EXCHANGE_TRANSACTION_FIELDS:
                    raise DataFormatError(
                        f"가져오기 CSV 헤더가 올바르지 않습니다: {reader.fieldnames!r}",
                        f"헤더를 {','.join(EXCHANGE_TRANSACTION_FIELDS)} 순서로 맞춰 주세요.",
                    )
                for line_number, row in enumerate(reader, start=2):
                    if None in row:
                        raise DataFormatError(
                            f"가져오기 CSV {line_number}행의 열 개수가 올바르지 않습니다.",
                            "각 행을 헤더의 6개 열에 맞추고 쉼표와 인용 부호를 확인해 주세요.",
                        )
                    missing_fields = [
                        field
                        for field in ("date", "type", "category", "amount")
                        if not (row.get(field) or "").strip()
                    ]
                    if missing_fields:
                        raise ValidationError(
                            f"가져오기 CSV {line_number}행의 필수 값이 없습니다: "
                            f"{', '.join(missing_fields)}",
                            "date, type, category, amount 값을 모두 입력해 주세요.",
                        )
                    try:
                        transactions.append(
                            Transaction.create(
                                date=validate_date(row["date"]),
                                type=validate_type(row["type"]),
                                category=self._require_category(row["category"]),
                                amount=validate_amount(row["amount"]),
                                memo=row.get("memo") or "",
                                tags=parse_tags(row.get("tags") or ""),
                            )
                        )
                    except ValidationError as exc:
                        raise ValidationError(
                            f"가져오기 CSV {line_number}행 오류: {exc}",
                            exc.hint,
                        ) from exc
        except FileNotFoundError as exc:
            raise NotFoundError(
                f"가져올 파일을 찾을 수 없습니다: {source_path}",
                "--from 경로를 확인해 주세요.",
            ) from exc
        return self.stores.transactions.add_many(transactions)

    def export_csv(
        self,
        destination: Path | str,
        *,
        month: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> int:
        if month is not None and (from_date is not None or to_date is not None):
            raise ValidationError(
                "export의 --month와 --from/--to는 함께 사용할 수 없습니다.",
                "월 또는 날짜 범위 중 한 가지 방식만 선택해 주세요.",
            )
        if (from_date is None) != (to_date is None):
            raise ValidationError(
                "export의 --from과 --to는 함께 지정해야 합니다.",
                "--month를 사용하거나 --from과 --to를 모두 입력해 주세요.",
            )
        if month is None and from_date is None:
            raise ValidationError(
                "export에는 --month 또는 --from/--to 날짜 범위 조건이 필요합니다."
            )
        if month is not None:
            validate_month(month)
            year, month_number = (int(part) for part in month.split("-"))
            month_from = f"{month}-01"
            month_to = f"{month}-{monthrange(year, month_number)[1]:02d}"
            if from_date is None:
                from_date = month_from
            if to_date is None:
                to_date = month_to
        if from_date is not None:
            validate_date(from_date, "시작 날짜")
        if to_date is not None:
            validate_date(to_date, "종료 날짜")
        if from_date and to_date and from_date > to_date:
            raise ValidationError("--from이 --to보다 늦습니다.")

        destination_path = Path(destination).expanduser()
        protected_paths = {path.resolve() for path in self.stores.persistent_paths}
        if destination_path.resolve() in protected_paths:
            raise ValidationError(
                "내보내기 파일로 앱의 저장 파일을 덮어쓸 수 없습니다.",
                "--out에 data 폴더 밖의 다른 파일을 지정해 주세요.",
            )
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with destination_path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=EXCHANGE_TRANSACTION_FIELDS)
            writer.writeheader()
            for transaction in self.search_transactions(
                from_date=from_date, to_date=to_date
            ):
                writer.writerow(transaction.to_exchange_row())
                count += 1
        return count
