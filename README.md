# hwpx-math-check

hwpx 수학 문항 은행(2열 표 구조)을 **로컬 파이썬만으로** 자동 검수하는 파이프라인.
렌더링·vision API 없이 XML에서 텍스트·수식·구조를 직접 뽑아 검사한다 (토큰 0).

```
hwpx (표 기반 문항 은행)
  └─ scripts/hwpx_items.py       표 파싱 → items.json
       ├─ (exam-item-reviewer)    13종 결정론 정합성 검사 (별도 스킬)
       ├─ scripts/math_review.py  수학 전용 통합 러너 (--math 모드 진입점)
       │    ├─ eq_answer_check.py   정답 ↔ 해설 SymPy 동치 검산
       │    ├─ extra_checks.py      오탈자·출처·표기·중복·통계·메타 부가 검사
       │    ├─ twin_check.py        평가↔일반 쌍둥이문항 교차 검수
       │    ├─ hml2sympy.py         한글 수식 스크립트 → SymPy 트랜스파일러
       │    └─ ai_review.py       [선택] Claude API 심층 검수 (--ai, 토큰 비용)
       └─ scripts/hwpx_fix.py     검사 결과를 hwpx에 되돌려 쓰는 교정기
```

## 상태

| 단계 | 상태 |
|---|---|
| hwpx → items.json 파싱 | ✅ 211문항 무손실 검증 |
| 정합성 검사 (번호·중복·정답 분포) | ✅ exam-item-reviewer 재사용 |
| 한글 수식 → SymPy 변환 | ✅ 수식 5,503개 전수 — **파싱 성공 97.9%, 실패 0** (나머지 2.1%는 비수식 라벨) |
| 정답↔해설 SymPy 동치 검산 | ✅ `simplify(a-b)==0` — 211문항 중 **정답 유일 증명 139, 일치 56**, 오탐 0 |
| 범위형 결론 판정 (`0<k<2`) | ✅ 모든 제약(부등식·≠) 교집합 통과 값만 인정 |
| ± 결론 판정 | ✅ `+-`를 부호 심볼로 보존, 양쪽 부호 대입 판정 |
| 쌍둥이문항 교차 검수 | ✅ 실측 불변식 5종 (메타 3필드·id 몸통·참조 무결성) |
| 통합 러너 (`--math` 모드) | ✅ `math_review.py` — exam-item-reviewer에 그대로 이식 가능 |
| **hwpx 자동 교정** | ✅ `hwpx_fix.py` — 확정 가능한 결함만 되돌려 쓰고, 판단 필요분은 보류 |
| **AI 심층 검수 (선택)** | ✅ `ai_review.py` — 해설 단계 오류·조건 불충분 등 규칙 사각지대 |

## 사용법

**가장 쉬운 방법 — 웹에서 바로:**

> **https://hclee-source.github.io/hwpx-math-check/**

브라우저에 hwpx 파일을 끌어다 놓으면 끝. 설치가 전혀 필요 없다.
모든 처리(sympy 검산 포함)는 Pyodide(WASM)로 **브라우저 안에서만** 실행되며
파일이 서버로 전송되지 않는다. 최초 접속 시 엔진 로딩에 10~20초 걸린다.

**Windows 로컬 실행 세 가지** (전부 원본 옆에 `*_검수보고서.html`을 만들어 브라우저로 연다):

1. **검수도우미.pyw 더블클릭** — 창에서 파일 선택 → [검수 시작]. 가장 쉬움
2. **우클릭 → 보내기 → 문항검수** — 탐색기에서 hwpx를 우클릭으로 바로.
   등록: `SendTo` 폴더(`shell:sendto`)에 `검수실행.bat` 바로가기를 넣으면 된다
3. **검수실행.bat에 드래그&드롭** — hwpx 1~2개를 끌어다 놓기 (CP949 인코딩)

파일 2개를 주면 쌍둥이 교차 검수까지 한다. 순서는 무관 — 쌍둥이문항 필드가
채워진 쪽을 자동으로 평가측으로 인식한다.

명령줄:

