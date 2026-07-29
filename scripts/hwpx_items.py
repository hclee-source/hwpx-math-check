#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hwpx_items.py — 표 기반 hwpx 문항 은행을 exam-item-reviewer 입력(items.json)으로 정규화.

전제 구조: 문항 1개 = 2열 표 1개 (좌=필드명, 우=값)
  문항id / 본문 / 선택지1~5 / 정답 / 해설1~3 / 지식단위 / 난이도 / 학습행동영역 / 쌍둥이문항

수식(<hp:equation>)은 한글 수식 스크립트를 $...$ 로 인라인해 보존한다.
본문을 stdout으로 쏟지 않고 통계만 출력한다(토큰 절약).
"""
import argparse, json, re, zipfile
from lxml import etree

ln = lambda e: etree.QName(e).localname
FIELDS = ['문항id', '본문', '선택지1', '선택지2', '선택지3', '선택지4', '선택지5',
          '정답', '해설1', '해설2', '해설3', '지식단위', '난이도', '학습행동영역', '쌍둥이문항']


def _eq(eq):
    for c in eq.iter():
        if ln(c) == 'script':
            return (c.text or '').strip()
    return ''


def _cell_text(tc, eq_wrap=True):
    """셀 안 문단을 순서대로 복원. 문단 사이는 개행으로 유지."""
    out = []
    for p in tc.iter():
        if ln(p) != 'p':
            continue
        buf = []
        for run in p:
            if ln(run) != 'run':
                continue
            for ch in run:
                if ln(ch) == 't':
                    buf.append(ch.text or '')
                elif ln(ch) == 'equation':
                    s = _eq(ch)
                    buf.append(f'${s}$' if eq_wrap else s)
        seg = ''.join(buf)
        if seg.strip():
            out.append(seg.strip())
    return '\n'.join(out)


def _own_rows(tbl):
    """이 표가 직접 가진 tr만 (중첩 표 제외)."""
    for tr in tbl.iter():
        if ln(tr) != 'tr':
            continue
        anc, ok = tr.getparent(), True
        while anc is not None and anc is not tbl:
            if ln(anc) == 'tbl':
                ok = False
                break
            anc = anc.getparent()
        if ok:
            yield tr


def _own_cells(tr):
    for tc in tr.iter():
        if ln(tc) != 'tc':
            continue
        anc, ok = tc.getparent(), True
        while anc is not None and anc is not tr:
            if ln(anc) == 'tr':
                ok = False
                break
            anc = anc.getparent()
        if ok:
            yield tc


def parse(path):
    items, skipped = [], 0
    with zipfile.ZipFile(path) as z:
        secs = sorted(n for n in z.namelist() if re.match(r'Contents/section\d+\.xml', n))
        for sec in secs:
            root = etree.fromstring(z.read(sec))
            for tbl in root.iter():
                if ln(tbl) != 'tbl':
                    continue
                rec = {}
                for tr in _own_rows(tbl):
                    cells = list(_own_cells(tr))
                    if len(cells) < 2:
                        continue
                    key = _cell_text(cells[0], eq_wrap=False).strip()
                    if key in FIELDS:
                        rec[key] = _cell_text(cells[1])
                if '문항id' not in rec or not rec.get('문항id', '').strip():
                    skipped += 1
                    continue
                items.append(rec)
    return items, skipped


def to_items_json(recs, source):
    out = []
    for i, r in enumerate(recs, 1):
        opts = [r.get(f'선택지{k}', '').strip() for k in range(1, 6)]
        while opts and not opts[-1]:
            opts.pop()
        raw = (r.get('정답') or '').strip()
        m = re.search(r'[1-9]', raw)
        ans = int(m.group()) if m else None
        expl = '\n'.join(x for x in (r.get(f'해설{k}', '').strip() for k in (1, 2, 3)) if x)
        out.append({
            'no': i, 'q': r.get('본문', '').strip(), 'opts': opts,
            'answer': ans, 'answer_raw': raw, 'expl': expl,
            'loc': r.get('문항id', ''),
            'meta': {k: r.get(k, '') for k in ('문항id', '지식단위', '난이도', '학습행동영역', '쌍둥이문항')},
        })
    return {'source': source, 'n': len(out), 'items': out}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('hwpx')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    recs, skipped = parse(a.hwpx)
    data = to_items_json(recs, a.hwpx)
    json.dump(data, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    import collections
    nopt = collections.Counter(len(i['opts']) for i in data['items'])
    noans = sum(1 for i in data['items'] if i['answer'] is None)
    noexp = sum(1 for i in data['items'] if not i['expl'])
    neq = sum(i['q'].count('$') + i['expl'].count('$') for i in data['items']) // 2
    print(f"문항 {data['n']}개 (표 건너뜀 {skipped}개) → {a.out}")
    print(f"  보기 개수 분포: {dict(sorted(nopt.items()))}")
    print(f"  정답 미확정 {noans} / 해설 없음 {noexp} / 수식 약 {neq}개")
