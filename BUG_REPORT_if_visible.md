# BUG REPORT: if_visible 블록 감지가 반대로 동작

## ✅ 종결 (2026-10-14, 이대리)

**보고된 두 항목 모두 닫혔습니다.** 아래 원문은 기록으로 남겨 둡니다.

1. **`if_visible` 양갈래** — `0516fd9`(2026-03-24)이 원인을 고쳤으나 재현 시험 없이 올라갔기 때문에, 고쳤다는 주장만 남고 보고는 열린 상태였습니다. 이제 `tests/integration/test_if_visible_branches.py`에 실제 Chromium 통합 시험 **24건**이 있고, 팝업이 떠 있는 쪽·아무것도 없는 쪽·`display: none`으로 숨은 쪽이 모두 올바르게 갈라집니다. 위 표의 "도움말" 행이 그 `display: none` 경로입니다.

2. **같은 보고가 두 번째 CSS 경로로 살아 있었습니다** — 그 시험을 쓰다가 찾았습니다. `height: 0; overflow: hidden`인 부모 안의 자식은 자기 상자를 그대로 가지므로 Playwright `is_visible()`이 **참**을 돌려줍니다. 접히는 아코디언이나 드롭다운은 보통 이렇게 만들기 때문에 `display: none`보다 오히려 흔한 모양입니다. 2026-10-14에 `aat.engine.dom_search.is_clipped_by_ancestor`로 닫았고, 가시성을 판정하는 **네 자리 전부**(선택자·영역·글자·상자 없는 글자)에 적용했습니다.

3. **`vars` + `{{env.X}}` 치환** — AAT-093(2026-03-26)에서 구현되었고, 오늘 실측으로 확인했습니다. `vars: {title: "{{env.POST_TITLE}}"}`를 단계에서 `{{title}}`로 쓰면 환경변수 값으로 치환됩니다.

**남아 있는 한 가지**: 같은 `height: 0` 구멍이 `text_visible` 단정에는 그대로 있습니다(보이지 않는 글자를 보인다고 읽습니다). 고치는 방향이 「지금 통과하는 단정을 실패로 바꾸는」 쪽이어서 대표님 판단 사항으로 올려 두었고, 그동안 `tests/integration/test_text_assertions.py`에 `xfail(strict=True)`로 못 박아 두었습니다.

---

## 보고자: 박대리 (AutoPost)
## 날짜: 2026-03-24
## 심각도: Critical (→ 종결)

## 현상

`if_visible` 블록의 OCR 텍스트 감지가 **정반대로 동작**합니다.

| 팝업 | 실제 상태 | if_visible 판단 | 결과 |
|------|---------|---------------|------|
| "작성 중인 글이 있습니다" | **있음** (화면에 보임) | **없다고 판단** → then 블록 스킵 | 팝업 안 닫힘 |
| "도움말" | **없음** (화면에 안 보임) | **있다고 판단** → then 블록 실행 | 엉뚱한 좌표 클릭 |

## 재현 시나리오

```yaml
# 이 블록이 실행되어야 하는데 스킵됨 (팝업이 떠 있는 상태)
- step: 4
  action: if_visible
  target:
    text: "작성 중인 글이 있습니다"
  then:
    - action: click_at
      value: "567,436"
      description: "취소 버튼 클릭"
    - action: wait
      value: "2000"
  description: "작성중 글 팝업 처리"

# 이 블록이 스킵되어야 하는데 실행됨 (도움말 패널 없는 상태)
- step: 5
  action: if_visible
  target:
    text: "도움말"
  then:
    - action: click_at
      value: "1221,40"
      description: "도움말 X 버튼 클릭"
    - action: wait
      value: "1000"
  description: "도움말 패널 닫기"
```

## 스크린샷

- `bug_if_visible_popup_exists.png` — "작성 중인 글이 있습니다" 팝업이 **보이는** 상태인데 if_visible이 **못 찾음**
- `bug_if_visible_final.png` — 결국 팝업이 안 닫혀서 제목/본문 입력 실패한 최종 상태

경로: `.aat/screenshots/`

## 추가 이슈: 변수 치환

`vars`에서 `{{env.POST_TITLE}}`가 여전히 치환되지 않고 `{{title}}`로 입력됨.
환경변수에 값이 있는 것은 확인됨 (Python launcher에서 출력):
```
Title: 학원 원장님, 월 3만원으로 학원 관리와 AI 마케팅...
Content: 1055 chars
```

## 기대 동작

1. `if_visible`: 화면에 텍스트가 **있으면** then 블록 실행, **없으면** 스킵
2. `vars` + `{{env.X}}`: 환경변수 값으로 정상 치환
