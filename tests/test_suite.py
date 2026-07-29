#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_suite.py — 코드 기반 검증 스위트.

1) 합성 문항: 결함을 일부러 심은 문항은 잡히고, 멀쩡한 문항은 오탐 없어야 함
2) 실데이터 회귀: 211문항 검수 결과가 알려진 수치와 정확히 일치해야 함
3) 보고서 렌더러: 강조·수정 제안 생성, HTML 이스케이프(XSS 방지)

  python tests/test_suite.py            # data/ 가 있으면 회귀까지, 없으면 합성만
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'scripts'))

import sympy
import hml2sympy
import eq_answer_check as eqc
import twin_check
import report_html

PASS, FAIL = [], []


def check(name, cond, msg=''):
    (PASS if cond else FAIL).append(name)
    if not cond:
        print(f'  FAIL {name}  {msg}')


def item(no, opts, ans, expl, loc=None, meta=None):
    m = {'문항id': loc or f'TG0C1S0Aa1-{no:02d}', '지식단위': 'G0C1S0A',
         '난이도': '1', '학습행동영역': 'T', '쌍둥이문항': ''}
    m.update(meta or {})
    return {'no': no, 'q': '본문 $x$', 'opts': opts, 'answer': ans,
            'answer_raw': str(ans), 'expl': expl, 'loc': m['문항id'], 'meta': m}


# ── 1. hml2sympy ──────────────────────────────────────────────

def t_transpile():
    st, fl = hml2sympy.transpile('4- sqrt {2}')
    check('hml.기본', sympy.simplify(st[0]['exprs'][0] - (4 - sympy.sqrt(2))) == 0)
    st, fl = hml2sympy.transpile('rm F(4,``0)')
    check('hml.좌표', st and not fl, '좌표가 파싱 실패')
    st, fl = hml2sympy.transpile('3:2')
    check('hml.비율', sympy.simplify(st[0]['exprs'][0] - sympy.Rational(3, 2)) == 0)
    st, fl = hml2sympy.transpile('k<')
    check('hml.고아플래그', 'trailing_op' in fl)
    st, fl = hml2sympy.transpile('x = 3 +- sqrt {2}')
    check('hml.PM심볼', 'pm' in fl and any(
        'PM_' in str(e) for s in st for e in s['exprs']))
    st, fl = hml2sympy.transpile('b^{2} & =c^{2}-a^{2}# & =5^{2}-9# & =16')
    check('hml.여러줄', len(st) == 3 and st[-1]['exprs'][-1] == 16)


# ── 2. eq_answer_check 합성 문항 ──────────────────────────────

def run_eq(items):
    f, s, d = eqc.check(items)
    return f, dict(s), d


def t_eq_ok_value():
    """정답 보기 = 해설 결론 (표기만 다름) → 결함 0, 유일증명"""
    it = item(1, ['$1$', '$2$', '$4- sqrt {2}$', '$3$', '$5$'], 3,
              '풀이 과정\n따라서 $k=- sqrt {2} +4$')
    f, s, d = run_eq([it])
    check('eq.동치오탐없음', not f, str(f))
    check('eq.유일증명', it['loc'] in d['정답유일증명'])


def t_eq_wrong_answer():
    """해설 결론이 3번 보기인데 정답 표기는 1번 → ANS_IN_OTHER"""
    it = item(2, ['$1$', '$2$', '$4- sqrt {2}$', '$3$', '$5$'], 1,
              '풀이 과정\n따라서 $k=- sqrt {2} +4$')
    f, s, d = run_eq([it])
    check('eq.정답오기검출', any(x['code'] == 'ANS_IN_OTHER' and x['found_in'] == [3]
                           for x in f), str(f))


def t_eq_range():
    """범위형 결론 0<k<2 + 제약 k≠3"""
    opts = ['$0$', '$1$', '$3$', '$5$', '$6$']
    expl = '$k>0$, $k != 3$\n따라서 $0<k<2$'
    f, s, d = run_eq([item(3, opts, 2, expl)])
    check('eq.범위정답', not f and s.get('정답유일증명') == 1, f'{f} {s}')
    f, s, d = run_eq([item(4, opts, 3, expl)])
    check('eq.범위오답검출', any(x['code'] in ('ANS_RANGE_OUT', 'ANS_IN_OTHER')
                           and x['found_in'] == [2] for x in f), str(f))


def t_eq_dup():
    """보기 $1$과 $2-1$은 수학적으로 같음 → OPT_DUP_EQ"""
    it = item(5, ['$1$', '$2- 1$', '$3$', '$4$', '$5$'], 3, '따라서 $3$')
    f, s, d = run_eq([it])
    check('eq.중복검출', any(x['code'] == 'OPT_DUP_EQ' and x['found_in'] == [1, 2]
                        for x in f), str(f))


