# AAT Demo Test Site

AAT 테스트용 데모 Flask 웹 애플리케이션.

> **WARNING:** Demo only. 프로덕션 사용 금지.
> 하드코딩된 secret key, in-memory 저장소, 입력 검증 없음.

## 실행

```bash
pip install flask
python test-site/app.py
# http://localhost:5001
```

## 페이지 구성

| 경로 | 기능 |
|------|------|
| `/` | 메인 (로그인/회원가입 링크) |
| `/register` | 회원가입 |
| `/login` | 로그인 |
| `/main` | 로그인 후 메인 |
| `/logout` | 로그아웃 |

## 시나리오 디렉토리 구조

이 프로젝트에는 시나리오가 3곳에 있으며 각각 용도가 다릅니다:

| 경로 | 용도 | 특징 |
|------|------|------|
| `test-site/scenarios/` | 이 데모 앱 전용 | 간결한 6스텝, `find_and_type` 직접 사용 |
| `scenarios/` | AAT 실행용 (작업 디렉토리) | 확장된 9스텝, `find_and_click` + `find_and_type` 분리 |
| `scenarios/examples/` | AAT 예제 템플릿 | `expected_result`, `screenshot_after` 등 고급 필드 포함 |
