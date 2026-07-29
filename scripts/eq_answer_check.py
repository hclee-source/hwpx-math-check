#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eq_answer_check.py — 정답 ↔ 해설 결론 검산 (SymPy 동치 판정, 토큰 0).

핵심 아이디어: 수학 객관식은 해설의 결론에 정답 값이 나온다.
  정답 번호 → 선택지[정답]의 수식 → 해설 꼬리의 결론과 **수학적으로 같은가?**

v1은 문자열 정규화 대조라 `4-√2` vs `-√2+4` 같은 오탐이 났다.
v2(현재)는 hml2sympy로 SymPy 식을 만들어 simplify(a-b)==0 으로 판정하고,
범위형 결론(`0<k<2`)은 구간 포함 검사로 정답 유일성을 확인한다.

검사 코드:
  ANS_IN_OTHER    정답 아닌 선택지가 결론과 일치 (정답 번호 오기 강력 의심)  high
  ANS_RANGE_OUT   범위형 결론에 정답 값이 안 들어가고 다른 값이 들어감       high
  OPT_DUP_EQ      선택지 두 개가 수학적으로 같은 값                          high
  EQ_ORPHAN_OP    수식이 연산자에서 쪼개짐 `$k<$$-3$` (조판 결함)            high
  EQ_UNBALANCED   수식 괄호 짝 안 맞음 (조판 사고)                           high

