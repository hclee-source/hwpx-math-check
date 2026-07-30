#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hwpx_fix.py — 검사기가 잡은 결함 중 기계적으로 확정 가능한 것만 hwpx에 반영한다.

설계 원칙:
  1) 고칠 대상을 새로 찾지 않는다. extra_checks/eq_answer_check가 낸 결함 목록을
     그대로 입력으로 받아, 그 문항·그 유형에만 규칙을 적용한다.
     → 검사기와 교정기가 어긋날 수 없고, 교정 후 재검사하면 0건으로 수렴한다.
  2) 원본을 덮어쓰지 않는다. 항상 새 파일을 쓴다.
  3) 판단이 필요한 결함(완전 중복 문항, 편집 메모, 유사 문항)은 손대지 않고 보고한다.
  4) 변경 하나하나를 (문항id, 필드, 유형, 전/후)로 남긴다 — 편집자가 검증할 수 있게.

주의: 수식을 병합하면 한글이 저장해 둔 레이아웃 캐시(lineseg)가 낡는다.
      교정 후 **한글에서 열고 저장**한 뒤 재검사해야 쪽 번호가 정확하다.

  python hwpx_fix.py 원본.hwpx [--out 교정.hwpx] [--dry-run] [--log 변경내역.json]
"""
import argparse, json, re, zipfile
from collections import Counter

from lxml import etree

import eq_answer_check
import extra_checks
import hwpx_items
from hwpx_items import (FIELDS, _cell_text, _own_cells, _own_rows, _para_text,
                        _top_tables, ln, to_items_json)

SECTION = re.compile(r'Contents/section\d+\.xml')


# ── 텍스트 규칙 (한글 본문 <hp:t>) ────────────────────────────────────────────
# extra_checks.TYPOS의 '무엇이 틀렸나'에 대응하는 '무엇으로 고치나'.
# 연속 공백은 조판 의도일 수 있어 자동 교정 대상에서 뺀다.
TEXT_FIX = [
    ('수선이 발', re.compile(r'수선이 발'), '수선의 발'),
    ('커야한다', re.compile(r'커야한다'), '커야 한다'),
    ('작아야한다', re.compile(r'작아야한다'), '작아야 한다'),
    ('추죽', re.compile(r'추죽'), '주축'),
    ('개다', re.compile(r'(?<![가-힣])개다(?=[.\s]|$)'), '개이다'),
    ('되므로므로', re.compile(r'되므로므로'), '되므로'),
    ('이므로므로', re.compile(r'이므로므로'), '이므로'),
]


# ── 수식 규칙 (<hp:script>) ──────────────────────────────────────────────────
def _fix_sub_comma(s):
    """_{1,} → _{1} ,  쉼표가 아래첨자로 작게 조판되는 실제 렌더링 오류."""
    return re.sub(r'_\s*\{([^{}]*?),\s*\}', r'_{\1} ,', s)


def _fix_brace_space(s):
    """{ 1} over { 2} → {1} over {2}.  LEFT/RIGHT 뒤 공백은 구분자라 건드리지 않는다."""
    def rep(m):
        if re.search(r'(?:LEFT|RIGHT)\s*$', s[:m.start()]):
            return m.group()
        return '{' + m.group(1)
    return re.sub(r'\{[ \t]+(\S)', rep, s)


def _fix_plain_sub(s):
    """m_2 → m _{2}"""
    return re.sub(r'([A-Za-z])_(\d+)', r'\1 _{\2}', s)


def _fix_plain_sup(s):
    """r^2 → r ^{2}"""
    return re.sub(r'\s*\^(\d+)', r' ^{\1}', s)


def _fix_cmp_brace(s):
    """k<{-1} → k<-1   (정규화에서 뭉개지는 원인)"""
    return re.sub(r'([<>]\s*)\{\s*(-?\d+(?:\.\d+)?)\s*\}(?!\s*(?:over|\^|_|/))',
                  r'\1\2', s)


def _fix_cmp_space(s):
    """b!=0 → b != 0   (같은 줄에서 a != 0 과 혼용되던 것)"""
    s = re.sub(r'(?<=\S)(!=|<=|>=)', r' \1', s)
    return re.sub(r'(!=|<=|>=)(?=\S)', r'\1 ', s)


def _fix_trailing_space(s):
    """보기 수식이 숫자뿐인데 꼬리 백틱 → 선택지 우측 정렬이 어긋난다. 21` → 21"""
    m = re.fullmatch(r'[\s`~]*(\d+)[\s`~]+', s)
    return m.group(1) if m else s


def _fix_root(s):
    """root5 → sqrt {5}   (원고 전체가 sqrt 표기)"""
    return re.sub(r'\broot\s*(\d+)(?!\s*of)', r'sqrt {\1}', s)


def _fix_bar_it(s):
    """bar{rm BD } → bar{rm BD it}   (선분 표기 195건 중 1건만 it 누락)"""
    def rep(m):
        inner = m.group(1)
        if re.search(r'\bit\b', inner):
            return m.group()
        return 'bar{' + inner.rstrip() + ' it}'
    return re.sub(r'bar\s*\{([^{}]*)\}', rep, s)


# 검사기의 표기 유형명 → 적용할 수식 규칙
SCRIPT_FIX = {
    '첨자 안 쉼표': _fix_sub_comma,
    '중괄호 안 여분 공백': _fix_brace_space,
    '아래첨자 민형식 a_1': _fix_plain_sub,
    '위첨자 민형식 a^2': _fix_plain_sup,
    '한 수식 내 위첨자 형식 혼용': _fix_plain_sup,
    '한 수식 내 아래첨자 형식 혼용': _fix_plain_sub,
    '비교식 불필요 중괄호': _fix_cmp_brace,
    '비교 연산자 공백 불일치': _fix_cmp_space,
    '수식 끝 여분 공백': _fix_trailing_space,
    'root 표기': _fix_root,
    '서체 혼용: bar에 it 누락': _fix_bar_it,
}

# 사람이 판단해야 하는 결함 — 교정기가 절대 손대지 않는다
MANUAL = {
    'ITEM_DUP_EXACT': '완전 중복 문항 — 어느 쪽을 남기고 어느 쪽을 변형할지는 편집 판단',
    'OPT_DUP_EQ': '선택지 중복 — 어떤 값으로 바꿀지는 출제 판단',
    'ANS_RANGE_OUT': '정답이 해설 결론 범위를 벗어남 — 수학적 재검토 필요',
    'ANS_IN_OTHER': '정답 후보가 여럿 — 수학적 재검토 필요',
    'EQ_UNBALANCED': '괄호 짝이 맞지 않음 — 의도한 수식을 알 수 없음',
    'META_MISMATCH': '메타 필드 불일치 — 원본 대장과 대조 필요',
}

ORPHAN_TAIL = re.compile(r'(?:<=|>=|[=<>+\-])\s*$')


def _script_of(eq):
    for c in eq:
        if ln(c) == 'script':
            return c
    return None


def _sz_of(eq):
    for c in eq:
        if ln(c) == 'sz':
            return c
    return None


def _texts(el):
    return [t for t in el.iter() if ln(t) == 't']


def _scripts(el):
    return [s for s in el.iter() if ln(s) == 'script']


def _walk(root):
    """문항별로 (loc, {필드: 셀 element}, 출처 문단 element)을 수집.

    hwpx_items.parse와 같은 순서로 훑으므로 검사기가 본 것과 정확히 같은 대상이다.
    """
    out = []
    pending = None                          # 표 바로 앞 문단 = 출처 표기
    for p in root:
        if ln(p) != 'p':
            continue
        had_tbl = False
        for tbl in _top_tables(p):
            had_tbl = True
            cells = {}
            for tr in _own_rows(tbl):
                tcs = list(_own_cells(tr))
                if len(tcs) < 2:
                    continue
                key = _cell_text(tcs[0], eq_wrap=False).strip()
                if key in FIELDS:
                    cells[key] = tcs[1]
            loc = _cell_text(cells['문항id'], eq_wrap=False).strip() \
                if '문항id' in cells else ''
            if loc:
                out.append((loc, cells, pending))
        txt = _para_text(p)
        pending = p if txt else (None if had_tbl else pending)
    return out


def _field_cells(cells, field):
    """검사기의 필드명(본문/보기N/해설/출처) → 셀 element 목록."""
    if field == '본문':
        return [cells['본문']] if '본문' in cells else []
    if field.startswith('보기'):
        k = field[2:]
        return [cells[f'선택지{k}']] if f'선택지{k}' in cells else []
    if field == '해설':
        return [cells[f'해설{k}'] for k in (1, 2, 3) if f'해설{k}' in cells]
    return []


def fix(path, dry_run=False):
    """hwpx를 검사한 뒤, 확정 가능한 결함만 고친 XML과 변경 내역을 돌려준다."""
    with zipfile.ZipFile(path) as z:
        secs = sorted(n for n in z.namelist() if SECTION.match(n))
        raws = {s: z.read(s) for s in secs}

    changes = []
    roots = {s: etree.fromstring(raws[s]) for s in secs}

    # 파싱 → 검사. 검사기가 낸 결함 목록이 곧 교정 대상 명세다
    parsed, _ = hwpx_items.parse(path)
    data = to_items_json(parsed, path)
    ex = extra_checks.analyze(data)
    eq_findings, _, _ = eq_answer_check.check(data['items'])

    # 문항id → (셀 map, 출처 문단)
    scope = {}
    for s in secs:
        for loc, cells, cite in _walk(roots[s]):
            scope[loc] = (cells, cite)

    def log(loc, field, kind, before, after):
        if before != after:
            changes.append({'loc': loc, 'field': field, 'kind': kind,
                            'before': before, 'after': after})
            return True
        return False

    # ── 1) 오탈자 ──────────────────────────────────────────────────────────
    for t in ex['typos']:
        cells, _ = scope.get(t['loc'], (None, None))
        if cells is None:
            continue
        for cell in _field_cells(cells, t['field']):
            for el in _texts(cell):
                s0 = el.text or ''
                s = s0
                for name, pat, rep in TEXT_FIX:
                    s = pat.sub(rep, s)
                if log(t['loc'], t['field'], f'오탈자 {t["hit"]}', s0, s):
                    el.text = s

    # ── 2) 출처 표기 혼용 (쏀 → 쎈) ────────────────────────────────────────
    for c in ex['citations']:
        for loc in c['locs']:
            _, cite = scope.get(loc, (None, None))
            if cite is None:
                continue
            for el in _texts(cite):
                s0 = el.text or ''
                s = s0.replace(c['minor'], c['major'])
                if log(loc, '출처', f"출처 표기 {c['minor']}→{c['major']}", s0, s):
                    el.text = s

    # ── 3) 수식 표기 ───────────────────────────────────────────────────────
    for name, info in ex['style'].items():
        rule = SCRIPT_FIX.get(name)
        if rule is None:
            continue
        for loc in info['locs']:
            cells, _ = scope.get(loc, (None, None))
            if cells is None:
                continue
            for field, cell in list(cells.items()):
                for el in _scripts(cell):
                    s0 = el.text or ''
                    s = rule(s0)
                    if log(loc, field, name, s0, s):
                        el.text = s

    # ── 4) 쪼개진 수식 병합 (연산자에서 끊긴 인접 수식) ────────────────────
    for f in eq_findings:
        if f['code'] != 'EQ_ORPHAN_OP':
            continue
        cells, _ = scope.get(f['loc'], (None, None))
        if cells is None:
            continue
        for field, cell in list(cells.items()):
            for para in cell.iter():
                if ln(para) != 'p':
                    continue
                for run in para:
                    if ln(run) != 'run':
                        continue
                    eqs = [c for c in run if ln(c) == 'equation']
                    i = 0
                    while i < len(eqs) - 1:
                        a, b = eqs[i], eqs[i + 1]
                        sa, sb = _script_of(a), _script_of(b)
                        if sa is None or sb is None or \
                                not ORPHAN_TAIL.search((sa.text or '').strip()):
                            i += 1
                            continue
                        merged = (sa.text or '').strip() + (sb.text or '').strip()
                        log(f['loc'], field, '쪼개진 수식 병합',
                            f'{sa.text} | {sb.text}', merged)
                        sa.text = merged
                        # 나란히 놓였던 두 수식의 폭 합 = 병합 후 폭 (조판 폭 보존)
                        za, zb = _sz_of(a), _sz_of(b)
                        if za is not None and zb is not None:
                            try:
                                za.set('width', str(int(za.get('width', 0))
                                                    + int(zb.get('width', 0))))
                                za.set('height', str(max(int(za.get('height', 0)),
                                                         int(zb.get('height', 0)))))
                            except ValueError:
                                pass
                        run.remove(b)
                        eqs.pop(i + 1)
    # 남은 결함 = 사람이 판단할 것
    manual = []
    for f in eq_findings + ex['findings']:
        if f['code'] in MANUAL:
            manual.append({'code': f['code'], 'loc': f['loc'],
                           'want': f.get('want', ''), 'why': MANUAL[f['code']]})
    for m in ex['memos']:
        manual.append({'code': 'EDIT_MEMO', 'loc': m['loc'],
                       'want': f"{m['field']} {m['hit']}",
                       'why': '편집 메모가 원고에 남아 있다 — 그림이 실제로 반영됐는지 확인 후 지울 것'})
    for d in ex['dups']:
        if not d['exact']:
            manual.append({'code': 'ITEM_DUP_NEAR', 'loc': d['a'], 'want': d['b'],
                           'why': '유사 문항 — 변형이 충분한지 사람이 읽어야 한다'})

    out_raws = dict(raws)
    if not dry_run:
        for s in secs:
            decl = raws[s].split(b'?>', 1)[0] + b'?>'      # 원본 선언 그대로
            out_raws[s] = decl + etree.tostring(roots[s], encoding='UTF-8',
                                               xml_declaration=False)
    return out_raws, changes, manual, ex, data


def write_hwpx(src, dst, out_raws):
    """zip 항목 순서·압축 방식을 원본 그대로 유지하고 section만 갈아끼운다.

    mimetype은 반드시 첫 항목·무압축이어야 한글이 읽는다.
    """
    with zipfile.ZipFile(src) as zin, \
            zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = out_raws.get(info.filename) or zin.read(info.filename)
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zi.internal_attr = info.internal_attr
            zi.create_system = info.create_system
            zout.writestr(zi, data)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('hwpx')
    ap.add_argument('--out', help='기본값: 원본 옆에 *_교정.hwpx')
    ap.add_argument('--log', help='변경 내역 JSON 저장 경로')
    ap.add_argument('--dry-run', action='store_true', help='파일을 쓰지 않고 보고만')
    a = ap.parse_args()

    out_raws, changes, manual, ex, data = fix(a.hwpx, dry_run=a.dry_run)

    print(f"{data['n']}문항 — 자동 교정 {len(changes)}건 / 사람 판단 {len(manual)}건")
    for kind, n in Counter(c['kind'] for c in changes).most_common():
        print(f'   [교정] {kind}: {n}건')
    for code, n in Counter(m['code'] for m in manual).most_common():
        print(f'   [보류] {code}: {n}건')

    if a.log:
        json.dump({'source': a.hwpx, 'changes': changes, 'manual': manual},
                  open(a.log, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'변경 내역 → {a.log}')

    if a.dry_run:
        for c in changes[:40]:
            print(f"   {c['loc']} {c['field']} [{c['kind']}]")
            print(f"      - {c['before']!r}")
            print(f"      + {c['after']!r}")
        if len(changes) > 40:
            print(f'   … 외 {len(changes) - 40}건')
    else:
        out = a.out or re.sub(r'\.hwpx$', '_교정.hwpx', a.hwpx)
        write_hwpx(a.hwpx, out, out_raws)
        print(f'교정본 → {out}')
        print('※ 한글에서 열고 저장한 뒤 재검사할 것 (레이아웃 캐시 갱신)')
