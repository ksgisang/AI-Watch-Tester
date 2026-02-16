# AAT Demo 기획서

테스트 URL: {{url}}

## 페이지 목록
- / (Home): "Welcome to AAT Demo", Register/Login 버튼
- /register: Name, Email, Password 입력 → Register 버튼 → 성공 시 "Registration successful"
- /login: Email, Password 입력 → Login 버튼 → 성공 시 /main 이동
- /main: "Welcome, {이름}!" 표시, Home/Logout 버튼
- /logout: 세션 종료 → / 이동, "logged out" 메시지

## 테스트 케이스
1. 회원가입: /register → Name "Test User", Email "test@example.com", Password "password123" → Register 클릭 → "Registration successful" 확인
2. 로그인: /login → Email "test@example.com", Password "password123" → Login 클릭 → /main 이동 확인
3. 로그아웃: 로그인 후 Logout 클릭 → / 이동 확인