```bash
# 1) hwpx → items.json
python scripts/hwpx_items.py 문항은행.hwpx --out items.json

# 2) 수식 전수 파싱 측정 (실패 패턴 보고)
python scripts/hml2sympy.py items.json --dump failures.json

# 3) 수학 검수 통합 실행 (검산 + 쌍둥이 교차)
python scripts/math_review.py 평가_items.json 일반_items.json --out report.json --html 보고서.html

# 개별 실행
python scripts/eq_answer_check.py items.json --out findings.json
python scripts/twin_check.py 평가_items.json 일반_items.json

# 4) 검사 결과를 hwpx에 되돌려 쓰기 (자동 교정)
python scripts/hwpx_fix.py 문항은행.hwpx --dry-run          # 무엇이 바뀌는지만 본다
python scripts/hwpx_fix.py 문항은행.hwpx --log 교정내역.json  # 원본 옆에 *_교정.hwpx

# 5) [선택] AI 심층 검수 — 규칙이 못 잡는 것만. 토큰 비용이 든다
python scripts/ai_review.py items.json --estimate           # 비용만 먼저 계산
python scripts/ai_review.py items.json --limit 5 --sync     # 5문항 시범
python scripts/math_review.py items.json --ai --html 보고서.html   # 통합 실행

# 트랜스파일러 자가 테스트
python scripts/hml2sympy.py --selftest
```

요구사항: Python 3.9+, `pip install lxml sympy` (AI 검수만 `pip install anthropic`)

새 PC 셋업은 세 줄이면 된다:

```bash
git clone https://github.com/hclee-source/hwpx-math-check
pip install lxml sympy
# 이후 검수실행.bat 에 hwpx 드래그&드롭
```

## hml2sympy가 처리하는 문법

`{}over{}`(분수) · `sqrt{}`/`root n of x` · `^{}`/`_{}` · `TIMES`/`CDOT` ·
`bar{PF}`(선분→단일 심볼) · `prime` · `LEFT|…RIGHT|`(절댓값) · `LEFT(`/`RIGHT)` ·
`GEQ`/`LEQ`/`!=` · `DEG`/`ANGLE`/`TRIANGLE` · `+-`(± → 플래그) · `CDOTS`(⋯ → 플래그) ·
`a:b`(비율→나눗셈) · `F(4,0)`(좌표→튜플) · `&`/`#`(여러 줄 정렬 수식 → 줄 분리) ·
백틱/`~`(공백) · `it`/`rm`(서체 지정자) · 한글 텍스트 혼입(걷어내고 수식 조각만)

변환 결과에 `flags`가 붙는다: `pm`(± → 부호 심볼 `PM_`, 검산에서 양쪽 부호 대입),
`cdots`(값 계산 불가), `text`(텍스트 제거됨), `trailing_op`(`$k<$` 고아 연산자 — 조판 결함 신호).

## 자동 교정 (hwpx_fix.py)

**고칠 대상을 새로 찾지 않는다.** `extra_checks`/`eq_answer_check`가 낸 결함 목록을
그대로 입력으로 받아 그 문항·그 유형에만 규칙을 적용한다. 검사기와 교정기가 어긋날 수 없고,
교정본을 재검사하면 해당 항목이 0건으로 수렴한다.

| 자동 교정 | 사람 판단으로 보류 |
|---|---|
| 오탈자 (수선이 발→수선의 발, 개다→개이다, 추죽→주축, 커야한다) | 완전 중복 문항 — 어느 쪽을 변형할지 |
| 출처 표기 혼용 (쏀→쎈) | 편집 메모 `(그림 수정)` — 그림이 실제 반영됐는지 |
| 쪼개진 수식 병합 (`$k<$$-3$` → `$k<-3$`) | 유사 문항 — 변형이 충분한지 |
| 표기 정규화 (첨자 쉼표·중괄호 공백·민형식 첨자·`root`→`sqrt` 등) | 정답↔해설 불일치 후보 — 수학적 재검토 |

원본은 절대 덮어쓰지 않는다(`*_교정.hwpx`). 변경 하나하나를 `(문항id, 필드, 유형, 전/후)`로
`--log`에 남기므로 편집자가 전수 검증할 수 있다. zip 항목 순서·압축 방식과 `mimetype` 선두
무압축 조건을 유지해 한글이 그대로 읽는다.

