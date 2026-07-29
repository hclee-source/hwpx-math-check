#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""report_html.py — 검수 결과를 편집자가 읽을 HTML 보고서로 렌더링."""
import html as _html
import time

CODE_DESC = {
    'ANS_IN_OTHER':   '정답이 아닌 보기가 해설 결론과 일치 — 정답 번호 오기 의심',
    'ANS_RANGE_OUT':  '범위형 결론에 정답 값이 없고 다른 보기 값이 들어감',
    'OPT_DUP_EQ':     '보기 두 개가 수학적으로 같은 값',
    'EQ_ORPHAN_OP':   '수식이 연산자에서 두 조각으로 쪼개짐 (조판 결함)',
    'EQ_UNBALANCED':  '수식 괄호 짝 안 맞음 (조판 사고)',
    'TWIN_MISSING':   '쌍둥이문항 필드가 비어 있음',
    'TWIN_BROKEN_REF': '쌍둥이문항이 가리키는 문항이 없음',
    'TWIN_META_DIFF': '쌍둥이끼리 지식단위/난이도/학습행동영역 불일치',
    'TWIN_ID_PATTERN': '쌍둥이 문항id 몸통 불일치 (오타 의심)',
    'TWIN_UNREF':     '평가 어디서도 참조되지 않는 일반 문항',
}
SEV_KO = {'high': '높음', 'medium': '중간', 'low': '낮음'}
SEV_COLOR = {'high': '#c0392b', 'medium': '#b9770e', 'low': '#7f8c8d'}

CSS = """
body{font-family:'Malgun Gothic',sans-serif;max-width:920px;margin:24px auto;
     padding:0 16px;color:#222;line-height:1.55}
h1{font-size:1.4em;border-bottom:2px solid #333;padding-bottom:6px}
h2{font-size:1.1em;margin-top:28px}
table{border-collapse:collapse;width:100%;font-size:.92em}
th,td{border:1px solid #ccc;padding:6px 9px;text-align:left;vertical-align:top}
th{background:#f2f2f2}
.sev{font-weight:bold;white-space:nowrap}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}
.card{border:1px solid #ddd;border-radius:8px;padding:10px 16px;min-width:110px;
      text-align:center;background:#fafafa}
.card b{display:block;font-size:1.5em}
.ok{color:#1e8449}.warn{color:#b9770e}.muted{color:#7f8c8d;font-size:.88em}
.loclist{font-family:Consolas,monospace;font-size:.88em;word-break:break-all}
.empty{background:#eafaf1;border:1px solid #a9dfbf;border-radius:8px;
       padding:12px 16px;color:#1e8449;font-weight:bold}
"""


def _e(s):
    return _html.escape(str(s))


def render(findings, stats, details, sources):
    now = time.strftime('%Y-%m-%d %H:%M')
    p = []
    p.append(f'<meta charset="utf-8"><title>문항 검수 보고서</title><style>{CSS}</style>')
    p.append('<h1>수학 문항 검수 보고서</h1>')
    p.append(f'<p class="muted">{_e(" · ".join(sources))}<br>생성 {now} · '
             'hwpx-math-check (정답↔해설 SymPy 검산 + 조판 결함 + 쌍둥이 교차)</p>')

    # 결함 후보
    p.append(f'<h2>결함 후보 — {len(findings)}건</h2>')
    if not findings:
        p.append('<div class="empty">결함 후보 없음 — 기계 판정 기준 통과</div>')
    else:
        p.append('<table><tr><th>심각도</th><th>문항</th><th>유형</th><th>내용</th></tr>')
        for f in findings:
            sev = f.get('sev', '')
            desc = CODE_DESC.get(f['code'], f['code'])
            extra = ' / '.join(x for x in (
                str(f.get('want', '')), str(f.get('tail', ''))) if x)
            found = f.get('found_in')
            if found:
                extra += f' (관련 보기: {found})'
            p.append(
                f'<tr><td class="sev" style="color:{SEV_COLOR.get(sev, "#333")}">'
                f'{SEV_KO.get(sev, sev)}</td>'
                f'<td class="loclist">{_e(f.get("loc", ""))}<br>'
                f'<span class="muted">#{f.get("no", "")} 정답 {f.get("ans", "")}</span></td>'
                f'<td>{_e(f["code"])}</td>'
                f'<td>{_e(desc)}<br><span class="muted">{_e(extra[:160])}</span></td></tr>')
        p.append('</table>')

    # 검산 요약 카드
    tot = {'정답유일증명': 0, '정답일치': 0, '판정불가': 0, '결론없음': 0}
    todo = []
    for src, d in details.items():
        for k in tot:
            tot[k] += len(d.get(k, []))
        todo += d.get('판정불가', []) + d.get('결론없음', [])
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

    # 사람이 볼 목록
    if todo:
        p.append(f'<h2>사람이 정독할 문항 — {len(todo)}건</h2>'
                 '<p class="muted">결론 수식이 없거나 기계가 판정하지 못한 문항. '
                 '결함이라는 뜻이 아니라 자동 검증이 안 됐다는 뜻이다.</p>')
        p.append(f'<p class="loclist">{_e(", ".join(todo))}</p>')

    # 쌍둥이 통계
    tw = stats.get('쌍둥이')
    if tw:
        p.append('<h2>쌍둥이문항 교차</h2>'
                 f'<p>쌍 성립 {tw.get("쌍성립", 0)} · 1:N 참조 {tw.get("1:N참조", 0)} · '
                 f'정답 번호 상이 {tw.get("정답상이", 0)}(정상 — 쌍둥이는 숫자 변형 문항)</p>')

    p.append('<p class="muted">이 보고서는 1차 기계 검수 결과다. 풀이 과정 자체의 오류, '
             '그림, 문장 표현은 검사 범위 밖이며 최종 판단은 사람이 한다.</p>')
    return '\n'.join(p)
