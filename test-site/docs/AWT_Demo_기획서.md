# AAT Demo 웹 애플리케이션 기획서

## 개요
Flask 기반 웹 애플리케이션으로, 회원가입/로그인/로그아웃 기능을 제공하는 데모 사이트입니다.
테스트 URL: {{url}}

## 페이지 구성

### 1. Home (/)
- "Welcome to AAT Demo" 제목 표시
- "Register" 버튼 → /register 이동
- "Login" 버튼 → /login 이동
- 네비게이션: Home, Register, Login 링크

### 2. 회원가입 (/register)
- "Create Account" 제목
- 입력 필드:
  - Name (text, 필수)
  - Email (email, 필수)
  - Password (password, 필수)
- "Register" 버튼 (초록색) → 가입 처리
- 가입 성공 시: "Registration successful" 메시지, /login으로 이동
- 하단에 "Already have an account? Login here" 링크

### 3. 로그인 (/login)
- "Login" 제목
- 입력 필드:
  - Email (email, 필수)
  - Password (password, 필수)
- "Login" 버튼 (파란색) → 로그인 처리
- 로그인 성공 시: /main으로 이동
- 로그인 실패 시: 에러 메시지 표시
- 하단에 "Don't have an account? Register here" 링크

### 4. Main (/main) - 로그인 후
- "Welcome, {사용자이름}!" 제목
- "Home" 버튼 → / 이동
- "Logout" 버튼 (빨간색) → 로그아웃 처리
- 네비게이션: Home, Main, Logout 링크

### 5. 로그아웃 (/logout)
- 세션 종료 후 / 로 리다이렉트
- "You have been logged out" 메시지 표시

## 테스트 시나리오 요구사항

### TC-001: 회원가입
1. /register 페이지로 이동
2. Name에 "Test User" 입력
3. Email에 "test@example.com" 입력
4. Password에 "password123" 입력
5. Register 버튼 클릭
6. "Registration successful" 메시지 확인

### TC-002: 로그인
1. /login 페이지로 이동
2. Email에 "test@example.com" 입력
3. Password에 "password123" 입력
4. Login 버튼 클릭
5. /main 페이지로 이동 확인
6. "Welcome" 텍스트 확인

### TC-003: 메인 페이지 네비게이션
1. 로그인 상태에서 /main 페이지 확인
2. Home 버튼 클릭 → / 이동 확인
3. Main 링크 클릭 → /main 이동 확인

### TC-004: 로그아웃
1. 로그인 상태에서 Logout 클릭
2. / 페이지로 이동 확인
3. "logged out" 메시지 확인

### TC-005: 입력 검증
1. /register 페이지에서 빈 필드로 Register 클릭
2. 필수 입력 검증 확인
3. 잘못된 이메일 형식 입력 후 Register 클릭
4. 이메일 형식 검증 확인