> **수식을 병합하면 한글의 레이아웃 캐시(`lineseg`)가 낡는다.**
> 교정 후 **한글에서 열고 저장**한 뒤 재검사해야 쪽 번호가 정확하다.

## AI 심층 검수 (ai_review.py) — 선택

결정론 검사의 사각지대가 하나 있다. `eq_answer_check`는 `선택지[정답] ↔ 해설 결론`의
동치만 본다. **해설 자체의 계산이 틀렸으면 정답과 해설은 여전히 서로 일치하므로
검사를 통과한다.** 그 구멍을 Claude API로 메운다.

| AI가 보는 것 | AI가 보지 않는 것 (규칙이 이미 전수 검사) |
|---|---|
| `AI_ANSWER_WRONG` 직접 푼 결과 ≠ 인쇄된 정답 | 수식 조판·괄호 짝·쪼개진 수식 |
| `AI_EXPL_ERROR` 해설 중간 단계 오류·비약 | 표기 스타일·출처·오탈자 |
| `AI_ITEM_AMBIGUOUS` 조건 불충분·중의적 | 문항 중복·정답 분포 편향 |
| `AI_WORDING` 용어 오류·오해를 부르는 문장 | 정답↔해설 결론 동치 |

**오탐 방어가 설계의 중심이다.**

- 해설을 먼저 읽지 말고 **직접 풀고 나서** 대조하도록 지시한다 — 해설을 따라 읽으면
  틀린 단계를 그대로 승인한다
- 등급(sev)을 **모델이 정하지 않는다.** 모델은 확신도(높음/보통/낮음)만 내고,
  코드가 환산한다. **확신도 '낮음'은 결함으로 올리지 않고 버린다**
- 표현 지적(`AI_WORDING`)은 확신도가 높아도 `low`를 넘지 않는다
- 그림이 필요한 문항은 텍스트로 판단 불가 → `판단불가`로 두고 추측하지 않는다
- 보고서 카드에 **AI가 푼 결과·근거·확신도를 함께** 띄운다. 근거 없는 지적은
  편집자가 검증할 수 없으므로 결함이 아니다

**비용 설계.** 문항 1개 = 요청 1개. 기본이 **Batch API(표준가의 50%)**이고,
검수 기준 프롬프트(약 1,300자)는 문항 전체에 걸쳐 **프롬프트 캐싱**으로 재사용된다.
판정은 **structured outputs**로 스키마를 고정해 파싱 실패가 없다.
`--estimate`로 **API를 호출하지 않고** 입력 토큰과 비용 범위를 먼저 볼 수 있다.

`ANTHROPIC_API_KEY` 환경변수(또는 `ant auth login`)가 필요하다.
**웹 검수 페이지에는 넣지 않았다** — 브라우저에 API 키를 두면 유출된다.
AI 검수는 로컬 전용이다.

> section0.xml을 컨텍스트에 올리지 않는 원칙은 그대로다. 문항별 텍스트
> (본문·보기·정답·해설)만 보낸다 — 한 요청에 다른 문항이 섞이지도 않는다.

## exam-item-reviewer 통합 (--math 모드)

`scripts/` 4개 파일(hml2sympy, eq_answer_check, twin_check, math_review)을
스킬의 `scripts/`에 복사하면 된다. `check_items.py`와 같은 items.json 스키마를 쓰고,
finding 스키마(code/sev/no/loc/want/tail)도 동일하게 맞춰져 있다.
`--math` 모드 = `math_review.py` 실행 후 두 결과를 합쳐 보고.

## 데이터

`data/`의 문항 JSON은 출판사 자산이라 저장소에 포함하지 않는다 (.gitignore).

## 검수 원칙

- 오탐이 세 번 나면 아무도 안 쓴다 — 애매하면 등급을 내리고 "확인 필요"로 표시
- 인쇄된 정답을 뒤집는 판정은 단정하지 않는다 — 근거를 붙여 사람에게 넘긴다
- 5MB짜리 section0.xml을 LLM 컨텍스트에 올리지 않는다 — 스크립트가 파싱하고 요약만

설계 배경과 함정 목록은 [docs/설계노트.md](docs/설계노트.md) 참고.
