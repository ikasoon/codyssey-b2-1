# CSV 용돈 기입장

수입·지출을 터미널에서 관리하는 Python 애플리케이션입니다. 거래, 카테고리, 예산을 서로 다른 CSV 파일에 영구 저장합니다. 거래 조회와 검색은 `yield` 기반 제너레이터로 한 행씩 읽습니다.

## 준비와 실행

Python 3.10 이상을 지원합니다. 패키지·가상환경 관리는 `uv`, 반복 명령은 `Justfile`을 사용합니다.

```bash
just setup
just test
just check
just run --help
```

애플리케이션의 실행 의존성은 없으며, `pytest`는 개발 의존성 그룹에만 포함됩니다. `uv sync`는 테스트 도구까지 준비하고, 실행 환경만 필요할 때는 `uv sync --no-dev`를 사용합니다.

```bash
uv sync --no-dev  # 실행 환경만 설치
uv sync           # 개발·테스트 환경 설치
```

`just run` 뒤에는 애플리케이션 인자를 그대로 전달할 수 있습니다. 직접 실행하려면 다음과 같이 입력합니다.

```bash
uv run python -m budget_app --help
uv run python -m budget_app list --limit 20
```

모든 옵션은 리눅스 표준 장문 형식인 `--`로 통일했습니다. `--data-dir`은 어느 위치에 두어도 되며 기본값은 현재 디렉터리의 `./data`입니다.

```bash
uv run python -m budget_app --data-dir ./my-data list --limit 10
uv run python -m budget_app list --limit 10 --data-dir ./my-data
```

각 명령과 중첩 명령은 `--help`를 지원합니다.

## 주요 명령

거래 추가는 과제에서 요구한 대로 날짜, 타입, 카테고리, 금액, 메모, 태그를 차례로 묻는 대화형 방식입니다.

```bash
uv run python -m budget_app add
uv run python -m budget_app list --limit 10
uv run python -m budget_app search --from 2026-08-01 --to 2026-08-31 --type expense --category food --q 점심 --tag 식사
uv run python -m budget_app summary --month 2026-08 --top 3
```

`update`는 **옵션 방식**으로 고정했습니다. 지정하지 않은 필드는 기존 값을 유지하고, 빈 메모나 태그로 바꾸려면 `--memo ""`, `--tags ""`를 사용합니다.

```bash
uv run python -m budget_app update --id TRANSACTION_ID --amount 18000 --memo "저녁 식사"
uv run python -m budget_app delete --id TRANSACTION_ID
```

예산과 카테고리도 영구 저장됩니다. 기본 카테고리는 `food`, `transport`, `rent`, `salary`, `leisure`, `other`입니다. 거래에서 사용 중인 카테고리는 먼저 해당 거래를 수정해야 삭제할 수 있습니다.

```bash
uv run python -m budget_app budget set --month 2026-08 --amount 500000
uv run python -m budget_app budget get --month 2026-08
uv run python -m budget_app budget list
uv run python -m budget_app category add --name medical
uv run python -m budget_app category list
uv run python -m budget_app category remove --name medical
```

`category add`와 `category remove`에서 `--name`을 생략하면 카테고리명을 대화형으로 입력받습니다.

예산이 있는 달의 `summary`에는 사용률과 초과 경고가 함께 표시됩니다.

## 저장 위치와 형식

첫 실행 때 저장 폴더와 다음 세 파일을 자동 생성합니다. 필수 조건인 3개 이상의 영구 저장 파일을 충족합니다. 카테고리 파일에 헤더만 있고 데이터가 없을 때도 기본 카테고리를 다시 생성합니다.

| 파일 | CSV 헤더 | 용도 |
| --- | --- | --- |
| `data/transactions.csv` | `id,date,type,category,amount,memo,tags` | 거래 내역, 날짜 최신순 |
| `data/categories.csv` | `name` | 등록 카테고리 |
| `data/budgets.csv` | `month,amount` | 월별 예산 |

모든 파일은 UTF-8, 헤더 포함 CSV입니다. `tags` 값은 쉼표로 구분하며 `csv` 표준 인용 규칙에 따라 파일 안에서는 필요할 때 큰따옴표로 감싸집니다. 금액은 0보다 큰 정수입니다.

## 가져오기와 내보내기

교환용 CSV 스키마는 다음 순서로 고정합니다. `id`는 가져올 때 애플리케이션이 새로 생성하므로 포함하지 않습니다.

| column | required | 값 |
| --- | --- | --- |
| `date` | Y | `YYYY-MM-DD` |
| `type` | Y | `income` 또는 `expense` |
| `category` | Y | 이미 등록된 카테고리 |
| `amount` | Y | 양의 정수 |
| `memo` | N | 문자열 |
| `tags` | N | 쉼표로 구분한 문자열 |

```csv
date,type,category,amount,memo,tags
2026-08-27,expense,food,15000,저녁 식사,"식사,친구"
```

```bash
uv run python -m budget_app import --from ./incoming.csv
uv run python -m budget_app export --out ./august.csv --month 2026-08
uv run python -m budget_app export --out ./period.csv --from 2026-08-01 --to 2026-08-31
```

내보내기는 `--month`를 지정하거나 `--from`과 `--to`를 반드시 함께 지정해야 하며, 두 필터 방식은 섞어 쓸 수 없습니다. 앱이 사용하는 세 저장 CSV를 `--out`으로 지정하는 것도 데이터 보호를 위해 거부합니다.

## 구조

- `budget_app/models.py`: 거래 dataclass와 입력값 검증
- `budget_app/repositories.py`: 3개 CSV의 제너레이터 읽기와 전체 재작성
- `budget_app/services.py`: 검색, 요약, 예산, import/export 업무 규칙
- `budget_app/cli.py`: `argparse` 명령과 출력
- `budget_app/decorators.py`: 예외를 원인·해결 힌트·종료 코드로 바꾸는 공통 데코레이터
- `tests/`: fixture, parametrization, `monkeypatch`를 활용한 `pytest` 자동화 테스트

정상 실행은 종료 코드 `0`, 잘못된 입력이나 없는 데이터는 `2`, 파일 처리 오류는 `3`, 사용자 취소는 `130`을 반환합니다.
