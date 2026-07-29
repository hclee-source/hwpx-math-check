# hwpx-math-check

hwpx 수학 문항 은행(2열 표 구조)을 **로컬 파이썬만으로** 자동 검수하는 파이프라인.
렌더링·vision API 없이 XML에서 텍스트·수식·구조를 직접 뽑아 검사한다 (토큰 0).

```
hwpx (표 기반 문항 은행)
  └─ scripts/hwpx_items.py       표 파싱 → items.json
       ├─ (exam-item-reviewer)    13종 결정론 정합성 검사 (별도 스킬)
       └─ scripts/math_review.py  수학 전용 통합 러너 (--math 모드 진입점)
            ├─ eq_answer_check.py   정답 ↔ 해설 SymPy 동치 검산
            ├─ twin_check.py        평가↔일반 쌍둥이문항 교차 검수
            └─ hml2sympy.py         한글 수식 스크립트 → SymPy 트랜스파일러
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

# 트랜스파일러 자가 테스트
python scripts/hml2sympy.py --selftest
```

요구사항: Python 3.9+, `pip install lxml sympy`

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
