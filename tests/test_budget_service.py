from __future__ import annotations

import csv
import inspect
from pathlib import Path

import pytest

from budget_app.errors import NotFoundError, ValidationError
from budget_app.services import BudgetService


@pytest.fixture
def service(tmp_path: Path) -> BudgetService:
    return BudgetService(tmp_path / "data")


def test_첫_실행은_필수_CSV와_기본_카테고리를_생성한다(
    service: BudgetService,
) -> None:
    data_dir = service.stores.data_dir
    assert (data_dir / "transactions.csv").is_file()
    assert (data_dir / "categories.csv").is_file()
    assert (data_dir / "budgets.csv").is_file()
    assert {path.name for path in data_dir.iterdir()} == {
        "transactions.csv",
        "categories.csv",
        "budgets.csv",
    }
    assert "food" in list(service.list_categories())


def test_헤더만_있는_카테고리_CSV는_기본값으로_복구된다(
    service: BudgetService,
) -> None:
    categories_path = service.stores.categories_path
    categories_path.write_text("name\n", encoding="utf-8")

    restarted = BudgetService(service.stores.data_dir)
    assert list(restarted.list_categories()) == [
        "food",
        "transport",
        "rent",
        "salary",
        "leisure",
        "other",
    ]


def test_목록과_검색은_최신순_제너레이터를_반환한다(
    service: BudgetService,
) -> None:
    older = service.add_transaction(
        date="2026-07-01",
        type="expense",
        category="food",
        amount=5000,
        memo="점심",
        tags="식사,회사",
    )
    newer = service.add_transaction(
        date="2026-08-01",
        type="income",
        category="salary",
        amount=100000,
        memo="용돈",
        tags="정기",
    )

    listed = service.list_transactions(limit=2)
    searched = service.search_transactions(transaction_type="expense", tag="식사")
    assert inspect.isgenerator(listed)
    assert inspect.isgenerator(searched)
    assert [item.id for item in listed] == [newer.id, older.id]
    assert [item.id for item in searched] == [older.id]


def test_거래_수정은_최신순으로_재정렬하고_삭제는_거래를_제거한다(
    service: BudgetService,
) -> None:
    first = service.add_transaction(
        date="2026-08-01",
        type="expense",
        category="food",
        amount=1000,
    )
    second = service.add_transaction(
        date="2026-08-02",
        type="expense",
        category="transport",
        amount=2000,
    )

    updated = service.update_transaction(
        first.id, date="2026-08-03", amount=3000, memo="수정"
    )
    assert updated.id == first.id
    assert [item.id for item in service.list_transactions(10)] == [
        first.id,
        second.id,
    ]

    service.delete_transaction(second.id)
    assert [item.id for item in service.list_transactions(10)] == [first.id]
    with pytest.raises(NotFoundError):
        service.delete_transaction("missing-id")


def test_월별_요약은_예산_사용률과_상위_지출을_포함한다(
    service: BudgetService,
) -> None:
    service.add_transaction(
        date="2026-08-01",
        type="income",
        category="salary",
        amount=100000,
    )
    service.add_transaction(
        date="2026-08-02",
        type="expense",
        category="food",
        amount=30000,
    )
    service.add_transaction(
        date="2026-08-03",
        type="expense",
        category="transport",
        amount=25000,
    )
    service.set_budget("2026-08", 50000)

    summary = service.monthly_summary("2026-08", top=1)
    assert summary.income == 100000
    assert summary.expense == 55000
    assert summary.balance == 45000
    assert summary.category_expenses == (("food", 30000),)
    assert summary.budget_usage == pytest.approx(110.0)
    assert summary.is_over_budget


def test_사용_중인_카테고리는_삭제할_수_없다(service: BudgetService) -> None:
    service.add_category("gift")
    transaction = service.add_transaction(
        date="2026-08-01",
        type="income",
        category="gift",
        amount=10000,
    )
    with pytest.raises(ValidationError):
        service.remove_category("gift")

    service.update_transaction(transaction.id, category="other")
    service.remove_category("gift")
    assert "gift" not in list(service.list_categories())


def test_CSV_가져오기와_내보내기는_고정_스키마를_사용한다(
    service: BudgetService, tmp_path: Path
) -> None:
    source = tmp_path / "source.csv"
    with source.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=("date", "type", "category", "amount", "memo", "tags"),
        )
        writer.writeheader()
        writer.writerow(
            {
                "date": "2026-02-28",
                "type": "expense",
                "category": "food",
                "amount": "12000",
                "memo": "저녁, 외식",
                "tags": "식사,친구",
            }
        )

    assert service.import_csv(source) == 1
    destination = tmp_path / "export.csv"
    assert service.export_csv(destination, month="2026-02") == 1
    with destination.open("r", encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    assert list(rows[0]) == ["date", "type", "category", "amount", "memo", "tags"]
    assert rows[0]["memo"] == "저녁, 외식"
    assert rows[0]["tags"] == "식사,친구"


def test_CSV_가져오기는_누락된_선택_열_값을_허용한다(
    service: BudgetService, tmp_path: Path
) -> None:
    source = tmp_path / "optional-values.csv"
    source.write_text(
        "date,type,category,amount,memo,tags\n"
        "2026-08-01,expense,food,12000\n"
        "2026-08-02,expense,food,13000,점심\n",
        encoding="utf-8",
    )

    assert service.import_csv(source) == 2
    transactions = list(service.list_transactions(2))
    assert transactions[0].memo == "점심"
    assert transactions[0].tags == ()
    assert transactions[1].memo == ""
    assert transactions[1].tags == ()


def test_CSV_가져오기는_누락된_필수_값을_거부한다(
    service: BudgetService, tmp_path: Path
) -> None:
    source = tmp_path / "missing-required.csv"
    source.write_text(
        "date,type,category,amount,memo,tags\n"
        "2026-08-01,expense,food,12000,,\n"
        "2026-08-01,expense,food\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        service.import_csv(source)
    assert list(service.list_transactions(10)) == []


@pytest.mark.parametrize(
    "values",
    [
        {"date": "2026-02-30", "type": "expense", "category": "food", "amount": 1},
        {"date": "2026-02-01", "type": "wrong", "category": "food", "amount": 1},
        {
            "date": "2026-02-01",
            "type": "expense",
            "category": "missing",
            "amount": 1,
        },
        {"date": "2026-02-01", "type": "expense", "category": "food", "amount": 0},
    ],
    ids=("invalid-date", "invalid-type", "missing-category", "zero-amount"),
)
def test_잘못된_거래_입력값은_거부된다(
    service: BudgetService, values: dict[str, str | int]
) -> None:
    with pytest.raises(ValidationError):
        service.add_transaction(**values)


def test_검색은_등록되지_않은_카테고리를_거부한다(
    service: BudgetService,
) -> None:
    with pytest.raises(ValidationError):
        list(service.search_transactions(category="not-registered"))


def test_CSV_내보내기는_완전한_날짜_범위를_요구한다(
    service: BudgetService, tmp_path: Path
) -> None:
    destination = tmp_path / "range.csv"
    with pytest.raises(ValidationError):
        service.export_csv(destination, from_date="2026-08-01")
    with pytest.raises(ValidationError):
        service.export_csv(destination, to_date="2026-08-31")
    with pytest.raises(ValidationError):
        service.export_csv(
            destination,
            month="2026-08",
            from_date="2026-08-01",
            to_date="2026-08-31",
        )
    assert not destination.exists()

    assert (
        service.export_csv(
            destination, from_date="2026-08-01", to_date="2026-08-31"
        )
        == 0
    )
    assert destination.exists()
