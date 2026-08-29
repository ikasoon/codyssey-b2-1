"""CLI의 공통 예외 처리를 분리하는 데코레이터."""

from __future__ import annotations

import csv
from functools import wraps
import sys
from typing import Callable, ParamSpec

from budget_app.errors import BudgetAppError


P = ParamSpec("P")


def cli_error_boundary(function: Callable[P, int]) -> Callable[P, int]:
    """예상 가능한 오류를 원인과 해결 힌트로 바꾸고 종료 코드를 반환한다."""

    @wraps(function)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> int:
        try:
            return function(*args, **kwargs)
        except BudgetAppError as exc:
            print(f"오류: {exc}", file=sys.stderr)
            print(f"해결: {exc.hint}", file=sys.stderr)
            return 2
        except (OSError, csv.Error, UnicodeError) as exc:
            print(f"오류: 파일을 처리하지 못했습니다: {exc}", file=sys.stderr)
            print(
                "해결: 파일 경로, 권한, UTF-8 인코딩, CSV 형식을 확인해 주세요.",
                file=sys.stderr,
            )
            return 3
        except EOFError:
            print("오류: 입력이 중간에 종료되었습니다.", file=sys.stderr)
            print("해결: 필요한 값을 모두 입력해 주세요.", file=sys.stderr)
            return 2
        except KeyboardInterrupt:
            print("\n입력이 취소되었습니다.", file=sys.stderr)
            return 130
        except Exception as exc:
            print(f"오류: 예상하지 못한 문제가 발생했습니다: {exc}", file=sys.stderr)
            print(
                "해결: 입력과 저장 파일을 확인한 뒤 다시 시도해 주세요.",
                file=sys.stderr,
            )
            return 1

    return wrapper
