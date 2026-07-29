#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hml2sympy.py — 한글(HWP) 수식 스크립트 → SymPy 트랜스파일러.

파이프라인 위치: hwpx_items.py 산출 items.json의 $...$ 수식을 SymPy 객체로 변환해,
eq_answer_check.py의 문자열 대조를 simplify 동치 판정으로 교체할 기반.

사용:
  python hml2sympy.py data/평가문항_items.json data/일반문항_items.json
      → 전수 파싱 성공률 측정 + 실패 상위 패턴 보고 (본문은 쏟지 않는다)
  python hml2sympy.py --selftest
      → 인수인계 문서의 PoC 케이스 검증

API:
  transpile(script) -> (statements, flags)
    statements: 줄 단위 [{'exprs': [sympy...], 'ops': ['=','<',...]}]
      ops[i]는 exprs[i]와 exprs[i+1] 사이 관계. 줄 첫 요소가 '&=' 연속행이면
      exprs 첫 항이 없을 수 있다(이어붙이기는 호출자 몫 — 마지막 줄이 결론).
    flags: {'pm','cdots','text'} 부분집합 — 검산 신뢰도 판단용.
       pm    ±를 +로 근사했다 → 동치 판정에 쓰지 말 것
       cdots ⋯가 들어 있다 → 값 계산 불가, 기호 대조만
       text  한글 등 텍스트를 걷어냈다 → 남은 조각만 파싱함