def t_eq_equation_options():
    """방정식형 보기 5개(전부 다름) → 중복 오탐 없어야 하고 정답 유일 증명"""
    opts = ['${x^{2}} over {3} - {y^{2}} over {9} =1$',
            '${x^{2}} over {3} - {y^{2}} over {3} =1$',
            '${x^{2}} over {9} - {y^{2}} over {3} =1$',
            '$x^{2} - {y^{2}} over {3} =1$',
            '${x^{2}} over {3} -y^{2} =1$']
    it = item(6, opts, 1, '따라서 구하는 방정식은 ${x^{2}} over {3} - {y^{2}} over {9} =1$')
    f, s, d = run_eq([it])
    check('eq.방정식중복오탐없음', not any(x['code'] == 'OPT_DUP_EQ' for x in f), str(f))
    check('eq.방정식유일증명', s.get('정답유일증명') == 1, str(s))


def t_eq_orphan_unbalanced():
    it = item(7, ['$k<$$-3$', '$2$', '$3$', '$4$', '$5$'], 2, '따라서 $2$')
    f, s, d = run_eq([it])
    check('eq.고아검출', any(x['code'] == 'EQ_ORPHAN_OP' and '보기1' in x['want']
                        for x in f), str(f))
    it = item(8, ['$1$', '$2$', '$3$', '$4$', '$5$'], 1, '따라서 $sqrt {2$ 이다')
    f, s, d = run_eq([it])
    check('eq.괄호검출', any(x['code'] == 'EQ_UNBALANCED' for x in f), str(f))


def t_eq_pm():
    """± 결론: 두 부호 보기 모두 일치로 인정, 결함 아님"""
    it = item(9, ['$3+ sqrt {2}$', '$3- sqrt {2}$', '$1$', '$4$', '$5$'], 1,
              '따라서 $x = 3 +- sqrt {2}$')
    f, s, d = run_eq([it])
    check('eq.PM판정', not any(x['code'].startswith('ANS_') for x in f)
          and s.get('정답일치') == 1, f'{f} {s}')


# ── 3. twin_check 합성 ────────────────────────────────────────

def t_twin():
    def ev(no, twin, **meta):
        return item(no, ['$1$'] * 5, 1, '따라서 $1$',
                    loc=f'UG0C1S0Aa1-{no:02d}',
                    meta={'쌍둥이문항': twin, **meta})

    def gn(no, loc):
        return item(no, ['$1$'] * 5, 2, '따라서 $2$', loc=loc)

    g = [gn(1, 'GG0C1S0Aa1-01'), gn(2, 'GG0C1S0Aa1-02'),
         gn(3, 'GG0C1S0Aa1-03'), gn(4, 'GG9Z9S9Zz9-01')]
    e = [ev(1, 'GG0C1S0Aa1-01'),                     # 정상 (정답 달라도 무관)
         ev(2, 'GG0C1S0Aa1-99'),                     # 깨진 참조
         ev(3, ''),                                  # 누락
         ev(4, 'GG0C1S0Aa1-02', 난이도='9'),          # 메타 불일치
         ev(5, 'GG9Z9S9Zz9-01')]                     # 실존하지만 몸통 불일치
    # 참조 안 된 일반 문항: GG0C1S0Aa1-03 → TWIN_UNREF 1건
    f, s = twin_check.check(e, g)
    codes = sorted(x['code'] for x in f)
    check('twin.검출세트', codes == sorted(
        ['TWIN_BROKEN_REF', 'TWIN_MISSING', 'TWIN_META_DIFF',
         'TWIN_ID_PATTERN', 'TWIN_UNREF']), str(codes))
    check('twin.정답상이는결함아님', not any('정답' in x['code'] for x in f))


# ── 4. report_html ────────────────────────────────────────────

def t_report():
    check('rp.수식표기', report_html.pretty_eq('{x ^{2}} over {16}') == '(x ²)/(16)',
          report_html.pretty_eq('{x ^{2}} over {16}'))
    check('rp.루트', '√' in report_html.pretty_eq('4- sqrt {2}'))
    check('rp.기호', report_html.pretty_eq('a +- b <= c') == 'a ± b ≤ c',
          report_html.pretty_eq('a +- b <= c'))

    it = item(1, ['$k<$$-3$', '<script>alert(1)</script>', '$3$', '$4$', '$5$'],
              3, '따라서 $3$')
    f, s, d = run_eq([it])
    html = report_html.render(f, {}, {'t': d}, ['t'], items={it['loc']: it})
    check('rp.강조', '<mark>' in html and '수정 제안' in html)
    check('rp.XSS이스케이프', '<script>alert' not in html)
    html2 = report_html.render([], {}, {}, ['t'])   # 문항 정보 없이도 동작
    check('rp.빈보고서', '결함 후보 없음' in html2)


