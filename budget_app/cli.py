"""argparse 기반 명령줄 인터페이스."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable, Sequence
from datetime import date as today_date
from pathlib import Path
import sys
from typing import TypeVar

from budget_app.decorators import cli_error_boundary
from budget_app.errors import ValidationError
from budget_app.models import (
    Transaction,
    parse_tags,
    validate_amount,
    validate_category_name,
    validate_date,
    validate_type,
)
from budget_app.services import BudgetService


T = TypeVar("T")


class LongOptionArgumentParser(argparse.ArgumentParser):
    """도움말까지 모든 옵션을 ``--`` 형태로만 제공한다."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        kwargs["add_help"] = False
        super().__init__(*args, **kwargs)
        self.add_argument("--help", action="help", help="사용 방법을 출력하고 종료")


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("양의 정수를 입력해야 합니다.") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("0보다 큰 정수를 입력해야 합니다.")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = LongOptionArgumentParser(
        prog="budget-app",
        description="CSV 파일로 저장하는 용돈 기입장",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        metavar="DIR",
        help="저장 CSV 폴더 (기본값: ./data, 어느 위치에서든 지정 가능)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    add = commands.add_parser("add", help="대화형으로 거래 추가")
    add.set_defaults(handler=_handle_add)

    list_parser = commands.add_parser("list", help="최신순 거래 목록")
    list_parser.add_argument("--limit", type=_positive_int, default=20)
    list_parser.set_defaults(handler=_handle_list)

    search = commands.add_parser("search", help="조건에 맞는 거래 검색")
    search.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD")
    search.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD")
    search.add_argument("--category")
    search.add_argument("--type", choices=("income", "expense"))
    search.add_argument("--q", help="메모 키워드")
    search.add_argument("--tag")
    search.set_defaults(handler=_handle_search)

    summary = commands.add_parser("summary", help="월별 수입/지출 요약")
    summary.add_argument("--month", required=True, metavar="YYYY-MM")
    summary.add_argument("--top", type=_positive_int, default=3)
    summary.set_defaults(handler=_handle_summary)

    budget = commands.add_parser("budget", help="월 예산 설정/조회")
    budget_commands = budget.add_subparsers(dest="budget_command", required=True)
    budget_set = budget_commands.add_parser("set", help="월 예산 설정")
    budget_set.add_argument("--month", required=True, metavar="YYYY-MM")
    budget_set.add_argument("--amount", required=True, type=_positive_int)
    budget_set.set_defaults(handler=_handle_budget_set)
    budget_get = budget_commands.add_parser("get", help="월 예산 조회")
    budget_get.add_argument("--month", required=True, metavar="YYYY-MM")
    budget_get.set_defaults(handler=_handle_budget_get)
    budget_list = budget_commands.add_parser("list", help="전체 월 예산 조회")
    budget_list.set_defaults(handler=_handle_budget_list)

    category = commands.add_parser("category", help="카테고리 관리")
    category_commands = category.add_subparsers(dest="category_command", required=True)
    category_add = category_commands.add_parser("add", help="카테고리 추가")
    category_add.add_argument("--name", help="생략하면 대화형으로 입력")
    category_add.set_defaults(handler=_handle_category_add)
    category_list = category_commands.add_parser("list", help="카테고리 목록")
    category_list.set_defaults(handler=_handle_category_list)
    category_remove = category_commands.add_parser("remove", help="카테고리 삭제")
    category_remove.add_argument("--name", help="생략하면 대화형으로 입력")
    category_remove.set_defaults(handler=_handle_category_remove)

    update = commands.add_parser("update", help="옵션 방식으로 거래 수정")
    update.add_argument("--id", required=True)
    update.add_argument("--date", metavar="YYYY-MM-DD")
    update.add_argument("--type", choices=("income", "expense"))
    update.add_argument("--category")
    update.add_argument("--amount", type=_positive_int)
    update.add_argument("--memo")
    update.add_argument("--tags", help="쉼표로 구분한 태그")
    update.set_defaults(handler=_handle_update)

    delete = commands.add_parser("delete", help="id로 거래 삭제")
    delete.add_argument("--id", required=True)
    delete.set_defaults(handler=_handle_delete)

    importer = commands.add_parser("import", help="CSV에서 거래 가져오기")
    importer.add_argument("--from", dest="source", required=True, metavar="CSV")
    importer.set_defaults(handler=_handle_import)

    exporter = commands.add_parser("export", help="조건에 맞는 거래를 CSV로 내보내기")
    exporter.add_argument("--out", required=True, metavar="CSV")
    exporter.add_argument("--month", metavar="YYYY-MM")
    exporter.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD")
    exporter.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD")
    exporter.set_defaults(handler=_handle_export)

    return parser


def _move_data_dir_to_front(arguments: list[str]) -> list[str]:
    """--data-dir을 명령 앞/뒤 어느 곳에 써도 전역 옵션으로 해석한다."""
    remaining: list[str] = []
    data_option: list[str] = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--data-dir":
            data_option = [argument]
            if index + 1 < len(arguments):
                data_option.append(arguments[index + 1])
                index += 1
        elif argument.startswith("--data-dir="):
            data_option = [argument]
        else:
            remaining.append(argument)
        index += 1
    return data_option + remaining


def _prompt(label: str, validator: Callable[[str], T]) -> T:
    while True:
        value = input(label).strip()
        try:
            return validator(value)
        except ValidationError as exc:
            print(f"입력 오류: {exc}")
            print(f"힌트: {exc.hint}")


def _print_transactions(transactions: Iterable[Transaction]) -> int:
    count = 0
    for item in transactions:
        count += 1
        tags = ",".join(item.tags)
        print(
            f"{item.id} | {item.date} | {item.type} | {item.category} | "
            f"{item.amount} | {item.memo} | {tags}"
        )
    if count == 0:
        print("거래 데이터가 없습니다.")
    else:
        print(f"총 {count}건")
    return count


def _handle_add(args: argparse.Namespace, service: BudgetService) -> int:
    print("거래 정보를 입력하세요. (Ctrl+C: 취소)")
    transaction_date = _prompt(
        f"날짜 (YYYY-MM-DD, 오늘 {today_date.today().isoformat()}): ", validate_date
    )
    transaction_type = _prompt("타입 (income/expense): ", validate_type)

    def existing_category(value: str) -> str:
        return service._require_category(value)

    category = _prompt("카테고리: ", existing_category)
    amount = _prompt("금액 (양의 정수): ", validate_amount)
    memo = input("메모 (선택): ").strip()
    tags = _prompt("태그 (선택, 쉼표 구분): ", parse_tags)
    transaction = service.add_transaction(
        date=transaction_date,
        type=transaction_type,
        category=category,
        amount=amount,
        memo=memo,
        tags=",".join(tags),
    )
    print(f"거래가 저장되었습니다. id={transaction.id}")
    return 0


def _handle_list(args: argparse.Namespace, service: BudgetService) -> int:
    _print_transactions(service.list_transactions(args.limit))
    return 0


def _handle_search(args: argparse.Namespace, service: BudgetService) -> int:
    _print_transactions(
        service.search_transactions(
            from_date=args.from_date,
            to_date=args.to_date,
            category=args.category,
            transaction_type=args.type,
            query=args.q,
            tag=args.tag,
        )
    )
    return 0


def _handle_summary(args: argparse.Namespace, service: BudgetService) -> int:
    summary = service.monthly_summary(args.month, args.top)
    print(f"[{summary.month} 월별 요약]")
    if summary.count == 0:
        print("거래 데이터가 없습니다.")
    print(f"총 수입: {summary.income:,}원")
    print(f"총 지출: {summary.expense:,}원")
    print(f"잔액: {summary.balance:,}원")
    print(f"카테고리별 지출 TOP {args.top}:")
    if summary.category_expenses:
        for rank, (category, amount) in enumerate(summary.category_expenses, start=1):
            print(f"  {rank}. {category}: {amount:,}원")
    else:
        print("  지출 데이터가 없습니다.")
    if summary.budget is not None:
        print(f"예산: {summary.budget:,}원")
        print(f"예산 사용률: {summary.budget_usage:.1f}%")
        if summary.is_over_budget:
            print("경고: 월 예산을 초과했습니다!")
    return 0


def _handle_budget_set(args: argparse.Namespace, service: BudgetService) -> int:
    amount = service.set_budget(args.month, args.amount)
    print(f"{args.month} 예산이 {amount:,}원으로 저장되었습니다.")
    return 0


def _handle_budget_get(args: argparse.Namespace, service: BudgetService) -> int:
    amount = service.get_budget(args.month)
    if amount is None:
        print(f"{args.month}에 설정된 예산이 없습니다.")
    else:
        print(f"{args.month} 예산: {amount:,}원")
    return 0


def _handle_budget_list(args: argparse.Namespace, service: BudgetService) -> int:
    count = 0
    for month, amount in service.list_budgets():
        print(f"{month}: {amount:,}원")
        count += 1
    if count == 0:
        print("설정된 예산이 없습니다.")
    return 0


def _handle_category_add(args: argparse.Namespace, service: BudgetService) -> int:
    name = (
        args.name
        if args.name is not None
        else _prompt("카테고리명: ", validate_category_name)
    )
    category = service.add_category(name)
    print(f"카테고리가 추가되었습니다: {category}")
    return 0


def _handle_category_list(args: argparse.Namespace, service: BudgetService) -> int:
    for category in service.list_categories():
        print(category)
    return 0


def _handle_category_remove(args: argparse.Namespace, service: BudgetService) -> int:
    name = (
        args.name
        if args.name is not None
        else _prompt("삭제할 카테고리명: ", validate_category_name)
    )
    service.remove_category(name)
    print(f"카테고리가 삭제되었습니다: {name}")
    return 0


def _handle_update(args: argparse.Namespace, service: BudgetService) -> int:
    update_fields = (
        args.date,
        args.type,
        args.category,
        args.amount,
        args.memo,
        args.tags,
    )
    if all(value is None for value in update_fields):
        raise ValidationError(
            "수정할 옵션이 없습니다.",
            "--date, --type, --category, --amount, --memo, --tags 중 하나를 지정해 주세요.",
        )
    transaction = service.update_transaction(
        args.id,
        date=args.date,
        type=args.type,
        category=args.category,
        amount=args.amount,
        memo=args.memo,
        tags=args.tags,
    )
    print(f"거래가 수정되었습니다. id={transaction.id}")
    return 0


def _handle_delete(args: argparse.Namespace, service: BudgetService) -> int:
    service.delete_transaction(args.id)
    print(f"거래가 삭제되었습니다. id={args.id}")
    return 0


def _handle_import(args: argparse.Namespace, service: BudgetService) -> int:
    count = service.import_csv(args.source)
    print(f"가져오기가 완료되었습니다. {count}건")
    return 0


def _handle_export(args: argparse.Namespace, service: BudgetService) -> int:
    count = service.export_csv(
        args.out,
        month=args.month,
        from_date=args.from_date,
        to_date=args.to_date,
    )
    print(f"내보내기가 완료되었습니다. {count}건: {Path(args.out)}")
    return 0


@cli_error_boundary
def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(_move_data_dir_to_front(arguments))
    service = BudgetService(args.data_dir)
    return args.handler(args, service)


def entrypoint() -> None:
    raise SystemExit(main())
