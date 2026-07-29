#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""twin_check.py — 평가↔일반 쌍둥이문항 교차 검수 (토큰 0).

평가 문항의 `쌍둥이문항` 필드가 일반 문항을 가리킨다 (단방향, 1:N 허용).
실측으로 확인한 불변식만 검사한다 — 문법을 상상해서 만들지 말 것:

  지식단위 · 난이도 · 학습행동영역   쌍둥이끼리 100% 일치 (107/107)
  문항id 몸통                        'G' + 자기 몸통, 일련번호(-NN)만 다를 수 있음
  정답 번호                          19/107만 일치 — 자유 변동이므로 검사하지 않는다

검사 코드:
  TWIN_MISSING     평가 문항에 쌍둥이문항 필드가 비어 있음            medium
  TWIN_BROKEN_REF  가리킨 id가 일반 파일에 없음                       high
  TWIN_META_DIFF   지식단위/난이도/학습행동영역 불일치                high
  TWIN_ID_PATTERN  쌍둥이 id 몸통이 자기 몸통과 다름 (오타 의심)      medium
  TWIN_UNREF       평가 어디서도 참조되지 않는 일반 문항              low
"""
import argparse, json
from collections import Counter

META_INVARIANT = ('지식단위', '난이도', '학습행동영역')


def _body(item_id):
    """UG0C1S3Aa1-01 → G0C1S3Aa1 (접두 문자와 일련번호 제거)."""
    return item_id[1:].rsplit('-', 1)[0] if item_id else ''


def check(ev_items, gn_items):
    gn = {i['meta']['문항id']: i for i in gn_items}
    out, stats = [], Counter()
    referenced = set()

    for it in ev_items:
        my = it['meta']
        me, twin = my['문항id'], my.get('쌍둥이문항', '').strip()
        base = {'no': it['no'], 'loc': me, 'ans': it['answer'], 'found_in': []}
        if not twin:
            out.append({**base, 'code': 'TWIN_MISSING', 'sev': 'medium',
                        'want': '', 'tail': '쌍둥이문항 필드 비어 있음'})
            continue
        referenced.add(twin)
        g = gn.get(twin)
        if g is None:
            out.append({**base, 'code': 'TWIN_BROKEN_REF', 'sev': 'high',
                        'want': twin, 'tail': '일반 파일에 해당 문항id 없음'})
            continue
        stats['쌍성립'] += 1
        stats['정답일치' if it['answer'] == g['answer'] else '정답상이'] += 1

        diff = [f for f in META_INVARIANT
                if my.get(f, '').strip() != g['meta'].get(f, '').strip()]
        if diff:
            detail = ', '.join(f'{f}: {my.get(f)}≠{g["meta"].get(f)}' for f in diff)
            out.append({**base, 'code': 'TWIN_META_DIFF', 'sev': 'high',
                        'want': twin, 'tail': detail})
        if not (twin.startswith('G') and _body(twin) == _body(me)):
            out.append({**base, 'code': 'TWIN_ID_PATTERN', 'sev': 'medium',
                        'want': twin, 'tail': f'몸통 불일치 (기대 G{_body(me)}-*)'})

    multi = [t for t, c in Counter(
        i['meta'].get('쌍둥이문항', '').strip() for i in ev_items).items()
        if t and c > 1]
    stats['1:N참조'] = len(multi)

    for gid, g in gn.items():
        if gid not in referenced:
            out.append({'code': 'TWIN_UNREF', 'sev': 'low', 'no': g['no'],
                        'loc': gid, 'ans': g['answer'], 'found_in': [],
                        'want': '', 'tail': '평가 문항 어디서도 참조되지 않음'})
    return out, stats


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('eval_json', help='평가문항 items.json (쌍둥이문항 필드 보유측)')
    ap.add_argument('general_json', help='일반문항 items.json')
    ap.add_argument('--out')
    a = ap.parse_args()
    ev = json.load(open(a.eval_json, encoding='utf-8'))
    gn = json.load(open(a.general_json, encoding='utf-8'))
    findings, stats = check(ev['items'], gn['items'])
    if a.out:
        json.dump(findings, open(a.out, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
    print(f"쌍둥이 교차 검수: 평가 {ev['n']} × 일반 {gn['n']} → 결함 후보 {len(findings)}건")
    for k, v in Counter(x['code'] for x in findings).most_common():
        print(f"   {k}: {v}")
    print('통계:', dict(stats))
    for f in findings[:15]:
        print(f"   [{f['code']}] {f['loc']} → {f['want']} | {f['tail']}")
