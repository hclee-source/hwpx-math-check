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

import base64

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


# ── 5.75 hwpx_images — BMP→PNG 변환 (Claude vision은 BMP를 안 받는다) ──

def t_images():
    """변환기의 세 함정: 행 4바이트 패딩, bottom-up 저장, BGR 픽셀 순서."""
    import struct
    import zlib
    import hwpx_images as hi

    def make_bmp(w, h, rgb_rows, bottom_up=True, bpp=24, comp=0):
        """rgb_rows: 위→아래 순서의 [(r,g,b), ...] 행 리스트."""
        stride = (w * 3 + 3) & ~3
        rows = list(rgb_rows)
        if bottom_up:
            rows = rows[::-1]
        px = b''
        for row in rows:
            line = b''.join(bytes((b, g, r)) for r, g, b in row)  # BGR
            px += line + b'\x00' * (stride - len(line))           # 패딩
        info = struct.pack('<IiiHHIIiiII', 40, w, h if bottom_up else -h,
                           1, bpp, comp, len(px), 0, 0, 0, 0)
        return (b'BM' + struct.pack('<IHHI', 14 + 40 + len(px), 0, 0, 54)
                + info + px)

    def png_pixels(data):
        """PNG(필터0, 8bit truecolor) → 위→아래 [(r,g,b), ...] 행 리스트."""
        assert data[:8] == b'\x89PNG\r\n\x1a\n'
        pos, w, h, idat = 8, None, None, b''
        while pos < len(data):
            n = struct.unpack('>I', data[pos:pos + 4])[0]
            tag = data[pos + 4:pos + 8]
            body = data[pos + 8:pos + 8 + n]
            if tag == b'IHDR':
                w, h, depth, ctype = struct.unpack('>IIBB', body[:10])
                assert (depth, ctype) == (8, 2), (depth, ctype)
            elif tag == b'IDAT':
                idat += body
            pos += 12 + n
        raw = zlib.decompress(idat)
        out, stride = [], w * 3
        for y in range(h):
            s = y * (stride + 1)
            assert raw[s] == 0, '필터 0이 아니다'
            line = raw[s + 1:s + 1 + stride]
            out.append([tuple(line[i:i + 3]) for i in range(0, stride, 3)])
        return out

    # 3x2, 색이 전부 다르고 폭이 4의 배수가 아니라 패딩이 생긴다
    src = [[(255, 0, 0), (0, 255, 0), (0, 0, 255)],
           [(1, 2, 3), (250, 251, 252), (10, 20, 30)]]
    got = png_pixels(hi.bmp_to_png(make_bmp(3, 2, src)))
    check('img.bottomup복원', got == src, f'{got} != {src}')
    # top-down BMP(높이 음수)도 같은 결과가 나와야 한다
    got2 = png_pixels(hi.bmp_to_png(make_bmp(3, 2, src, bottom_up=False)))
    check('img.topdown복원', got2 == src, str(got2))
    # 1px 폭 — 패딩이 3바이트 붙는 최악의 경우
    one = [[(7, 8, 9)], [(200, 100, 50)]]
    check('img.1px폭', png_pixels(hi.bmp_to_png(make_bmp(1, 2, one))) == one)

    # 미지원 변종은 조용히 죽지 말고 ValueError로 알려야 한다
    for label, kw in (('8bpp', {'bpp': 8}), ('압축', {'comp': 1})):
        try:
            hi.bmp_to_png(make_bmp(3, 2, src, **kw))
            check(f'img.거부.{label}', False, '예외가 안 났다')
        except ValueError:
            check(f'img.거부.{label}', True)
    try:
        hi.bmp_to_png(b'GIF89a' + b'\x00' * 100)
        check('img.거부.BMP아님', False, '예외가 안 났다')
    except ValueError:
        check('img.거부.BMP아님', True)
    try:
        hi.bmp_to_png(make_bmp(3, 2, src)[:40])       # 데이터 잘림
        check('img.거부.잘림', False, '예외가 안 났다')
    except ValueError:
        check('img.거부.잘림', True)

    # load(): 매니페스트 → 변환. 깨진 그림 하나가 전체를 죽이지 않아야 한다
    import tempfile
    import zipfile
    hpf = ('<opf:package><opf:manifest>'
           '<opf:item id="image1" href="BinData/image1.bmp" media-type="image/bmp"/>'
           '<opf:item id="image2" href="BinData/image2.bmp" media-type="image/bmp"/>'
           '<opf:item id="image3" href="BinData/image3.png" media-type="image/png"/>'
           '<opf:item id="image4" href="BinData/missing.bmp" media-type="image/bmp"/>'
           '<opf:item id="style" href="styles.css" media-type="text/css"/>'
           '</opf:manifest></opf:package>')
    tmp = tempfile.NamedTemporaryFile(suffix='.hwpx', delete=False)
    with zipfile.ZipFile(tmp, 'w') as z:
        z.writestr('Contents/content.hpf', hpf)
        z.writestr('BinData/image1.bmp', make_bmp(3, 2, src))
        z.writestr('BinData/image2.bmp', b'not a bmp at all')      # 깨진 그림
        z.writestr('BinData/image3.png', b'\x89PNG\r\n\x1a\nzzz')  # 그대로 통과
        z.writestr('styles.css', 'body{}')
    tmp.close()
    got = hi.load(tmp.name)
    check('img.load.변환2건', sorted(got) == ['image1', 'image3'], str(sorted(got)))
    check('img.load.BMP는PNG로', got['image1'][0] == 'image/png'
          and got['image1'][1][:8] == b'\x89PNG\r\n\x1a\n')
    check('img.load.PNG는그대로', got['image3'] == ('image/png',
                                                b'\x89PNG\r\n\x1a\nzzz'))
    check('img.load.CSS무시', 'style' not in got)
    os.unlink(tmp.name)

    # 파서가 `[그림 N]` 표시와 그림 id를 문항 단위로 이어 붙이는가
    import hwpx_items
    pic = ('<run><equation><script>x</script></equation></run>'
           '<run><pic><img binaryItemIDRef="imgA"/></pic></run>')
    def row(k, v):
        return (f'<tr><tc><p><run><t>{k}</t></run></p></tc>'
                f'<tc><p>{v}</p></tc></tr>')
    sec = ('<sec><p><run><tbl>'
           + row('문항id', '<run><t>IG0C1S0Aa1-01</t></run>')
           + row('본문', f'<run><t>본문</t></run>{pic}')
           + row('정답', '<run><t>1</t></run>')
           + row('선택지1', '<run><t>1</t></run>')
           + row('해설1', '<run><t>해설</t></run><run><pic>'
                          '<img binaryItemIDRef="imgB"/></pic></run>')
           + '</tbl></run></p></sec>')
    tmp2 = tempfile.NamedTemporaryFile(suffix='.hwpx', delete=False)
    with zipfile.ZipFile(tmp2, 'w') as z:
        z.writestr('Contents/section0.xml', sec)
    tmp2.close()
    d = hwpx_items.to_items_json(hwpx_items.parse(tmp2.name)[0], 't')
    i0 = d['items'][0]
    check('img.파서.id순서', i0['images'] == ['imgA', 'imgB'], str(i0['images']))
    check('img.파서.본문표시', '[그림 1]' in i0['q'], repr(i0['q']))
    check('img.파서.해설표시', '[그림 2]' in i0['expl'], repr(i0['expl']))
    os.unlink(tmp2.name)


