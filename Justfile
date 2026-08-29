default:
    @just --list

# uv로 가상환경과 잠금 파일을 준비합니다.
setup:
    uv sync

# 모든 자동화 테스트를 실행합니다.
test:
    PYTHONDONTWRITEBYTECODE=1 uv run pytest -v

# 예: just run list --limit 10
run *args:
    uv run python -m budget_app {{args}}
