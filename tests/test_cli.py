from __future__ import annotations

from pathlib import Path

import pytest

from budget_app.cli import build_parser, main
from budget_app.services import BudgetService


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "ledger"


def run_cli(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    *arguments: str,
) -> tuple[int, str, str]:
    code = main([*arguments, "--data-dir", str(data_dir)])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_대화형으로_거래를_추가하고_장문_옵션으로_목록을_조회한다(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = iter(
        ("2026-08-27", "expense", "food", "15000", "저녁", "식사,친구")
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    code, output, errors = run_cli(data_dir, capsys, "add")
    assert code == 0
    assert "id=" in output
    assert errors == ""

    code, output, _ = run_cli(data_dir, capsys, "list", "--limit", "1")
    assert code == 0
    assert "2026-08-27" in output
    assert "총 1건" in output


def test_없는_거래를_삭제하면_스택트레이스_없이_오류_코드를_반환한다(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, errors = run_cli(
        data_dir, capsys, "delete", "--id", "does-not-exist"
    )
    assert code != 0
    assert "오류:" in errors
    assert "해결:" in errors
    assert "Traceback" not in errors


def test_내보내기는_검색_조건이_필수다(
    data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    destination = tmp_path / "out.csv"
    code, _, errors = run_cli(data_dir, capsys, "export", "--out", str(destination))
    assert code == 2
    assert "조건이 필요" in errors
    assert not destination.exists()

    code, _, errors = run_cli(
        data_dir,
        capsys,
        "export",
        "--out",
        str(destination),
        "--from",
        "2026-08-01",
    )
    assert code == 2
    assert "함께 지정" in errors
    assert "Traceback" not in errors
    assert not destination.exists()


def test_카테고리_추가와_삭제는_대화형_입력을_지원한다(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = iter(("", "medical"))
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    code, output, errors = run_cli(data_dir, capsys, "category", "add")
    assert code == 0
    assert "medical" in output
    assert "입력 오류:" in output
    assert errors == ""

    monkeypatch.setattr("builtins.input", lambda _prompt: "medical")
    code, output, errors = run_cli(data_dir, capsys, "category", "remove")
    assert code == 0
    assert "medical" in output
    assert errors == ""

    def fail_input(_prompt: str) -> str:
        raise AssertionError("명시된 --name은 입력을 호출하면 안 됩니다.")

    monkeypatch.setattr("builtins.input", fail_input)
    code, _, errors = run_cli(data_dir, capsys, "category", "add", "--name", "")
    assert code == 2
    assert "비워 둘 수 없습니다" in errors
    assert "Traceback" not in errors


def test_UTF_8이_아닌_CSV는_스택트레이스_없이_해결_힌트를_출력한다(
    data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "invalid-encoding.csv"
    source.write_bytes(b"\xff\xfe\xfd")

    code, _, errors = run_cli(data_dir, capsys, "import", "--from", str(source))
    assert code == 3
    assert "오류:" in errors
    assert "UTF-8" in errors
    assert "Traceback" not in errors
    assert list(BudgetService(data_dir).list_transactions(10)) == []


def test_등록되지_않은_카테고리_검색은_스택트레이스_없이_거부된다(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, errors = run_cli(
        data_dir, capsys, "search", "--category", "not-registered"
    )
    assert code == 2
    assert "등록되지 않은 카테고리" in errors
    assert "category list" in errors
    assert "Traceback" not in errors

    code, output, errors = run_cli(data_dir, capsys, "search", "--category", "food")
    assert code == 0
    assert "거래 데이터가 없습니다" in output
    assert errors == ""


def test_예상하지_못한_오류는_공통_예외_처리기가_감춘다(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_service(*args: object, **kwargs: object) -> BudgetService:
        raise RuntimeError("simulated unexpected failure")

    monkeypatch.setattr("budget_app.cli.BudgetService", fail_service)
    code, _, errors = run_cli(data_dir, capsys, "list")
    assert code == 1
    assert "simulated unexpected failure" in errors
    assert "해결:" in errors
    assert "Traceback" not in errors


def test_모든_CLI_옵션은_장문_형식으로_등록된다() -> None:
    parsers = [build_parser()]
    while parsers:
        parser = parsers.pop()
        for action in parser._actions:
            assert all(option.startswith("--") for option in action.option_strings)
            if isinstance(action.choices, dict):
                parsers.extend(action.choices.values())
