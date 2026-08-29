"""사용자에게 설명할 수 있는 애플리케이션 오류."""


class BudgetAppError(Exception):
    """스택 트레이스 없이 사용자에게 보여 줄 수 있는 기본 오류."""

    def __init__(self, message: str, hint: str = "입력값을 확인해 주세요.") -> None:
        super().__init__(message)
        self.hint = hint


class ValidationError(BudgetAppError):
    """사용자 입력 또는 가져온 데이터가 유효하지 않을 때 발생한다."""


class NotFoundError(BudgetAppError):
    """요청한 데이터가 존재하지 않을 때 발생한다."""


class DataFormatError(BudgetAppError):
    """영구 저장 파일의 형식이 올바르지 않을 때 발생한다."""

