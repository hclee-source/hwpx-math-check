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
           '<p><linesegarray><lineseg vertpos="0"/></linesegarray>'
           '<run><t>쎈 9쪽 12번</t></run></p>'
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
    check('pg.출처수집', [i.get('src_cite') for i in data['items']] ==
          ['쎈 9쪽 12번', ''], str([i.get('src_cite') for i in data['items']]))
    html = report_html.render(
        [{'code': 'EQ_UNBALANCED', 'sev': 'high', 'no': 1,
          'loc': 'TG0C1S0Aa1-02', 'ans': 1, 'found_in': [], 'want': 'x{', 'tail': ''}],
        {}, {}, ['t'], items={i['loc']: i for i in data['items']})
    check('pg.보고서표시', '2쪽' in html)
    os.unlink(tmp.name)


# ── 5.5 extra_checks 합성 검증 ────────────────────────────────

def t_extra():
    import extra_checks
    its = [
        item(1, ['$1$', '$2$', '$3$', '$4$', '$5$'], 1,
             '풀이 (그림 수정)\n따라서 $1$', loc='XG0C1S0Aa1-01',
             meta={'지식단위': 'G0C1S0A', '난이도': '1'}),
        item(2, ['$root5$', '$2 $', '$3$', '$4$', '$5$'], 2,
             '← 이거 참고해서 그림 발주\n따라서 $2$', loc='XG0C1S0Aa1-02',
             meta={'지식단위': 'G0C1S0A', '난이도': '1'}),
        item(3, ['$1$', '$2$', '$3$', '$4$', '$5$'], 3,
             '$(x _{1,} y _{1})$ 이용\n따라서 $3$', loc='XG0C1S0Aa9-01',
             meta={'지식단위': 'G0C1S0A', '난이도': '1'}),   # 난이도 9≠1 위반
    ]
    # 중복 후보: 1·2번 본문을 같게
    its[0]['q'] = its[1]['q'] = '포물선 $y^{2} = 4x$ 의 초점을 지나는 직선이 어쩌고 하는 본문'
    ex = extra_checks.analyze({'items': its})
    check('ex.메모2건', len(ex['memos']) == 2, str(ex['memos']))
    check('ex.root검출', 'root 표기' in ex['style'], str(ex['style'].keys()))
    check('ex.첨자쉼표', '첨자 안 쉼표' in ex['style'])
    check('ex.끝공백', '수식 끝 여분 공백' in ex['style'])
    check('ex.중복쌍', len(ex['dups']) == 1 and ex['dups'][0]['ratio'] > .95,
          str(ex['dups']))
    check('ex.난이도위반', any(x['code'] == 'META_MISMATCH' and '난이도' in x['tail']
                          for x in ex['findings']), str(ex['findings']))

    # 오탈자·출처 표기·완전 중복
    t = [item(1, ['$1$'] * 5, 1, '수선이 발을 내리면 $2$개다. 커야한다',
              loc='YG0C1S0Aa1-01'),
         item(2, ['$1$'] * 5, 1, '정상 해설이다.', loc='YG0C1S0Aa1-02')]
    t[0]['src_cite'] = '쏀 21쪽 99번'
    t[1]['src_cite'] = '쎈 22쪽 10번'
    # 본문·보기·정답 동일 → 완전 중복 (유사도 판정은 본문 20자 이상일 때만)
    t[0]['q'] = t[1]['q'] = '타원 $x^{2}+2y^{2}=8$ 의 두 초점 사이의 거리를 구하는 본문이다'
    ex2 = extra_checks.analyze({'items': t})
    fixes = {x['fix'] for x in ex2['typos']}
    check('ex.오탈자3종', {'수선의 발', '개이다'} <= fixes and
          any('커야' in f for f in fixes), str(fixes))
    check('ex.출처혼용', ex2['citations'] and ex2['citations'][0]['minor'] == '쏀',
          str(ex2['citations']))
    check('ex.완전중복', any(x['code'] == 'ITEM_DUP_EXACT' for x in ex2['findings']),
          str([x['code'] for x in ex2['findings']]))

    # 표기 검사 정밀도: LEFT{ 는 구분자라 오탐 금지, != 는 줄 단위로 잡아야 함
    t3 = [item(1, ['$1$'] * 5, 1,
               '$4 LEFT { (x-3) ^{2} RIGHT } =9$\n'
               '(ⅱ) $a != 0$, $b!=0$일 때\n따라서 $1$', loc='ZG0C1S0Aa1-01')]
    ex3 = extra_checks.analyze({'items': t3})
    check('ex.LEFT중괄호오탐없음', '중괄호 안 여분 공백' not in ex3['style'],
          str(ex3['style'].keys()))
    check('ex.연산자공백줄단위', '비교 연산자 공백 불일치' in ex3['style'],
          str(ex3['style'].keys()))


# ── 5.7 hwpx_fix 왕복 검증 (결함 심은 hwpx → 교정 → 재검사) ───

