# AWT Cloud Backend

Supabase Auth + PostgreSQL 기반 클라우드 백엔드.

## 빠른 시작 (로컬 개발)

```bash
cd cloud
pip install -r requirements.txt

# 로컬 개발은 SQLite + JWT secret만 있으면 동작
export AWT_SUPABASE_JWT_SECRET="your-dev-secret"

uvicorn app.main:app --reload
# http://127.0.0.1:8000/docs ← Swagger UI
```

---

## Supabase 프로젝트 셋업 가이드

### Step 1: Supabase 회원가입

1. https://supabase.com 접속
2. **Start your project** 클릭
3. GitHub 계정으로 로그인 (또는 이메일 회원가입)

### Step 2: 새 프로젝트 생성

1. 대시보드에서 **New Project** 클릭
2. 설정 입력:
   - **Organization**: 기본 org 선택 (또는 새로 생성)
   - **Project name**: `awt-cloud` (자유)
   - **Database Password**: 강력한 비밀번호 입력 → **반드시 따로 저장**
   - **Region**: `Northeast Asia (Seoul)` 선택 — `ap-northeast-2`
   - **Plan**: Free (무료, 2개 프로젝트까지)
3. **Create new project** 클릭 → 1~2분 대기

### Step 3: API 키 확인

프로젝트 생성 완료 후:

1. 왼쪽 메뉴 **Project Settings** (톱니바퀴) → **API**
2. 다음 3가지 값을 복사:

| 항목 | 위치 | 환경변수 |
|------|------|---------|
| **Project URL** | `https://xxxx.supabase.co` | `AWT_SUPABASE_URL` |
| **anon public** | `Project API keys` 섹션 | `AWT_SUPABASE_ANON_KEY` |
| **JWT Secret** | 페이지 하단 `JWT Settings` 섹션 | `AWT_SUPABASE_JWT_SECRET` |

> **주의**: `service_role` 키는 백엔드에서도 사용하지 않습니다. 절대 프론트엔드에 노출하지 마세요.

### Step 4: Authentication 설정

1. 왼쪽 메뉴 **Authentication** → **Providers**
2. **Email** 항목이 기본 활성화 상태인지 확인
3. (선택) **Confirm email** 토글:
   - 개발 중: **OFF** → 이메일 확인 없이 바로 가입
   - 프로덕션: **ON** → 이메일 확인 필수

### Step 5: Database 연결 정보 (프로덕션용)

1. **Project Settings** → **Database**
2. **Connection string** 섹션에서 **URI** 탭 선택
3. 형식: `postgresql://postgres.[ref]:[password]@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres`
4. 이 값을 `AWT_DATABASE_URL`에 설정 (asyncpg 사용 시 `postgresql+asyncpg://...`로 변경)

> **로컬 개발에서는 이 단계를 건너뛰세요.** 기본값 SQLite가 사용됩니다.

### Step 6: 환경변수 설정

`cloud/.env` 파일 생성:

```env
# Supabase
AWT_SUPABASE_URL=https://xxxxxxxxxxxx.supabase.co
AWT_SUPABASE_ANON_KEY=eyJhbGciOiJI...
AWT_SUPABASE_JWT_SECRET=your-jwt-secret-from-step-3

# Database (프로덕션에서만 — 로컬은 기본 SQLite 사용)
# AWT_DATABASE_URL=postgresql+asyncpg://postgres.[ref]:[password]@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres
```

> `.env` 파일은 `.gitignore`에 포함되어 있으므로 커밋되지 않습니다.

---

## 인증 흐름

### 회원가입 (Sign Up)

```bash
curl -X POST "https://YOUR_PROJECT.supabase.co/auth/v1/signup" \
  -H "apikey: YOUR_ANON_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "securepassword123"}'
```

응답:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 3600,
  "refresh_token": "xxxxx",
  "user": {
    "id": "uuid-here",
    "email": "user@example.com"
  }
}
```

### 로그인 (Sign In)

```bash
curl -X POST "https://YOUR_PROJECT.supabase.co/auth/v1/token?grant_type=password" \
  -H "apikey: YOUR_ANON_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "securepassword123"}'
```

응답에서 `access_token`을 복사합니다.

### API 호출

```bash
# 테스트 생성
curl -X POST "http://localhost:8000/api/tests" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"target_url": "https://example.com"}'

# 테스트 목록 조회
curl "http://localhost:8000/api/tests" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

---

## JWT 검증 방식

Supabase Auth는 프로젝트의 **JWT Secret** (HS256)으로 서명된 표준 JWT를 발급합니다.

```
Header:  {"alg": "HS256", "typ": "JWT"}
Payload: {"sub": "user-uuid", "email": "...", "role": "authenticated", "aud": "authenticated", ...}
```

백엔드에서는 `PyJWT` 라이브러리로 직접 검증합니다:

```python
import jwt
payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"], audience="authenticated")
user_id = payload["sub"]
```

`firebase-admin` 같은 무거운 SDK 없이 순수 JWT 검증만 수행합니다.

---

## API 엔드포인트

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | - | 헬스 체크 |
| POST | `/api/tests` | Bearer | 테스트 생성 (rate limited) |
| GET | `/api/tests` | Bearer | 내 테스트 목록 (페이징) |
| GET | `/api/tests/{id}` | Bearer | 테스트 상세 조회 |

### Rate Limiting

| Tier | 월간 POST 한도 |
|------|---------------|
| Free | 5회 |
| Pro | 무제한 |

초과 시 `429 Too Many Requests` + 헤더:
```
X-RateLimit-Limit: 5
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 2026-03-01T00:00:00+00:00
```

---

## 테스트 실행

```bash
cd cloud
pip install -r requirements.txt
pytest tests/ -v
```

Firebase 의존성 없이 PyJWT만으로 동작합니다. 테스트는 SQLite in-memory + JWT mock을 사용합니다.

---

## 환경변수 목록

| 변수 | 필수 | 기본값 | 설명 |
|------|------|--------|------|
| `AWT_SUPABASE_URL` | prod | - | Supabase 프로젝트 URL |
| `AWT_SUPABASE_ANON_KEY` | prod | - | Supabase anon public key |
| `AWT_SUPABASE_JWT_SECRET` | **yes** | - | JWT 서명 검증 시크릿 |
| `AWT_DATABASE_URL` | no | `sqlite+aiosqlite:///./awt_cloud.db` | DB 연결 문자열 |
| `AWT_RATE_LIMIT_FREE` | no | `5` | Free 월간 한도 |
| `AWT_RATE_LIMIT_PRO` | no | `-1` | Pro 월간 한도 (-1=무제한) |
| `AWT_DEBUG` | no | `false` | SQLAlchemy echo 등 |

---

## 디렉토리 구조

```
cloud/
├── app/
│   ├── main.py          # FastAPI 앱 엔트리포인트
│   ├── config.py         # pydantic-settings 환경변수
│   ├── database.py       # SQLAlchemy async 엔진
│   ├── models.py         # ORM 모델 (Test, User)
│   ├── schemas.py        # Pydantic 요청/응답 스키마
│   ├── auth.py           # Supabase JWT 검증 + get_current_user
│   ├── middleware.py      # Rate limiting
│   └── routers/
│       └── tests.py      # /api/tests CRUD
├── tests/
│   ├── conftest.py       # Fixtures (in-memory DB, mock user)
│   ├── test_health.py
│   ├── test_tests_api.py
│   ├── test_rate_limit.py
│   └── test_auth.py      # JWT 검증 테스트
├── requirements.txt
└── README.md
```
