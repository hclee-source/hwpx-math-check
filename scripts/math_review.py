#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""math_review.py — 수학 문항 은행 검수 통합 러너 (exam-item-reviewer의 --math 모드 진입점).

items.json(hwpx_items.py 산출)을 받아 수학 전용 검사를 한 번에 돌린다:
  1) eq_answer_check  정답↔해설 SymPy 동치 검산 + 조판 결함(고아 연산자·괄호짝)
  2) twin_check       파일 2개면 쌍둥이문항 교차 검수 (첫 번째 = 쌍둥이 필드 보유측)

exam-item-reviewer 통합: 이 저장소 scripts/*.py 를 스킬의 scripts/ 에 복사하고,
check_items.py(13종 정합성)와 같은 items.json 을 이 러너에도 넘기면 된다.
finding 스키마(code/sev/no/loc/...)는 check_items.py 와 동일하게 맞춰져 있다.

  python math_review.py 평가_items.json 일반_items.json --out report.json
"""
import argparse, json
from collections import Counter

import eq_answer_check
import extra_checks
import twin_check

SEV_ORDER = {'high': 0, 'medium': 1, 'low': 2}


def run(paths, ai=False, ai_sync=False, ai_limit=None, ai_progress=None):
    findings, stats, details, extras = [], {}, {}, {}
    datas = []
    for path in paths:
        data = json.load(open(path, encoding='utf-8'))
        datas.append(data)
        src = data.get('source', path)
        f, st, dt = eq_answer_check.check(data['items'])
        ex = extra_checks.analyze(data)
        f += ex['findings']                      # 메타 정합 위반은 결함 카드로
        for x in f:
            x['file'] = src
        findings += f
        stats[f'검산:{path}'] = dict(st)
        details[str(path)] = dt
        extras[src] = ex

    if len(datas) == 2:
        # 쌍둥이문항 필드가 채워진 쪽이 평가측 — 파일 순서는 어떻게 줘도 된다
        def n_twin(d):
            return sum(1 for i in d['items']
                       if i['meta'].get('쌍둥이문항', '').strip())
        ev, gn = sorted(datas, key=n_twin, reverse=True)
        f, st = twin_check.check(ev['items'], gn['items'])
        for x in f:
            x['file'] = '쌍둥이교차'
        findings += f
        stats['쌍둥이'] = dict(st)

    if ai:
        # 규칙이 못 잡는 것(해설 단계 오류·조건 불충분)만 Claude API에 넘긴다.
        # 결정론 검사와 달리 토큰이 든다 — 호출은 명시적 요청(--ai)일 때만.
        import ai_review
        for data in datas:
            its = data['items'][:ai_limit] if ai_limit else data['items']
            f, _, usage = ai_review.review(its, sync=ai_sync, progress=ai_progress)
            for x in f:
                x['file'] = data.get('source', '')
            findings += f
            stats[f"AI:{data.get('source', '')}"] = {
                '문항': len(its), '결함후보': len(f),
                '검수실패': len(usage['failed']),
                '비용USD': round(ai_review.cost(usage, usage['batch']), 2)}

    findings.sort(key=lambda x: (SEV_ORDER.get(x['sev'], 9), x['code'], x.get('no', 0)))
    items = {i['meta'].get('문항id', i.get('loc', '')): i
             for d in datas for i in d['items']}
    return findings, stats, details, items, extras


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('items_json', nargs='+',
                    help='items.json 1~2개 (2개면 첫 번째가 쌍둥이 필드 보유측=평가)')
    ap.add_argument('--out')
    ap.add_argument('--html', help='편집자용 HTML 보고서 저장 경로')
    ap.add_argument('--ai', action='store_true',
                    help='Claude API 심층 검수 추가 (토큰 비용 발생 — ai_review.py)')
    ap.add_argument('--ai-sync', action='store_true', help='AI 검수를 Batch 대신 즉시 실행')
    ap.add_argument('--ai-limit', type=int, help='AI 검수를 앞 N문항만 (시범)')
    a = ap.parse_args()
    if len(a.items_json) > 2:
        ap.error('items.json 은 1개 또는 2개')

    findings, stats, details, items, extras = run(
        a.items_json, ai=a.ai, ai_sync=a.ai_sync, ai_limit=a.ai_limit,
        ai_progress=(lambda *x: print(x[0] if len(x) == 1
                                      else f'  [{x[0]}/{x[1]}] {x[2]}', flush=True)))
    if a.out:
        json.dump({'findings': findings, 'stats': stats, 'details': details,
                   'extras': extras},
                  open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if a.html:
        import report_html
        open(a.html, 'w', encoding='utf-8').write(
            report_html.render(findings, stats, details, a.items_json,
                               items=items, extras=extras))

    n_items = sum(len(json.load(open(p, encoding='utf-8'))['items'])
                  for p in a.items_json)
    print(f'수학 검수 통합 실행: {n_items}문항 → 결함 후보 {len(findings)}건')
    by_sev = Counter(x['sev'] for x in findings)
    if findings:
        print(f"   심각도: {dict(by_sev)}")
    for k, v in Counter(x['code'] for x in findings).most_common():
        print(f'   {k}: {v}')
    for key, st in stats.items():
        print(f'{key}: {st}')
    for f in findings[:20]:
        print(f"   [{f['sev']}/{f['code']}] #{f.get('no')} {f['loc']} | "
              f"{str(f.get('want', ''))[:40]} | {str(f.get('tail', ''))[:50]}")
