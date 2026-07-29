#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extra_checks.py — 결정론 부가 검사: 편집 메모·수식 표기 스타일·중복 후보·통계·메타 정합.

수학적 오류 심층 검증(문제를 직접 푸는 것)은 여기서 안 한다 — LLM 검수 영역.
여기 있는 건 전부 패턴·집계 기반이라 오탐 위험이 낮은 것들이다.
"""
import difflib
import re
from collections import Counter

EQ = re.compile(r'\$(.+?)\$', re.S)

MEMOS = [
    re.compile(r'\(그림 ?수정\??\)'),
    re.compile(r'\[그림\]'),
    re.compile(r'←[^\n$]{0,60}'),
]

# (유형, 수식 정규식, 설명)
STYLE = [
    ('첨자 안 쉼표', re.compile(r'_\s*\{[^}]*,\s*\}'),
     '쉼표가 아래첨자로 작게 조판됨 — 실제 렌더링 오류'),
    ('root 표기', re.compile(r'\broot'), 'sqrt 표기로 통일 필요'),
    ('아래첨자 민형식 a_1', re.compile(r'[A-Za-z]_\d'), '다른 곳은 a _{1} 형식'),
    ('위첨자 민형식 a^2', re.compile(r'\^\d'), '다른 곳은 a ^{2} 형식'),
    ('중괄호 안 여분 공백', re.compile(r'\{\s+\S'), '{ 1} over { 2} 형태'),
    ('비교식 불필요 중괄호',
     re.compile(r'[<>]\s*\{\s*-?\d+(?:\.\d+)?\s*\}(?!\s*(?:over|\^|_|/))'),
     'k<{-1} 형태 — 정규화 시 뭉개질 위험'),
]


# 원고에서 실제 관측된 오탈자만. 문맥 없이도 확실한 것만 넣는다(오탐 금지).
TYPOS = [
    (re.compile(r'수선이 발'), '수선의 발'),
    (re.compile(r'커야한다'), '커야 한다 (띄어쓰기)'),
    (re.compile(r'작아야한다'), '작아야 한다 (띄어쓰기)'),
    (re.compile(r'추죽'), '주축'),
    (re.compile(r'(?<![가-힣])개다(?=[.\s]|$)'), '개이다'),
    (re.compile(r'되므로므로|이므로므로'), '중복 어미'),
    (re.compile(r'(\S)\s{2,}(\S)'), '연속 공백'),
]


def _fields(it):
    yield '본문', it.get('q', '')
    for k, o in enumerate(it.get('opts', [])):
        yield f'보기{k+1}', o
    yield '해설', it.get('expl', '')
    if it.get('src_cite'):
        yield '출처', it['src_cite']


def _typos(items):
    """오탈자 사전 검출 + 출처 서명 표기 혼용(소수파만 지적)."""
    out = []
    for it in items:
        for fn, tx in _fields(it):
            plain = EQ.sub(' ', tx or '')          # 수식 안은 검사 제외
            for pat, fix in TYPOS:
                for m in pat.finditer(plain):
                    if pat.pattern == r'(\S)\s{2,}(\S)':
                        continue                    # 연속 공백은 조판 관행 — 보류
                    out.append({'loc': it['loc'], 'page': it.get('page'),
                                'field': fn, 'hit': m.group().strip(), 'fix': fix})
    return out


def _citations(items):
    """출처 서명 표기 혼용 — 다수파 대비 소수파를 지적."""
    VARIANTS = [('쎈', '쏀'), ('개뿔', '게뿔'), ('마플', '마블')]
    out = []
    for a, b in VARIANTS:
        ha = [it['loc'] for it in items if a in (it.get('src_cite') or '')]
        hb = [it['loc'] for it in items if b in (it.get('src_cite') or '')]
        if ha and hb:
            major, minor, mj, mn = ((a, b, ha, hb) if len(ha) >= len(hb)
                                    else (b, a, hb, ha))
            out.append({'major': major, 'minor': minor,
                        'major_n': len(mj), 'minor_n': len(mn),
                        'locs': mn})
    return out


def _memos(items):
    out = []
    for it in items:
        for fn, tx in _fields(it):
            for pat in MEMOS:
                for m in pat.finditer(tx or ''):
                    out.append({'loc': it['loc'], 'page': it.get('page'),
                                'field': fn, 'hit': m.group().strip()})
    return out


def _style(items):
    types = {}
    for it in items:
        for fn, tx in _fields(it):
            for eq in EQ.findall(tx or ''):
                for name, pat, hint in STYLE:
                    m = pat.search(eq)
                    if m:
                        t = types.setdefault(name, {'hint': hint, 'n': 0,
                                                    'locs': [], 'example': ''})
                        t['n'] += 1
                        if it['loc'] not in t['locs']:
                            t['locs'].append(it['loc'])
                        if not t['example']:
                            t['example'] = eq.strip()[:50]
                # 한 수식 안에서 첨자 표기가 뒤섞임 (a ^{2} 와 b^2 혼용 등)
                for kind, rich, plain in (
                        ('위첨자', r'\^\s*\{', r'\^\d'),
                        ('아래첨자', r'_\s*\{', r'[A-Za-z]_\d')):
                    if re.search(rich, eq) and re.search(plain, eq):
                        t = types.setdefault(f'한 수식 내 {kind} 형식 혼용',
                                             {'hint': '같은 수식에 두 표기가 섞임',
                                              'n': 0, 'locs': [], 'example': ''})
                        t['n'] += 1
                        if it['loc'] not in t['locs']:
                            t['locs'].append(it['loc'])
                        t['example'] = t['example'] or eq.strip()[:50]
                # 비교 연산자 좌우 공백 불일치 (a != 0 과 b!=0 혼용)
                if re.search(r'\S(?:!=|<=|>=)', eq) and re.search(r'\s(?:!=|<=|>=)\s', eq):
                    t = types.setdefault('비교 연산자 공백 불일치',
                                         {'hint': '한 수식 안에서 a != 0 과 b!=0 혼용',
                                          'n': 0, 'locs': [], 'example': ''})
                    t['n'] += 1
                    if it['loc'] not in t['locs']:
                        t['locs'].append(it['loc'])
                    t['example'] = t['example'] or eq.strip()[:50]
                # 보기 수식이 순수 숫자인데 꼬리 공백/백틱 → 우측 정렬 어긋남
                if fn.startswith('보기') and re.fullmatch(r'[\s`~]*\d+[\s`~]+', eq):
                    t = types.setdefault('수식 끝 여분 공백',
                                         {'hint': '선택지 정렬이 어긋남', 'n': 0,
                                          'locs': [], 'example': ''})
                    t['n'] += 1
                    if it['loc'] not in t['locs']:
                        t['locs'].append(it['loc'])
                    if not t['example']:
                        t['example'] = f'${eq}$'
    # 소수파 표기 검출: bar{rm ~ it} 대 bar{rm ~}
    with_it, without = [], []
    for it in items:
        for fn, tx in _fields(it):
            for eq in EQ.findall(tx or ''):
                for m in re.finditer(r'bar\s*\{[^{}]*\}', eq):
                    (with_it if re.search(r'\bit\b', m.group()) else without
                     ).append(it['loc'])
    tot = len(with_it) + len(without)
    if tot >= 8:
        minor, label = ((with_it, 'bar에 it 포함') if len(with_it) < len(without)
                        else (without, 'bar에 it 누락'))
        if minor and len(minor) / tot <= 0.2:
            types[f'서체 혼용: {label}'] = {
                'hint': f'전체 {tot}건 중 {len(minor)}건만 다른 형식',
                'n': len(minor), 'locs': sorted(set(minor)), 'example': ''}
    return types


def _dups(items, th=0.85):
    """중복 후보. 본문+보기+정답이 모두 같으면 '완전 중복'으로 등급을 올린다."""
    def norm(s):
        return re.sub(r'\s+', '', s or '')

    qs = [norm(it.get('q', '')) for it in items]
    full = [norm(it.get('q', '') + '|'.join(it.get('opts', [])) +
                 str(it.get('answer'))) for it in items]
    out = []
    for a in range(len(items)):
        if len(qs[a]) < 20:
            continue
        for b in range(a + 1, len(items)):
            if abs(len(qs[a]) - len(qs[b])) > max(len(qs[a]), len(qs[b])) * .3:
                continue
            r = difflib.SequenceMatcher(None, qs[a], qs[b]).ratio()
            if r >= th:
                exact = full[a] == full[b]
                out.append({'a': items[a]['loc'], 'ap': items[a].get('page'),
                            'b': items[b]['loc'], 'bp': items[b].get('page'),
                            'ratio': round(r, 3), 'exact': exact,
                            'same_ans': items[a]['answer'] == items[b]['answer']})
    out.sort(key=lambda x: (not x['exact'], -x['ratio']))
    return out


def _stats(items):
    c = Counter(it['answer'] for it in items if it.get('answer'))
    n = sum(c.values())
    dist = {k: c.get(k, 0) for k in range(1, 6)}
    chi2 = skewed = None
    if n >= 30:
        e = n / 5
        chi2 = round(sum((v - e) ** 2 / e for v in dist.values()), 2)
        skewed = chi2 > 9.488          # df=4, α=0.05
    longest = [it['loc'] for it in items if it.get('answer')
               and len(it['opts']) == 5
               and all(len(it['opts'][it['answer'] - 1]) > len(o)
                       for k, o in enumerate(it['opts']) if k != it['answer'] - 1)]
    return {'dist': dist, 'n': n, 'chi2': chi2, 'skewed': skewed,
            'longest_n': len(longest), 'longest': longest[:10]}


def _meta(items):
    """실측 불변식 정합 — 통과는 passed 문장으로, 위반은 findings로."""
    passed, findings = [], []

    def bad(loc, page, why):
        findings.append({'code': 'META_MISMATCH', 'sev': 'medium', 'no': 0,
                         'loc': loc, 'ans': None, 'found_in': [],
                         'want': '', 'tail': why, 'page': page})

    ids = [it['loc'] for it in items]
    dup = [k for k, v in Counter(ids).items() if v > 1]
    if dup:
        for d in dup:
            bad(d, None, '문항id 중복')
    else:
        passed.append(f'문항id 중복 없음 ({len(ids)}건)')

    ok = True
    for it in items:
        if len(it['opts']) != 5 or any(not o.strip() for o in it['opts']):
            bad(it['loc'], it.get('page'), '보기 5개 미완비')
            ok = False
    if ok:
        passed.append('선택지 5개 전부 채워짐')

    ok = True
    for it in items:
        if not it.get('answer') or not 1 <= it['answer'] <= 5:
            bad(it['loc'], it.get('page'), f'정답 범위 밖: {it.get("answer_raw")}')
            ok = False
    if ok:
        passed.append('정답 1~5 범위')

    ok = True
    for it in items:
        if len(set(o.strip() for o in it['opts'])) < len(it['opts']):
            bad(it['loc'], it.get('page'), '문항 내 동일 문자열 보기 존재')
            ok = False
    if ok:
        passed.append('한 문항 내 동일 보기 없음')

    ok = True
    for it in items:
        ku = it['meta'].get('지식단위', '').strip()
        if ku and ku not in it['loc']:
            bad(it['loc'], it.get('page'), f'지식단위({ku})가 문항id와 불일치')
            ok = False
    if ok:
        passed.append('지식단위 ↔ 문항id 정합')

    ok = True
    for it in items:
        d = it['meta'].get('난이도', '').strip()
        m = re.search(r'(\d)-\d+$', it['loc'])
        if d and m and d != m.group(1):
            bad(it['loc'], it.get('page'), f'난이도({d})가 문항id 숫자({m.group(1)})와 불일치')
            ok = False
    if ok:
        passed.append('난이도 ↔ 문항id 정합')

    groups = {}
    for it in items:
        m = re.match(r'(.+)-(\d+)$', it['loc'])
        if m:
            groups.setdefault(m.group(1), []).append(int(m.group(2)))
    ok = True
    for pre, seq in groups.items():
        s = sorted(seq)
        # 파일이 은행의 부분집합이라 1부터 시작하지 않을 수 있다 — 빈틈·중복만 결함
        if s != list(range(s[0], s[0] + len(s))):
            bad(f'{pre}-*', None, f'일련번호 불연속/중복: {s}')
            ok = False
    if ok:
        passed.append('접두 그룹별 일련번호 연속 (누락·중복 없음)')

    return passed, findings


def analyze(data):
    items = data['items']
    passed, meta_findings = _meta(items)
    dups = _dups(items)
    # 완전 중복(본문·보기·정답 동일)은 결함 카드로 올린다
    for d in dups:
        if d['exact']:
            meta_findings.append({
                'code': 'ITEM_DUP_EXACT', 'sev': 'high', 'no': 0,
                'loc': d['a'], 'ans': None, 'found_in': [], 'page': d['ap'],
                'want': d['b'],
                'tail': f'{d["b"]}와 본문·보기·정답이 완전히 동일 — 변형 없이 복사된 것으로 보임'})
    if not any(it.get('src_cite') for it in items):
        cites = []
    else:
        cites = _citations(items)
    n_cite = sum(1 for it in items if (it.get('src_cite') or '').strip())
    if n_cite == len(items) and items:
        passed.append(f'출처 표기 전 문항 기재 ({n_cite}건)')
    return {'memos': _memos(items), 'style': _style(items),
            'dups': dups, 'stats': _stats(items), 'typos': _typos(items),
            'citations': cites, 'passed': passed, 'findings': meta_findings}