def _eq_xml(script, w=1656):
    """수식 개체 하나. script의 <,& 는 XML 이스케이프해야 한다."""
    esc = script.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return (f'<equation><sz width="{w}" widthRelTo="ABSOLUTE" height="1125" '
            f'heightRelTo="ABSOLUTE"/><script>{esc}</script></equation>')


def t_fix():
    """교정기는 검사기가 잡은 것만 고치고, 나머지는 한 글자도 건드리지 않아야 한다."""
    import json as _j
    import tempfile
    import zipfile
    import extra_checks
    import eq_answer_check
    import hwpx_fix
    import hwpx_items

    def row(k, v):
        return (f'<tr><tc><p><run><t>{k}</t></run></p></tc>'
                f'<tc><p><run>{v}</run></p></tc></tr>')

    tbl = ('<tbl>'
           + row('문항id', '<t>FG0C1S0Aa1-01</t>')
           + row('본문', '<t>점 $</t>' + _eq_xml('r^2') + '<t>$ 에서 내린 수선이 발</t>')
           # 쪼개진 수식: 연산자로 끝난 수식 + 인접 수식
           + row('선택지1', _eq_xml('k<') + _eq_xml('-3', w=1504))
           + row('선택지2', _eq_xml('{ 1} over { 2}'))
           + row('선택지3', _eq_xml('k<{-4}'))
           + row('선택지4', _eq_xml('root5'))
           + row('선택지5', _eq_xml('21`'))
           + row('정답', '<t>2</t>')
           + row('해설1', _eq_xml('(x _{1,} ``y _{1} )')
                 + '<t> 이므로 답은 </t>' + _eq_xml('{ 1} over { 2}')
                 + '<t> 개다. 이 값은 커야한다</t>')
           + row('지식단위', '<t>G0C1S0A</t>')
           + row('난이도', '<t>1</t>')
           + row('학습행동영역', '<t>F</t>')
           + row('쌍둥이문항', '<t></t>')
           + '</tbl>')
    # 출처 표기는 표 바로 앞 문단 — 소수파 '쏀' 1건 + 다수파 '쎈' 3건
    sec = ('<sec>'
           + ''.join(f'<p><run><t>쎈 {n}쪽 {n}번</t></run></p>'
                     f'<p><run>{tbl.replace("FG0C1S0Aa1-01", f"FG0C1S0Aa1-1{n}")}'
                     f'</run></p>' for n in (1, 2, 3))
           + '<p><run><t>쏀 9쪽 12번</t></run></p>'
           + f'<p><run>{tbl}</run></p>'
           + '</sec>')

    tmp = tempfile.NamedTemporaryFile(suffix='.hwpx', delete=False)
    with zipfile.ZipFile(tmp, 'w') as z:
        z.writestr('mimetype', 'application/hwp+zip')
        z.writestr('Contents/section0.xml',
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>' + sec)
    tmp.close()

    # 교정 전: 심은 결함이 실제로 검출되는가 (검출 안 되면 이 테스트는 무의미)
    d0 = hwpx_items.to_items_json(hwpx_items.parse(tmp.name)[0], 't')
    ex0 = extra_checks.analyze(d0)
    f0, _, _ = eq_answer_check.check(d0['items'])
    check('fx.사전.오탈자', len(ex0['typos']) >= 2, str(ex0['typos']))
    check('fx.사전.출처혼용', ex0['citations'] and ex0['citations'][0]['minor'] == '쏀')
    check('fx.사전.고아연산자', any(x['code'] == 'EQ_ORPHAN_OP' for x in f0),
          str([x['code'] for x in f0]))
    for name in ('중괄호 안 여분 공백', '첨자 안 쉼표', 'root 표기',
                 '수식 끝 여분 공백', '비교식 불필요 중괄호', '위첨자 민형식 a^2'):
        check(f'fx.사전.{name}', name in ex0['style'], str(list(ex0['style'])))

    out_raws, changes, manual, _, _ = hwpx_fix.fix(tmp.name)
    dst = tmp.name.replace('.hwpx', '_교정.hwpx')
    hwpx_fix.write_hwpx(tmp.name, dst, out_raws)

    # 교정 후: 결함이 사라졌는가
    d1 = hwpx_items.to_items_json(hwpx_items.parse(dst)[0], 't')
    ex1 = extra_checks.analyze(d1)
    f1, _, _ = eq_answer_check.check(d1['items'])
    check('fx.후.오탈자0', ex1['typos'] == [], str(ex1['typos']))
    check('fx.후.출처혼용0', ex1['citations'] == [], str(ex1['citations']))
    check('fx.후.표기0', ex1['style'] == {}, str(list(ex1['style'])))
    check('fx.후.고아연산자0', not any(x['code'] == 'EQ_ORPHAN_OP' for x in f1),
          str([x['code'] for x in f1]))

    # 구조·내용 보존
    check('fx.문항수유지', len(d0['items']) == len(d1['items']) == 4,
          f"{len(d0['items'])}→{len(d1['items'])}")
    check('fx.정답유지', [i['answer'] for i in d1['items']] == [2] * 4,
          str([i['answer'] for i in d1['items']]))
    check('fx.메타유지', [i['meta'] for i in d0['items']] ==
          [i['meta'] for i in d1['items']])
    it = d1['items'][-1]
    check('fx.수식병합', '$k<-3$' in it['opts'][0], repr(it['opts'][0]))
    check('fx.한글텍스트교정', '수선의 발' in it['q'] and '개이다' in it['expl']
          and '커야 한다' in it['expl'], repr(it['q']) + repr(it['expl'][:80]))
    check('fx.보기값보존', it['opts'][4] == '$21$', repr(it['opts'][4]))
    check('fx.변경로그있음', len(changes) > 10 and
          all({'loc', 'field', 'kind', 'before', 'after'} <= set(c) for c in changes),
          str(len(changes)))

    # 병합된 수식은 두 조각의 폭 합을 물려받아야 한다 (조판 폭 보존)
    from lxml import etree
    with zipfile.ZipFile(dst) as zf:
        root = etree.fromstring(zf.read('Contents/section0.xml'))
        szs = [e for e in root.iter() if etree.QName(e).localname == 'sz'
               and e.get('width') == '3160']
        check('fx.병합폭합산', len(szs) == 4, f'{len(szs)}건 (문항 4개 × 1)')

        # zip 구조: mimetype 첫 항목·무압축이어야 한글이 읽는다
        first = zf.infolist()[0]
        check('fx.mimetype선두', first.filename == 'mimetype' and
              first.compress_type == 0, first.filename)
        check('fx.crc정상', zf.testzip() is None)

    # 사람 판단 대상은 손대지 않는다
    check('fx.보류분류', all(m['code'] in hwpx_fix.MANUAL or
                          m['code'] in ('EDIT_MEMO', 'ITEM_DUP_NEAR')
                          for m in manual), str([m['code'] for m in manual]))

    os.unlink(tmp.name)
    os.unlink(dst)


# ── 6. 실데이터 회귀 (data/ 있을 때만) ────────────────────────

def t_regression():
    import json
    import math_review
    d1 = os.path.join(HERE, '..', 'data', '평가문항_items.json')
    d2 = os.path.join(HERE, '..', 'data', '일반문항_items.json')
    if not (os.path.exists(d1) and os.path.exists(d2)):
        print('  (data/ 없음 — 회귀 검증 생략)')
        return
    findings, stats, details, items, extras = math_review.run([d1, d2])
    ex_gn = [v for k, v in extras.items() if '일반' in k][0]
    check('rg.편집메모', len(ex_gn['memos']) >= 15, len(ex_gn['memos']))
    check('rg.첨자쉼표8', ex_gn['style'].get('첨자 안 쉼표', {}).get('n') == 8,
          str(ex_gn['style'].get('첨자 안 쉼표')))
    check('rg.중복후보', len(ex_gn['dups']) >= 3, len(ex_gn['dups']))
    check('rg.카이제곱', ex_gn['stats']['chi2'] == 9.85 and ex_gn['stats']['skewed'],
          str(ex_gn['stats']['chi2']))
    check('rg.노출편향과다아님', ex_gn['stats']['longest_n'] <= 8,
          str(ex_gn['stats']['longest_n']))
    check('rg.메타정합통과', len(ex_gn['passed']) == 7, str(ex_gn['passed']))
    orphan = [x for x in findings if x['code'] == 'EQ_ORPHAN_OP']
    check('rg.고아연산자2', len(orphan) == 2 and
          sorted(x['loc'] for x in orphan) == ['UG0C1S3Da1-02', 'UG0C1S3Da3-02'],
          str([x['loc'] for x in orphan]))
    # 평가 3쌍(U/S/C 세트 복사) — 일반 파일엔 없음
    exact = sorted(x['loc'] for x in findings if x['code'] == 'ITEM_DUP_EXACT')
    check('rg.완전중복3쌍', exact == ['SG0C1S4Db3-01', 'UG0C1S3Ab3-01',
                                 'UG0C1S3Cb3-01'], str(exact))
    tot = lambda k: sum(len(v.get(k, [])) for v in details.values())
    check('rg.유일증명139', tot('정답유일증명') == 139, tot('정답유일증명'))
    check('rg.일치56', tot('정답일치') == 56, tot('정답일치'))
    check('rg.판정불가11', tot('판정불가') == 11, tot('판정불가'))
    check('rg.문항맵211', len(items) == 211, len(items))
    check('rg.쌍둥이', stats['쌍둥이']['쌍성립'] == 107)


if __name__ == '__main__':
    for t in (t_transpile, t_eq_ok_value, t_eq_wrong_answer, t_eq_range,
              t_eq_dup, t_eq_equation_options, t_eq_orphan_unbalanced,
              t_eq_pm, t_twin, t_report, t_pages, t_extra, t_fix,
              t_regression):
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
