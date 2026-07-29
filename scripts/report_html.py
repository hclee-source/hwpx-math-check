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
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@600;700&display=swap');
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css');
:root{--bg:#FAF9F5;--surface:#FFF;--surface2:#F0EEE6;--text:#1F1E1D;
  --muted:#73726C;--border:#E4E1D5;--accent:#D97757;--ok:#5F7D50;
  --warn:#A9741B;--bad:#B3382C;
  --shadow:0 1px 2px rgba(31,30,29,.05),0 4px 14px rgba(31,30,29,.04)}
*{box-sizing:border-box}
body{font-family:'Pretendard Variable',Pretendard,-apple-system,sans-serif;
     background:var(--bg);max-width:900px;margin:0 auto;padding:36px 20px 48px;
     color:var(--text);line-height:1.65;-webkit-font-smoothing:antialiased}
h1{font-family:'Noto Serif KR',serif;font-size:1.6em;font-weight:700;
   letter-spacing:-.01em;margin:0 0 4px}
h2{font-size:1.05em;font-weight:700;margin:34px 0 10px}
.muted{color:var(--muted);font-size:.86em}
.cards{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}
.card{border:1px solid var(--border);border-radius:14px;padding:14px 20px;
      min-width:118px;text-align:center;background:var(--surface);
      box-shadow:var(--shadow)}
.card b{display:block;font-size:1.65em;font-weight:800;letter-spacing:-.02em}
.card{font-size:.85em;color:var(--muted)}
.ok{color:var(--ok)}.warn{color:var(--warn)}
.empty{background:#EFF3EA;border:1px solid #CBDABE;border-radius:14px;
       padding:14px 18px;color:var(--ok);font-weight:700}
details.finding{border:1px solid var(--border);border-left:5px solid var(--muted);
       border-radius:14px;margin:10px 0;background:var(--surface);
       box-shadow:var(--shadow);overflow:hidden}
details.finding[data-sev=high]{border-left-color:var(--bad)}
details.finding[data-sev=medium]{border-left-color:var(--warn)}
details.finding>summary{cursor:pointer;padding:12px 16px;font-weight:600;
       list-style-position:inside;transition:.12s}
details.finding>summary:hover{background:var(--surface2)}
details.finding>summary .sev,details.finding>summary .page{
       display:inline-block;padding:1px 10px;border-radius:999px;color:#fff;
       font-size:.76em;margin-right:7px;font-weight:700;vertical-align:1px}
details.finding[data-sev=high] .sev{background:var(--bad)}
details.finding[data-sev=medium] .sev{background:var(--warn)}
details.finding[data-sev=low] .sev{background:var(--muted)}
details.finding>summary .page{background:var(--accent)}
.body{padding:2px 18px 14px}
.row{margin:9px 0}
.quote{background:var(--surface2);border-radius:10px;padding:9px 14px;margin:5px 0;
       font-size:.95em;word-break:break-all}
mark{background:#F6D3CB;color:#8F2A1E;padding:1px 4px;border-radius:4px;
     font-weight:700}
.eq{font-family:'Cambria Math','STIX Two Math',serif;background:#EBE7DB;
    padding:0 5px;border-radius:4px}
.fix{color:var(--ok);margin-top:5px;font-weight:600}
.hint{background:#FBF3E3;border:1px solid #EBDCB8;border-radius:10px;
      padding:8px 14px;margin-top:10px;font-size:.9em}
.loclist{font-family:ui-monospace,Consolas,monospace;font-size:.86em;
      word-break:break-all}
table.mini{border-collapse:separate;border-spacing:0;margin:8px 0;font-size:.92em;
      border:1px solid var(--border);border-radius:10px;overflow:hidden}
table.mini th,table.mini td{border-bottom:1px solid var(--border);
      border-right:1px solid var(--border);padding:6px 14px}
table.mini th{background:var(--surface2)}
table.mini tr:last-child td{border-bottom:0}
table.mini th:last-child,table.mini td:last-child{border-right:0}
table.mini tr.bad td{background:#F6D3CB;font-weight:700}
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
            page = (item or {}).get('page')
            pg = f'<span class="page">{page}쪽</span>' if page else ''
            p.append(
                f'<details class="finding" data-sev="{sev}"{" open" if i < 3 else ""}>'
                f'<summary><span class="sev">{SEV_KO.get(sev, sev)}</span>{pg}'
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
                pg = ''
                if it:
                    if it.get('page'):
                        pg = f'<span class="page">{it["page"]}쪽</span>'
                    lines = [l for l in it.get('expl', '').split('\n') if l.strip()]
                    if lines:
                        tail = (f'<div class="row">해설 마지막 줄:'
                                f'<div class="quote">{pretty_text(lines[-1])}</div></div>')
                p.append(f'<details class="finding" data-sev="low">'
                         f'<summary><span class="sev">{_e(why)}</span>{pg}'
                         f'{_e(loc)}</summary><div class="body">{tail}</div></details>')

    tw = stats.get('쌍둥이')
    if tw:
        p.append('<h2>쌍둥이문항 교차</h2>'
                 f'<p>쌍 성립 {tw.get("쌍성립", 0)} · 1:N 참조 {tw.get("1:N참조", 0)} · '
                 f'정답 번호 상이 {tw.get("정답상이", 0)}(정상 — 쌍둥이는 숫자 변형 문항)</p>')

    p.append('<p class="muted">이 보고서는 1차 기계 검수 결과다. 풀이 과정 자체의 오류, '
             '그림, 문장 표현은 검사 범위 밖이며 최종 판단은 사람이 한다.</p>')
    return '\n'.join(p)