# ── 5.8 ai_review (API 호출 없이 — 오탐 방어 로직과 스키마만) ──

def t_ai():
    """AI 검수의 핵심은 '확신 없는 지적을 버리는 것'이다. 그걸 검증한다."""
    import ai_review as ai

    # 스키마 유효성: 구조화 출력은 모든 object에 additionalProperties:false 필요
    def walk(s):
        if s.get('type') == 'object':
            check('ai.스키마closed', s.get('additionalProperties') is False, str(s)[:80])
            for v in s.get('properties', {}).values():
                walk(v)
        if s.get('type') == 'array':
            walk(s.get('items', {}))
    walk(ai.VERDICT_SCHEMA)
    codes = ai.VERDICT_SCHEMA['properties']['findings']['items']['properties']['code']
    check('ai.코드enum일치', set(codes['enum']) == set(ai.SEV_BY_CONF),
          f"{codes['enum']} vs {list(ai.SEV_BY_CONF)}")

    # 요청 파라미터: 캐싱·구조화출력·모델
    it = item(7, ['$1$', '$2$', '$3$', '$4$', '$5$'], 2, '풀이\n따라서 $2$',
              loc='AG0C1S0Aa1-01')
    p = ai.build_params(it)
    check('ai.모델', p['model'] == 'claude-opus-5', p['model'])
    check('ai.시스템캐싱',
          p['system'][0]['cache_control'] == {'type': 'ephemeral'})
    check('ai.구조화출력',
          p['output_config']['format']['schema'] is ai.VERDICT_SCHEMA)
    check('ai.effort', p['output_config']['effort'] == 'high')
    blocks = p['messages'][0]['content']
    body = '\n'.join(b['text'] for b in blocks if b['type'] == 'text')
    check('ai.문항텍스트', 'AG0C1S0Aa1-01' in body and '[인쇄된 정답] 2번' in body)
    check('ai.XML안보냄', '<' not in body.replace('<=', ''), body[:80])
    check('ai.그림없으면블록1개', len(blocks) == 1 and blocks[0]['type'] == 'text',
          str([b['type'] for b in blocks]))

    # ── 멀티모달: 그림 첨부 ────────────────────────────────────────
    it2 = item(8, ['$1$'] * 5, 1, '해설 [그림 2] 참고', loc='AG0C1S0Aa1-08')
    it2['q'] = '본문 [그림 1] 에서'
    it2['images'] = ['image7', 'image9']
    imgs = {'image7': ('image/png', b'\x89PNG\r\n\x1a\nfake7'),
            'image9': ('image/png', b'\x89PNG\r\n\x1a\nfake9')}
    bl = ai.build_params(it2, imgs)['messages'][0]['content']
    kinds = [b['type'] for b in bl]
    check('ai.img.블록순서', kinds == ['text', 'text', 'image', 'text', 'image'],
          str(kinds))
    check('ai.img.라벨', [b['text'] for b in bl if b['type'] == 'text'][1:]
          == ['[그림 1]', '[그림 2]'],
          str([b['text'] for b in bl if b['type'] == 'text'][1:]))
    src = bl[2]['source']
    check('ai.img.base64', src['type'] == 'base64'
          and src['media_type'] == 'image/png'
          and base64.b64decode(src['data']) == imgs['image7'][1], str(src)[:90])
    # 변환 실패한 그림은 '없는 것'이라고 알려야 한다 — 상상해서 판정하면 오탐
    bl2 = ai.build_params(it2, {'image7': imgs['image7']})['messages'][0]['content']
    check('ai.img.누락고지', sum(b['type'] == 'image' for b in bl2) == 1
          and '첨부하지 못했다' in bl2[-1]['text'], str([b['type'] for b in bl2]))
    check('ai.img.그림코드', 'AI_FIGURE_MISMATCH' in ai.SEV_BY_CONF)

    # ★ 확신도 → 등급 환산: '낮음'은 결함으로 올리지 않는다 (오탐 방어의 핵심)
    def verdict(conf, code='AI_ANSWER_WRONG'):
        return {'solved': '3번', 'answer_verdict': '불일치', 'confidence': conf,
                'findings': [{'code': code, 'where': '해설', 'detail': 'x',
                              'evidence': 'y', 'fix': 'z'}]}
    check('ai.낮음버림', ai.to_findings('L', 1, 2, verdict('낮음')) == [])
    hi = ai.to_findings('L', 1, 2, verdict('높음'))
    check('ai.높음high', len(hi) == 1 and hi[0]['sev'] == 'high', str(hi))
    md = ai.to_findings('L', 1, 2, verdict('보통'))
    check('ai.보통medium', len(md) == 1 and md[0]['sev'] == 'medium', str(md))
    # 표현 지적은 확신도가 높아도 low를 넘지 않는다
    w = ai.to_findings('L', 1, 2, verdict('높음', 'AI_WORDING'))
    check('ai.표현은low', w and w[0]['sev'] == 'low', str(w))
    check('ai.근거보존', hi[0]['evidence'] == 'y' and hi[0]['solved'] == '3번')
    check('ai.스키마호환', {'code', 'sev', 'no', 'loc', 'want', 'tail'} <= set(hi[0]))

    # review(): 실패 문항은 '결함'이 아니라 '검수 못함'으로 분리돼야 한다
    its = [item(1, ['$1$'] * 5, 1, 'a', loc='AG0C1S0Aa1-01'),
           item(2, ['$1$'] * 5, 1, 'b', loc='AG0C1S0Aa1-02'),
           item(3, ['$1$'] * 5, 1, 'c', loc='AG0C1S0Aa1-03')]
    fake = {
        'AG0C1S0Aa1-01': verdict('높음'),
        'AG0C1S0Aa1-02': {'solved': '1번', 'answer_verdict': '일치',
                          'confidence': '높음', 'findings': []},
        'AG0C1S0Aa1-03': {'error': 'refusal'},
    }
    orig = ai.run_sync
    ai.run_sync = (lambda items, progress=None, images=None:
                   (fake, {'in': 1000, 'out': 2000}))
    try:
        f, res, usage = ai.review(its, sync=True)
    finally:
        ai.run_sync = orig
    check('ai.결함1건', len(f) == 1 and f[0]['loc'] == 'AG0C1S0Aa1-01', str(f))
    check('ai.실패분리', [x['loc'] for x in usage['failed']] == ['AG0C1S0Aa1-03'],
          str(usage['failed']))
    # Batch는 표준가의 50%
    check('ai.비용batch', abs(ai.cost({'in': 1_000_000, 'out': 1_000_000}, True)
                            - 15.0) < 1e-9)
    check('ai.비용sync', abs(ai.cost({'in': 1_000_000, 'out': 1_000_000}, False)
                           - 30.0) < 1e-9)

    # 보고서: AI 카드에 근거가 뜨고, HTML은 이스케이프돼야 한다 (XSS)
    evil = dict(hi[0], evidence='<img src=x onerror=alert(1)>', loc='AG0C1S0Aa1-01')
    html = report_html.render([evil], {}, {}, ['t'],
                              items={i['loc']: i for i in its})
    check('ai.보고서근거', '근거' in html and '확신도' in html)
    check('ai.보고서XSS', '<img src=x' not in html and '&lt;img' in html)
    check('ai.보고서설명', 'AI가 직접 푼 결과가 인쇄된 정답과 다름' in html)


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
              t_eq_pm, t_twin, t_report, t_pages, t_extra, t_fix, t_images, t_ai,
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