# ── 5. hwpx 쪽 계산 (합성 hwpx) ───────────────────────────────

def _mini_tbl(item_id):
    def row(k, v):
        return (f'<tr><tc><p><run><t>{k}</t></run></p></tc>'
                f'<tc><p><run><t>{v}</t></run></p></tc></tr>')
    return ('<tbl>' + row('문항id', item_id) + row('정답', '1')
            + row('선택지1', '1') + '</tbl>')


def t_pages():
    import io
    import json as _j
    import tempfile
    import zipfile
    import hwpx_items
    # 문단 vertpos: 0 → 5000 (1쪽, 표A) → 0 리셋 (2쪽, 표B) → 400
    sec = ('<sec>'
           '<p><linesegarray><lineseg vertpos="0"/></linesegarray></p>'
           '<p><linesegarray><lineseg vertpos="5000"/></linesegarray>'
           f'<run>{_mini_tbl("TG0C1S0Aa1-01")}</run></p>'
           '<p><linesegarray><lineseg vertpos="0"/></linesegarray>'
           f'<run>{_mini_tbl("TG0C1S0Aa1-02")}</run></p>'
           '<p><linesegarray><lineseg vertpos="400"/></linesegarray></p>'
           '</sec>')
    tmp = tempfile.NamedTemporaryFile(suffix='.hwpx', delete=False)
    with zipfile.ZipFile(tmp, 'w') as z:
        z.writestr('Contents/section0.xml', sec)
    tmp.close()
    recs, skipped = hwpx_items.parse(tmp.name)
    data = hwpx_items.to_items_json(recs, 't')
    pages = [i['page'] for i in data['items']]
    check('pg.쪽계산', pages == [1, 2], str(pages))
    html = report_html.render(
        [{'code': 'EQ_UNBALANCED', 'sev': 'high', 'no': 1,
          'loc': 'TG0C1S0Aa1-02', 'ans': 1, 'found_in': [], 'want': 'x{', 'tail': ''}],
        {}, {}, ['t'], items={i['loc']: i for i in data['items']})
    check('pg.보고서표시', '2쪽' in html)
    os.unlink(tmp.name)


# ── 6. 실데이터 회귀 (data/ 있을 때만) ────────────────────────

def t_regression():
    import json
    import math_review
    d1 = os.path.join(HERE, '..', 'data', '평가문항_items.json')
    d2 = os.path.join(HERE, '..', 'data', '일반문항_items.json')
    if not (os.path.exists(d1) and os.path.exists(d2)):
        print('  (data/ 없음 — 회귀 검증 생략)')
        return
    findings, stats, details, items = math_review.run([d1, d2])
    check('rg.결함수', len(findings) == 2 and
          all(x['code'] == 'EQ_ORPHAN_OP' for x in findings),
          f'{len(findings)} {[x["code"] for x in findings]}')
    check('rg.결함위치', sorted(x['loc'] for x in findings) ==
          ['UG0C1S3Da1-02', 'UG0C1S3Da3-02'])
    tot = lambda k: sum(len(v.get(k, [])) for v in details.values())
    check('rg.유일증명139', tot('정답유일증명') == 139, tot('정답유일증명'))
    check('rg.일치56', tot('정답일치') == 56, tot('정답일치'))
    check('rg.판정불가11', tot('판정불가') == 11, tot('판정불가'))
    check('rg.문항맵211', len(items) == 211, len(items))
    check('rg.쌍둥이', stats['쌍둥이']['쌍성립'] == 107)


if __name__ == '__main__':
    for t in (t_transpile, t_eq_ok_value, t_eq_wrong_answer, t_eq_range,
              t_eq_dup, t_eq_equation_options, t_eq_orphan_unbalanced,
              t_eq_pm, t_twin, t_report, t_pages, t_regression):
        print(t.__name__)
        try:
            t()
        except Exception as e:
            import traceback
            FAIL.append(t.__name__ + ':예외')
            print('  EXC', traceback.format_exc().splitlines()[-1])
    print(f'\n결과: 통과 {len(PASS)} / 실패 {len(FAIL)}')
    if FAIL:
        print('실패 목록:', FAIL)
    sys.exit(1 if FAIL else 0)