"""
import argparse, json, re, sys
from collections import Counter

import sympy
from sympy.parsing.sympy_parser import (
    parse_expr, standard_transformations, implicit_multiplication_application)

TRANSFORMS = standard_transformations + (implicit_multiplication_application,)

# 화이트리스트 네임스페이스. 여기 없는 이름은 전부 Symbol이 되고(O·E·I도 점 이름),
# 이름 뒤에 '('가 오면 sympy가 자동으로 미지 함수 적용으로 만든다 — F(4,0) 좌표가 그대로 산다.
GLOBALS = {n: getattr(sympy, n) for n in (
    'sqrt', 'Abs', 'sin', 'cos', 'tan', 'sec', 'csc', 'cot',
    'asin', 'acos', 'atan', 'log', 'exp', 'factorial', 'pi',
    'Symbol', 'Function', 'Integer', 'Float', 'Rational', 'Number', 'Tuple', 'oo')}
GLOBALS['ln'] = sympy.log

# 이 이름들 뒤의 (…)는 함수 호출로 보존한다 — 그 외 NAME(a,b)는 좌표 표기
FUNC_NAMES = {'sqrt', 'Abs', 'sin', 'cos', 'tan', 'sec', 'csc', 'cot',
              'asin', 'acos', 'atan', 'log', 'ln', 'exp'}

# 유니코드 → ASCII 스크립트 (조판 과정에서 섞여 들어올 수 있는 것들)
UNICODE_MAP = {
    '×': '*', '÷': '/', '−': '-', '±': '+-', '∓': '+-',
    '²': '**2', '³': '**3', '√': 'sqrt', '°': ' DEG ', '′': ' prime ',
    '≥': '>=', '≤': '<=', '≠': '!=', '⋯': ' CDOTS ', '…': ' CDOTS ',
    ' ': ' ', '　': ' ',
}

# 텍스트(비수식) 문자: 한글, 원문자, 괄호문자 등
TEXT_CHARS = re.compile(r'[가-힣ㄱ-ㅎㅏ-ㅣ㉠-㉭①-⑮⑴-⒂○□〔〕「」『』]+')

RELOP = ('!=', '<=', '>=', '=', '<', '>')


class TranspileError(Exception):
    def __init__(self, category, detail=''):
        self.category, self.detail = category, detail
        super().__init__(f'{category}: {detail}')


def _normalize(s, flags):
    for k, v in UNICODE_MAP.items():
        s = s.replace(k, v)
    s = s.replace('`', ' ').replace('~', ' ')          # 한글 수식의 공백들
    s = re.sub(r'\b(it|rm)\b', ' ', s)                 # 서체 지정자
    s = re.sub(r'\blambda\b', 'lamda', s)              # 파이썬 키워드 회피

    # LEFT/RIGHT — 구분자는 살리고 키워드만 제거. LEFT| ... RIGHT| 는 절댓값
    s = re.sub(r'LEFT\s*\|', '|', s)
    s = re.sub(r'RIGHT\s*\|', '|', s)
    s = re.sub(r'LEFT\s*([({\[])', '(', s)
    s = re.sub(r'RIGHT\s*([)}\]])', ')', s)
    s = re.sub(r'\b(LEFT|RIGHT)\b', ' ', s)
    if '|' in s:
        s = re.sub(r'\|([^|]+)\|', r'Abs(\1)', s)

    if re.search(r'\bCDOTS\b|\bLDOTS\b|\bDOTSLOW\b', s):
        flags.add('cdots')
        s = re.sub(r'\b(CDOTS|LDOTS|DOTSLOW)\b', ' cdots ', s)
    s = re.sub(r'\bDEG\b', ' ', s)
    s = re.sub(r'\b(ANGLE)\s*([A-Za-z0-9]+)', r' ang\2 ', s)
    s = re.sub(r'\b(TRIANGLE)\s*([A-Za-z0-9]+)', r' tri\2 ', s)
    s = re.sub(r'\bGEQ\b', '>=', s)
    s = re.sub(r'\bLEQ\b', '<=', s)
    s = re.sub(r'\bNEQ\b', '!=', s)

    if '+-' in s or '-+' in s:
        flags.add('pm')
        # ± → 부호 심볼 PM_. 검산 쪽에서 PM_=±1 둘 다 대입해 판정한다
        s = s.replace('+-', '+PM_*').replace('-+', '-PM_*')

    # bar{PF} → 단일 심볼 barPF (선분 길이). bar PF 토큰형도 동일 처리
    s = re.sub(r'\bbar\s*{\s*([A-Za-z0-9 ]+?)\s*}',
               lambda m: ' bar' + re.sub(r'\s+', '', m.group(1)) + ' ', s)
    s = re.sub(r'\bbar\s+([A-Za-z0-9]+)', r' bar\1 ', s)
    # F prime → Fpr (미분 기호는 이름에 흡수)
    s = re.sub(r'([A-Za-z0-9])\s*\bprime\b', r'\1pr', s)
    s = re.sub(r'\bprime\b', 'pr', s)

    s = s.replace('{', '(').replace('}', ')')
    s = s.replace(':', '/')                    # 비율 a:b — 등식 대조에선 a/b와 등가
    # 거듭제곱근: root (n) of (x) → x^(1/n), 그 외 root는 sqrt
    s = re.sub(r'\broot\s*\(([^()]+)\)\s*of\s*\(([^()]+)\)', r'((\2)**(1/(\1)))', s)
    s = re.sub(r'\broot\s*(\d+)', r'sqrt(\1)', s)
    s = re.sub(r'\broot\b', 'sqrt', s)
    s = re.sub(r'\bsqrt\s+([A-Za-z0-9.]+)', r'sqrt(\1)', s)  # sqrt 2 토큰형
    s = _strip_point_labels(s)                 # F(4,0) 좌표 — 라벨 제거, 튜플만 남김
    s = re.sub(r'\s*\bover\b\s*', '/', s)
    s = re.sub(r'\bTIMES\b', '*', s)
    s = re.sub(r'\bCDOT\b', '*', s)
    s = re.sub(r'\bDIVIDE\b', '/', s)
    s = s.replace('^', '**')
    # 첨자: a_(n+1) → a_n1, a _ 1 → a_1 (심볼 이름에 흡수)
    s = re.sub(r'([A-Za-z])\s*_\s*\(([^()]*)\)',
               lambda m: m.group(1) + '_' + re.sub(r'[^A-Za-z0-9]', '', m.group(2)), s)
    s = re.sub(r'([A-Za-z])\s*_\s*([A-Za-z0-9])', r'\1_\2', s)
    return s


def _strip_point_labels(s):
    """좌표 표기 NAME(a, b)의 라벨 제거 → (a, b) 튜플만 남긴다.

    괄호 안 최상위에 콤마가 있는 경우만 좌표로 본다. FUNC_NAMES는 함수라 보존.
    (implicit multiplication이 Symbol*(tuple)을 만들면 TypeError가 나는 것을 차단)
    """
    def _tuple_ahead(k):
        """s[k]가 '(' 이고 그 괄호 최상위에 콤마가 있으면 True."""
        depth, p, comma = 0, k, False
        while p < n:
            if s[p] == '(':
                depth += 1
            elif s[p] == ')':
                depth -= 1
                if depth == 0:
                    break
            elif s[p] == ',' and depth == 1:
                comma = True
            p += 1
        return comma

    out, i, n = [], 0, len(s)
    while i < n:
        # 괄호로 감싼 라벨 "( P)(a, b)" — {rm P}가 괄호로 변환된 형태
        mw = re.match(r'\(\s*([A-Za-z][A-Za-z0-9_]*)\s*\)', s[i:])
        if mw and mw.group(1) not in FUNC_NAMES:
            k = i + mw.end()
            while k < n and s[k] == ' ':
                k += 1
            if k < n and s[k] == '(' and _tuple_ahead(k):
                i = k
                continue
        m = re.match(r'[A-Za-z][A-Za-z0-9_]*', s[i:])
        if m:
            name = m.group()
            j = i + len(name)
            k = j
            while k < n and s[k] == ' ':
                k += 1
            if name not in FUNC_NAMES and k < n and s[k] == '(' and _tuple_ahead(k):
                i = k              # 라벨만 건너뛰고 '(' 부터 계속
                continue
            out.append(name)
            i = j
            continue
        out.append(s[i])
        i += 1
    return ''.join(out)


def _split_top(s, seps):
    """괄호 깊이 0에서만 seps 문자로 분할."""
    parts, buf, depth = [], [], 0
    for ch in s:
        if ch in '([':
            depth += 1
        elif ch in ')]':
            depth = max(0, depth - 1)
        if depth == 0 and ch in seps:
            parts.append(''.join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append(''.join(buf))
    return parts


def _split_relations(s):
    """깊이 0의 관계 연산자로 분할 → (조각 리스트, 연산자 리스트)."""
    parts, ops, buf, depth, i = [], [], [], 0, 0
    while i < len(s):
        ch = s[i]
        if ch in '([':
            depth += 1
        elif ch in ')]':
            depth = max(0, depth - 1)
        if depth == 0:
            two = s[i:i + 2]
            if two in ('!=', '<=', '>='):
                parts.append(''.join(buf)); ops.append(two); buf = []; i += 2
                continue
            if ch in '=<>' and two != '**'[:2]:
                parts.append(''.join(buf)); ops.append(ch); buf = []; i += 1
                continue
        buf.append(ch)
        i += 1
    parts.append(''.join(buf))
    return parts, ops


def _parse(frag):
    frag = frag.strip()
    if not frag:
        return None
    try:
        return parse_expr(frag, transformations=TRANSFORMS, global_dict=GLOBALS)
    except Exception as e:
        raise TranspileError('parse_error', f'{frag[:50]!r}: {type(e).__name__}')


def transpile(script):
    """한글 수식 스크립트 1개 → (statements, flags). 실패 시 TranspileError."""
    flags = set()
    if TEXT_CHARS.search(script):
        flags.add('text')
        script = TEXT_CHARS.sub('#', script)   # 텍스트 자리에서 문장 분리
    s = _normalize(script, flags)

    statements = []
    for line in s.split('#'):                  # #: 여러 줄 수식의 줄바꿈
        line = line.replace('&', ' ').strip()  # &: 정렬 표식
        if not line:
            continue
        for stmt in _split_top(line, ','):     # 나열형 "x=1, y=2" 분리
            stmt = stmt.strip().rstrip('.')
            if not re.search(r'[0-9A-Za-z]', stmt):
                continue                       # 텍스트를 걷어낸 자리의 연산자 부스러기
            parts, ops = _split_relations(stmt)
            # 꼬리 고아 연산자 "$k<$" — 파싱은 살리되 플래그로 표시 (조판 결함 신호)
            while parts and not parts[-1].strip() and ops:
                parts.pop(); ops.pop()
                flags.add('trailing_op')
            exprs = [_parse(p) for p in parts]
            # 연속행 "& = ..." → 선두 빈 조각 허용, 그 외 빈 조각은 결함
            if exprs and exprs[0] is None and ops:
                exprs, ops = exprs[1:], ops[1:]
            if any(e is None for e in exprs):
                raise TranspileError('empty_operand', stmt[:50])
            if exprs:
                statements.append({'exprs': exprs, 'ops': ops})
    return statements, flags


# ── 전수 측정 러너 ──────────────────────────────────────────────

EQ = re.compile(r'\$(.+?)\$', re.S)


def _iter_equations(items):
    for it in items:
        fields = [('본문', it['q'])] + \
                 [(f'보기{k+1}', o) for k, o in enumerate(it['opts'])] + \
                 [('해설', it['expl'])]
        for fname, text in fields:
            for m in EQ.findall(text or ''):
                yield it.get('loc', it['no']), fname, m


def measure(paths, dump=None):
    total, ok, empty = 0, 0, 0
    flag_count = Counter()
    failures = []
    for path in paths:
        data = json.load(open(path, encoding='utf-8'))
        for loc, fname, script in _iter_equations(data['items']):
            total += 1
            try:
                stmts, flags = transpile(script)
            except TranspileError as e:
                failures.append({'loc': loc, 'field': fname,
                                 'script': script[:80], 'why': e.detail or e.category})
                continue
            if not stmts:
                empty += 1
            else:
                ok += 1
            for f in flags:
                flag_count[f] += 1

    print(f'수식 {total}개 → 파싱 성공 {ok} ({ok/total:.1%}) / '
          f'빈 수식 {empty} / 실패 {len(failures)} ({len(failures)/total:.1%})')
    print(f'플래그: {dict(flag_count)}')

    if failures:
        # 실패 사유를 남은 대문자 키워드(미지원 문법) 우선으로 군집화
        def cluster(f):
            kws = sorted(set(re.findall(r'[A-Z]{2,}', f['script'])))
            return 'kw:' + '+'.join(kws) if kws else 'err:' + f['why'].split(':')[-1].strip()
        pat = Counter(cluster(f) for f in failures)
        print('\n실패 패턴 상위 10:')
        for key, n in pat.most_common(10):
            samples = [f for f in failures if cluster(f) == key][:3]
            print(f'  {n:4d}  {key}')
            for smp in samples:
                print(f'         {smp["loc"]} {smp["field"]}: {smp["script"][:60]}')
    if dump:
        json.dump(failures, open(dump, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        print(f'\n실패 전체 {len(failures)}건 → {dump}')


# ── 자가 테스트 (인수인계 문서 PoC 케이스) ──────────────────────

def selftest():
    cases = [
        # (수식 A, 수식 B, 동치여야 하는가)
        ('4- sqrt {2}', '- sqrt {2} +4', True),
        ('{1} over {2}', '0.5', True),
        ('2 TIMES 3', '6', True),
        ('k<{-{1}over{2}}', 'k< -1/2', None),        # 관계식 — 파싱만 확인
        ('b^{2} & =c^{2}-a^{2}# & =5^{2}-9# & =16', None, None),
        ('bar{rm PF} + bar{rm QF} = 6', None, None),
        ('LEFT| x-2 RIGHT| <3', None, None),
        ('30 DEG', '30', True),
        ('x GEQ -1', None, None),
        ('a_{1} + a_{2}', None, None),
        ('rm F(4,``0)', None, None),                  # 좌표 표기
        ('rm P LEFT ( - {sqrt {10}} over {2} ,``- {1} over {2} RIGHT )', None, None),
        ('3:2', '1.5', True),                         # 비율 → 나눗셈 등가
        ('k<', None, None),                           # 고아 연산자 — 파싱은 살리고 플래그
    ]
    bad = 0
    for a, b, want_eq in cases:
        try:
            sa, fa = transpile(a)
        except TranspileError as e:
            print(f'FAIL parse: {a!r} → {e}'); bad += 1; continue
        if b is not None and want_eq is not None:
            sb, _ = transpile(b)
            ea, eb = sa[-1]['exprs'][-1], sb[-1]['exprs'][-1]
            same = sympy.simplify(ea - eb) == 0
            if same != want_eq:
                print(f'FAIL equiv: {a!r} vs {b!r} → {same}'); bad += 1; continue
        print(f'ok: {a!r}')
    print('실패' if bad else '전체 통과', f'({len(cases) - bad}/{len(cases)})')
    return bad


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('items_json', nargs='*')
    ap.add_argument('--dump', help='실패 목록 JSON 저장 경로')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if not a.items_json:
        ap.error('items_json 하나 이상 필요 (또는 --selftest)')
    measure(a.items_json, dump=a.dump)
