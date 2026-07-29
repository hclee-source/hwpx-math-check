#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""report_html.py — 검수 결과를 편집자용 HTML 보고서로 렌더링.

결함마다 카드를 만들어 문항의 실제 내용(보기·해설)을 보여주고,
문제 지점을 형광펜으로 표시하고, 수정 제안을 붙인다.
수식은 한글 스크립트를 읽을 수 있는 형태(√, 분수, 위첨자)로 바꿔 보여준다.
"""
import html as _html
import re
import time

CODE_DESC = {
    'ANS_IN_OTHER':   '정답이 아닌 보기가 해설 결론과 일치 — 정답 번호 오기 의심',
    'ANS_RANGE_OUT':  '범위형 결론에 정답 값이 없고 다른 보기 값이 들어감',
    'OPT_DUP_EQ':     '보기 두 개가 수학적으로 같은 값',
    'EQ_ORPHAN_OP':   '수식이 연산자에서 두 조각으로 쪼개짐 (조판 결함)',
    'EQ_UNBALANCED':  '수식 괄호 짝이 안 맞음 (조판 사고)',
    'TWIN_MISSING':   '쌍둥이문항 필드가 비어 있음',
    'TWIN_BROKEN_REF': '쌍둥이문항이 가리키는 문항이 없음',
    'TWIN_META_DIFF': '쌍둥이끼리 지식단위/난이도/학습행동영역 불일치',
    'TWIN_ID_PATTERN': '쌍둥이 문항id 몸통 불일치 (오타 의심)',
    'TWIN_UNREF':     '평가 어디서도 참조되지 않는 일반 문항',
}
FIX_HINT = {
    'EQ_ORPHAN_OP':   '한글에서 쪼개진 두 수식을 지우고 수식 하나로 다시 입력하세요.',
    'EQ_UNBALANCED':  '수식 편집기에서 괄호 짝을 맞추세요.',
    'ANS_IN_OTHER':   '정답 번호가 맞는지, 해설이 다른 문항 것이 아닌지 확인하세요.',
    'ANS_RANGE_OUT':  '정답 번호가 맞는지, 해설의 범위 결론이 맞는지 확인하세요.',
    'OPT_DUP_EQ':     '두 보기 중 하나를 다른 값으로 바꾸세요.',
    'TWIN_META_DIFF': '두 문항의 메타 필드를 같게 맞추세요.',
    'TWIN_BROKEN_REF': '쌍둥이문항 필드의 문항id 오타를 확인하세요.',
}
SEV_KO = {'high': '높음', 'medium': '중간', 'low': '낮음'}

# 고아 연산자: 연산자로 끝나는 수식 뒤에 수식이 바로 이어짐
ORPHAN = re.compile(r'(\$[^$]*?(?:<=|>=|[=<>+\-])\s*\$)(\s*)(\$[^$]*?\$)')
EQ = re.compile(r'\$(.+?)\$', re.S)

SUP = dict(zip('0123456789-+', '⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺'))


def _sup(t):
    t = t.strip()
    if all(c in SUP for c in t):
        return ''.join(SUP[c] for c in t)
    return '^(' + t + ')'


def pretty_eq(s):
    """한글 수식 스크립트 → 읽을 수 있는 텍스트 (√, 분수, ±, 위첨자…)."""
    s = s.replace('`', ' ').replace('~', ' ')
    s = re.sub(r'\b(it|rm)\b', ' ', s)
    s = re.sub(r'\b(LEFT|RIGHT)\b\s*', '', s)
    s = re.sub(r'\bbar\s*{([^{}]*)}',
               lambda m: ''.join(c + '̅' for c in m.group(1).replace(' ', '')), s)
    for _ in range(3):    # 중첩 분수
        s = re.sub(r'{([^{}]*)}\s*over\s*{([^{}]*)}', r'(\1)/(\2)', s)
    s = re.sub(r'\s*\bover\b\s*', '/', s)
    s = re.sub(r'\bsqrt\s*{([^{}]*)}', r'√(\1)', s)
    s = re.sub(r'\bsqrt\b\s*', '√', s)
    s = re.sub(r'\^\s*{([^{}]*)}', lambda m: _sup(m.group(1)), s)
    s = re.sub(r'\^(\d+)', lambda m: _sup(m.group(1)), s)
    s = re.sub(r'_\s*{([^{}]*)}', r'_\1', s)
    for a, b in (('TIMES', '×'), ('CDOTS', '⋯'), ('CDOT', '·'), ('+-', '±'),
                 ('<=', '≤'), ('>=', '≥'), ('!=', '≠'), ('DEG', '°'),
                 ('ANGLE', '∠'), ('TRIANGLE', '△'), ('prime', '′')):
        s = s.replace(a, b)
    s = s.replace('{', '(').replace('}', ')')
    return re.sub(r'\s+', ' ', s).strip()


def pretty_text(text):
    """필드 텍스트의 $수식$을 읽을 수 있는 형태로 (HTML 이스케이프 포함)."""
    out = []
    pos = 0
    for m in EQ.finditer(text or ''):
        out.append(_e(text[pos:m.start()]))
        out.append('<span class="eq">' + _e(pretty_eq(m.group(1))) + '</span>')
        pos = m.end()
    out.append(_e(text[pos:] if text else ''))
    return ''.join(out)


def _e(s):
    return _html.escape(str(s))


def _clip(text, mark_span, ctx=45):
    """mark_span(문자 구간) 주변만 남기고 자른다."""
    a, b = mark_span
    lo, hi = max(0, a - ctx), min(len(text), b + ctx)
    return (('…' if lo else '') + text[lo:a], text[a:b],
            text[b:hi] + ('…' if hi < len(text) else ''))


def _orphan_rows(item, fields):
    """고아 연산자 결함의 필드별 표시 행: (필드명, 강조 HTML, 수정 제안)"""
    rows = []
    fmap = {'해설': item.get('expl', ''), '본문': item.get('q', '')}
    for k, o in enumerate(item.get('opts', [])):
        fmap[f'보기{k+1}'] = o
    for fname in fields:
        raw = fmap.get(fname, '')
        for m in ORPHAN.finditer(raw):
            pre, hit, post = _clip(raw, (m.start(), m.end()))
            shown = (pretty_text(pre) + '<mark>' + pretty_text(hit) + '</mark>'
                     + pretty_text(post))
            merged = m.group(1)[:-1].rstrip() + ' ' + m.group(3)[1:].lstrip()
            fix = pretty_eq(EQ.sub(lambda x: x.group(1), merged))
            rows.append((fname, shown, fix))
    return rows


def _card_body(f, item, items):
    code = f['code']
    p = []
    if item is None:
        return ''
    ans = f.get('ans')
    opts = item.get('opts', [])

    if code == 'EQ_ORPHAN_OP':
        fields = [x.strip() for x in str(f.get('want', '')).split(',') if x.strip()]
        for fname, shown, fix in _orphan_rows(item, fields):
            p.append(f'<div class="row"><b>{_e(fname)}</b> — 수식이 두 조각으로 입력됨:'
                     f'<div class="quote">{shown}</div>'
                     f'<div class="fix">수정 제안 → 수식 하나로: '
                     f'<span class="eq">{_e(fix)}</span></div></div>')

    elif code == 'EQ_UNBALANCED':
        p.append(f'<div class="row">괄호 짝이 안 맞는 수식:'
                 f'<div class="quote"><mark>{_e(f.get("want", ""))}</mark></div></div>')

    elif code in ('ANS_IN_OTHER', 'ANS_RANGE_OUT'):
        tail = [l for l in item.get('expl', '').split('\n') if l.strip()]
        if ans and ans <= len(opts):
            p.append(f'<div class="row">표기된 정답 <b>{ans}번</b>:'
                     f'<div class="quote">{pretty_text(opts[ans-1])}</div></div>')
        if tail:
            p.append(f'<div class="row">해설 결론(마지막 줄):'
                     f'<div class="quote">{pretty_text(tail[-1])}</div></div>')
        for k in f.get('found_in', []):
            if k <= len(opts):
                p.append(f'<div class="row">결론과 일치하는 보기 <b>{k}번</b>:'
                         f'<div class="quote"><mark>{pretty_text(opts[k-1])}</mark></div></div>')

    elif code == 'OPT_DUP_EQ':
        for k in f.get('found_in', []):
            if k <= len(opts):
                p.append(f'<div class="row">보기 <b>{k}번</b>:'
                         f'<div class="quote"><mark>{pretty_text(opts[k-1])}</mark></div></div>')

    elif code == 'TWIN_META_DIFF':
        twin = items.get(str(f.get('want', '')))
        rows = ''
        for fld in ('지식단위', '난이도', '학습행동영역'):
            a = item.get('meta', {}).get(fld, '')
            b = (twin or {}).get('meta', {}).get(fld, '')
            hl = ' class="bad"' if a.strip() != b.strip() else ''
            rows += (f'<tr{hl}><td>{_e(fld)}</td><td>{_e(a)}</td><td>{_e(b)}</td></tr>')
        p.append(f'<table class="mini"><tr><th></th><th>{_e(f["loc"])}</th>'
                 f'<th>{_e(f.get("want", ""))}</th></tr>{rows}</table>')

    elif code.startswith('TWIN'):
        p.append(f'<div class="row">{_e(f.get("tail", ""))}'
                 + (f' — 대상: <b>{_e(f.get("want"))}</b>' if f.get('want') else '')
                 + '</div>')

    hint = FIX_HINT.get(code)
    if hint:
        p.append(f'<div class="hint">✏ {_e(hint)}</div>')
    return '\n'.join(p)


CSS = """
body{font-family:'Malgun Gothic',sans-serif;max-width:940px;margin:24px auto;
     padding:0 16px;color:#222;line-height:1.6}
h1{font-size:1.4em;border-bottom:2px solid #333;padding-bottom:6px}
h2{font-size:1.1em;margin-top:28px}
.muted{color:#7f8c8d;font-size:.88em}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}
.card{border:1px solid #ddd;border-radius:8px;padding:10px 16px;min-width:110px;
      text-align:center;background:#fafafa}
.card b{display:block;font-size:1.5em}
.ok{color:#1e8449}.warn{color:#b9770e}
.empty{background:#eafaf1;border:1px solid #a9dfbf;border-radius:8px;
       padding:12px 16px;color:#1e8449;font-weight:bold}
details.finding{border:1px solid #ddd;border-left:6px solid #999;border-radius:8px;
       margin:10px 0;background:#fff}
details.finding[data-sev=high]{border-left-color:#c0392b}
details.finding[data-sev=medium]{border-left-color:#b9770e}
details.finding>summary{cursor:pointer;padding:10px 14px;font-weight:bold;
       list-style-position:inside}
details.finding>summary .sev{padding:1px 8px;border-radius:10px;color:#fff;
       font-size:.8em;margin-right:6px}
details.finding[data-sev=high] .sev{background:#c0392b}
details.finding[data-sev=medium] .sev{background:#b9770e}
details.finding[data-sev=low] .sev{background:#7f8c8d}
.body{padding:2px 16px 12px}
.row{margin:8px 0}
.quote{background:#f7f7f7;border-radius:6px;padding:8px 12px;margin:4px 0;
       font-size:.95em;word-break:break-all}
mark{background:#ffd6d6;color:#a00;padding:1px 3px;border-radius:3px;font-weight:bold}
.eq{font-family:'Cambria Math','Segoe UI',serif;background:#eef4fb;
    padding:0 4px;border-radius:3px}
.fix{color:#1e8449;margin-top:4px}
.hint{background:#fff8e6;border:1px solid #f0dfa8;border-radius:6px;
      padding:6px 12px;margin-top:8px;font-size:.92em}
.loclist{font-family:Consolas,monospace;font-size:.88em;word-break:break-all}
table.mini{border-collapse:collapse;margin:6px 0;font-size:.92em}
table.mini th,table.mini td{border:1px solid #ccc;padding:4px 10px}
table.mini tr.bad td{background:#ffd6d6;font-weight:bold}
"""


def render(findings, stats, details, sources, items=None):
    items = items or {}
    now = time.strftime('%Y-%m-%d %H:%M')
    p = [f'<meta charset="utf-8"><title>문항 검수 보고서</title><style>{CSS}</style>']
    p.append('<h1>수학 문항 검수 보고서</h1>')
    p.append(f'<p class="muted">{_e(" · ".join(sources))}<br>생성 {now} · '
             'hwpx-math-check (정답↔해설 SymPy 검산 + 조판 결함 + 쌍둥이 교차)</p>')

    p.append(f'<h2>결함 후보 — {len(findings)}건</h2>')
    if not findings:
        p.append('<div class="empty">결함 후보 없음 — 기계 판정 기준 통과</div>')
    else:
        p.append('<p class="muted">각 항목을 클릭하면 문항 내용과 문제 지점, '
                 '수정 제안이 열립니다.</p>')
        for i, f in enumerate(findings):
            sev = f.get('sev', 'low')
            item = items.get(str(f.get('loc', '')))
            body = _card_body(f, item, items)
            p.append(
                f'<details class="finding" data-sev="{sev}"{" open" if i < 3 else ""}>'
                f'<summary><span class="sev">{SEV_KO.get(sev, sev)}</span>'
                f'{_e(f.get("loc", ""))} — {_e(CODE_DESC.get(f["code"], f["code"]))}'
                f'<span class="muted"> · #{f.get("no", "")} 정답 {f.get("ans", "")}'
                f' · {_e(f["code"])}</span></summary>'
                f'<div class="body">{body or "<p class=muted>상세 없음</p>"}</div></details>')

    # 검산 요약
    tot = {'정답유일증명': 0, '정답일치': 0, '판정불가': 0, '결론없음': 0}
    todo = {'판정불가': [], '결론없음': []}
    for src, d in details.items():
        for k in tot:
            tot[k] += len(d.get(k, []))
        for k in todo:
            todo[k] += d.get(k, [])
    n_all = sum(tot.values())
    if n_all:
        p.append('<h2>정답 검산 요약</h2><div class="cards">')
        p.append(f'<div class="card"><b class="ok">{tot["정답유일증명"]}</b>정답 유일 증명</div>')
        p.append(f'<div class="card"><b class="ok">{tot["정답일치"]}</b>정답 일치</div>')
        p.append(f'<div class="card"><b class="warn">{tot["판정불가"]}</b>판정 불가</div>')
        p.append(f'<div class="card"><b class="warn">{tot["결론없음"]}</b>결론 없음</div>')
        p.append('</div>')
        ok = tot['정답유일증명'] + tot['정답일치']
        p.append(f'<p>검산 대상 {n_all}문항 중 <b>{ok}문항({ok / n_all:.0%})</b>은 '
                 '정답 번호가 해설 결론과 수학적으로 일치함을 확인했다.</p>')

    n_todo = sum(len(v) for v in todo.values())
    if n_todo:
        p.append(f'<h2>사람이 정독할 문항 — {n_todo}건</h2>'
                 '<p class="muted">결함이라는 뜻이 아니라 자동 검증이 안 됐다는 뜻이다. '
                 '항목을 클릭하면 해설 결론이 보인다.</p>')
        for why, locs in todo.items():
            for loc in locs:
                it = items.get(str(loc))
                tail = ''
                if it:
                    lines = [l for l in it.get('expl', '').split('\n') if l.strip()]
                    if lines:
                        tail = (f'<div class="row">해설 마지막 줄:'
                                f'<div class="quote">{pretty_text(lines[-1])}</div></div>')
                p.append(f'<details class="finding" data-sev="low">'
                         f'<summary><span class="sev">{_e(why)}</span>'
                         f'{_e(loc)}</summary><div class="body">{tail}</div></details>')

    tw = stats.get('쌍둥이')
    if tw:
        p.append('<h2>쌍둥이문항 교차</h2>'
                 f'<p>쌍 성립 {tw.get("쌍성립", 0)} · 1:N 참조 {tw.get("1:N참조", 0)} · '
                 f'정답 번호 상이 {tw.get("정답상이", 0)}(정상 — 쌍둥이는 숫자 변형 문항)</p>')

    p.append('<p class="muted">이 보고서는 1차 기계 검수 결과다. 풀이 과정 자체의 오류, '
             '그림, 문장 표현은 검사 범위 밖이며 최종 판단은 사람이 한다.</p>')
    return '\n'.join(p)
