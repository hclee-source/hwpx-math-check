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
import twin_check

SEV_ORDER = {'high': 0, 'medium': 1, 'low': 2}


def run(paths):
    findings, stats = [], {}
    datas = []
    for path in paths:
        data = json.load(open(path, encoding='utf-8'))
        datas.append(data)
        f, st = eq_answer_check.check(data['items'])
        for x in f:
            x['file'] = data.get('source', path)
        findings += f
        stats[f'검산:{path}'] = dict(st)

    if len(datas) == 2:
        f, st = twin_check.check(datas[0]['items'], datas[1]['items'])
        for x in f:
            x['file'] = '쌍둥이교차'
        findings += f
        stats['쌍둥이'] = dict(st)

    findings.sort(key=lambda x: (SEV_ORDER.get(x['sev'], 9), x['code'], x.get('no', 0)))
    return findings, stats


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('items_json', nargs='+',
                    help='items.json 1~2개 (2개면 첫 번째가 쌍둥이 필드 보유측=평가)')
    ap.add_argument('--out')
    a = ap.parse_args()
    if len(a.items_json) > 2:
        ap.error('items.json 은 1개 또는 2개')

    findings, stats = run(a.items_json)
    if a.out:
        json.dump({'findings': findings, 'stats': stats},
                  open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

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