애매한 것은 보고하지 않고 '판정불가'로 집계만 한다 — 오탐이 세 번 나면 아무도 안 쓴다.
"""
import argparse, json
from collections import Counter

import sympy
from sympy import Eq, Ne, Lt, Le, Gt, Ge

from hml2sympy import transpile, TranspileError, EQ

REL = {'=': Eq, '!=': Ne, '<': Lt, '<=': Le, '>': Gt, '>=': Ge}
INEQ = ('<', '<=', '>', '>=')


def _tp_all(text):
    """텍스트의 $..$ 전부 transpile. 실패는 None으로."""
    out = []
    for m in EQ.findall(text or ''):
        try:
            out.append(transpile(m))
        except TranspileError:
            out.append(None)
    return out


PM = sympy.Symbol('PM_')     # hml2sympy가 ±를 이 심볼로 바꿔 둔다


def _eq(a, b):
    """simplify(a-b)==0 동치 판정. ±(PM_)는 두 부호 모두 시도. 튜플 좌표 등은 불일치."""
    if not (isinstance(a, sympy.Expr) and isinstance(b, sympy.Expr)):
        return False
    try:
        if a == b:
            return True
        d = sympy.simplify(a - b)
        if d == 0:
            return True
        if PM in d.free_symbols:
            return any(sympy.simplify(d.subs(PM, s)) == 0 for s in (1, -1))
        return False
    except Exception:
        return False


def _chain(st):
    """진술 → [(좌, op, 우)] 정규형. 부등호는 < 방향으로 통일."""
    out = []
    for a, op, b in zip(st['exprs'], st['ops'], st['exprs'][1:]):
        if op in ('>', '>='):
            a, b, op = b, a, {'>': '<', '>=': '<='}[op]
        out.append((a, op, b))
    return out


def _pair_eq(a, op, b, x, oq, y):
    """관계 하나끼리 동치 — 차이식 기반이라 `k<-3` vs `k+3<0`도 잡는다."""
    if op != oq:
        return False
    if not all(isinstance(t, sympy.Expr) for t in (a, b, x, y)):
        return False
    try:
        d1, d2 = a - b, x - y
        if _eq(d1, d2):
            return True
        return op in ('=', '!=') and _eq(d1, -d2)   # 등식은 좌우 대칭
    except Exception:
        return False


def _rel_equal(s1, s2):
    c1, c2 = _chain(s1), _chain(s2)
    if len(c1) != len(c2) or not c1:
        return False
    return all(_pair_eq(a, op, b, x, oq, y)
               for (a, op, b), (x, oq, y) in zip(c1, c2))


def _in_range(st, v):
    """범위형 결론 진술에 값 v를 대입 → True/False/None(판정 불가)."""
    syms = set().union(*[e.free_symbols for e in st['exprs']
                         if isinstance(e, sympy.Expr)]) if st['exprs'] else set()
    if len(syms) != 1 or not isinstance(v, sympy.Expr) or v.free_symbols:
        return None
    s = syms.pop()
    try:
        for a, op, b in zip(st['exprs'], st['ops'], st['exprs'][1:]):
            r = sympy.simplify(REL[op](a.subs(s, v), b.subs(s, v)))
            if r is not sympy.true:
                return False if r is sympy.false else None
        return True
    except Exception:
        return None


def _opt_repr(text):
    """선택지 → ('rel', st) | ('expr', e) | ('orphan', None) | None, flags"""
    flags, stmts = set(), []
    for tp in _tp_all(text):
        if tp is None:
            continue
        stmts += tp[0]
        flags |= tp[1]
    if 'trailing_op' in flags:
        return ('orphan', None), flags       # $k<$$-3$ 쪼개짐 — 대조 불가
    if not stmts:
        return None, flags
    st = stmts[-1]
    if not st['ops']:
        return ('expr', st['exprs'][-1]), flags
    if all(op == '=' for op in st['ops']) and isinstance(st['exprs'][0], sympy.Symbol):
        return ('expr', st['exprs'][-1]), flags   # `k=값` 꼴 — 값만 비교
    return ('rel', st), flags                     # 방정식·부등식 — 관계식 전체 비교


def _conclusions(expl, n_lines=3, cap=12):
    """해설 꼬리의 결론 후보 — 마지막 줄부터 역순으로 값/범위를 모은다."""
    lines = [l for l in (expl or '').split('\n') if l.strip()]
    cands, flags = [], set()
    for line in reversed(lines[-n_lines:]):
        for tp in reversed(_tp_all(line)):
            if tp is None:
                continue
            stmts, fl = tp
            flags |= fl
            for st in reversed(stmts):
                if any(op in INEQ or op == '!=' for op in st['ops']):
                    cands.append(('rel', st))     # 범위·제약 — 값 후보로 새면 안 됨
                elif st['ops']:                   # 전부 '=' — 값이자 방정식
                    cands.append(('expr', st['exprs'][-1]))
                    cands.append(('rel', st))
                else:
                    cands.append(('expr', st['exprs'][-1]))
                if len(cands) >= cap:
                    return cands, flags, lines
    return cands, flags, lines


def _matches(orep, cands):
    if orep is None:
        return False
    kind, val = orep
    for ckind, cval in cands:
        if kind == 'expr' and ckind == 'expr' and _eq(val, cval):
            return True
        if kind == 'rel' and ckind == 'rel' and _rel_equal(val, cval):
            return True
    return False


def unbalanced(script):
    d = 0
    for ch in script:
        if ch == '{':
            d += 1
        elif ch == '}':
            d -= 1
        if d < 0:
            return True
    return d != 0


def check(items, progress=None):
    """→ (findings, 집계 Counter, 판정별 문항id 목록 dict). progress(i, n) 콜백 선택."""
    out, stats = [], Counter()
    detail = {'정답유일증명': [], '정답일치': [], '판정불가': [], '결론없음': [], '불일치': []}
    for idx, it in enumerate(items):
        if progress and idx % 10 == 0:
            progress(idx, len(items))
        no, ans, opts = it['no'], it['answer'], it['opts']
        loc = (it.get('meta') or {}).get('문항id', '')
        if not ans or ans > len(opts):
            continue

        # 조판 결함 — 고아 연산자 / 괄호 짝
        orphan_fields = []
        o_reprs = []
        for k, o in enumerate(opts):
            r, fl = _opt_repr(o)
            o_reprs.append(r)
            if r and r[0] == 'orphan':
                orphan_fields.append(f'보기{k+1}')
        cands, cflags, lines = _conclusions(it['expl'])
        if 'trailing_op' in cflags:
            orphan_fields.append('해설')
        if orphan_fields:
            out.append({'code': 'EQ_ORPHAN_OP', 'sev': 'high', 'no': no, 'loc': loc,
                        'ans': ans, 'found_in': [], 'want': ','.join(orphan_fields),
                        'tail': '수식이 연산자에서 두 조각으로 쪼개짐'})
        for raw in EQ.findall(it['q'] + '\n' + it['expl']):
            if unbalanced(raw):
                out.append({'code': 'EQ_UNBALANCED', 'sev': 'high', 'no': no, 'loc': loc,
                            'want': raw[:60], 'ans': ans, 'found_in': [], 'tail': ''})
                break

        # 선택지끼리 수학적 중복 — 같은 종류(값/관계식)끼리 전체 비교
        def _same(r1, r2):
            if not r1 or not r2 or r1[0] != r2[0]:
                return False
            return _eq(r1[1], r2[1]) if r1[0] == 'expr' else \
                (r1[0] == 'rel' and _rel_equal(r1[1], r2[1]))
        dup = sorted({n + 1 for i in range(len(o_reprs))
                      for j in range(i + 1, len(o_reprs))
                      if _same(o_reprs[i], o_reprs[j]) for n in (i, j)})
        if dup:
            out.append({'code': 'OPT_DUP_EQ', 'sev': 'high', 'no': no, 'loc': loc,
                        'ans': ans, 'found_in': dup, 'want': f'보기 {dup} 동치', 'tail': ''})

        # 정답 ↔ 결론 동치 검산
        if not cands:
            stats['결론없음'] += 1
            detail['결론없음'].append(loc)
            continue
        expr_hits = {k + 1 for k, r in enumerate(o_reprs) if _matches(r, cands)}

        # 범위형 결론 — 모든 제약(부등식·≠)을 통과하는 값만 인정 (교집합)
        ranges = [st for kind, st in cands if kind == 'rel'
                  and any(op in INEQ or op == '!=' for op in st['ops'])]

        def _range_ok(v):
            res = [_in_range(st, v) for st in ranges]
            if any(r is False for r in res):
                return False
            return any(r is True for r in res)

        range_hits = {k + 1 for k, r in enumerate(o_reprs)
                      if ranges and r and r[0] == 'expr'
                      and isinstance(r[1], sympy.Expr) and not r[1].free_symbols
                      and _range_ok(r[1])}
        hits = sorted(expr_hits | range_hits)

        if not hits:
            stats['판정불가'] += 1
            detail['판정불가'].append(loc)
            continue
        if hits == [ans]:
            stats['정답유일증명'] += 1        # 정답만 결론과 일치 — 자동 검증 완료
            detail['정답유일증명'].append(loc)
        elif ans in hits:
            stats['정답일치'] += 1            # 다른 보기도 걸렸지만 정답 포함
            detail['정답일치'].append(loc)
        else:
            others = sorted(set(hits))
            is_range = bool(ranges) and not _matches(o_reprs[ans - 1], cands)
            out.append({
                'code': 'ANS_RANGE_OUT' if is_range and len(others) == 1 else 'ANS_IN_OTHER',
                'sev': 'high', 'no': no, 'loc': loc, 'ans': ans, 'found_in': others,
                'want': opts[ans - 1][:60],
                'tail': (lines[-1] if lines else '')[:90],
            })
            stats['불일치'] += 1
            detail['불일치'].append(loc)
    return out, stats, detail


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('items_json')
    ap.add_argument('--out')
    a = ap.parse_args()
    data = json.load(open(a.items_json, encoding='utf-8'))
    findings, stats, detail = check(data['items'])
    if a.out:
        json.dump(findings, open(a.out, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
    print(f"{data['n']}문항 검사 → 결함 후보 {len(findings)}건")
    for k, v in Counter(x['code'] for x in findings).most_common():
        print(f"   {k}: {v}")
    print('검산 통계:', dict(stats))
    for f in findings:
        if f['code'].startswith('ANS_'):
            print(f"   [{f['code']}] #{f['no']} {f['loc']} 정답{f['ans']} "
                  f"일치보기{f['found_in']} | {f['want'][:40]} | 결론: {f['tail'][:50]}")
