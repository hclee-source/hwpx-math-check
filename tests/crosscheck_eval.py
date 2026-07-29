# -*- coding: utf-8 -*-
"""claude.ai 보고서의 각 주장을 우리 프로그램 출력과 문항 번호까지 대조."""
import io, json, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r'C:\hcl\hwpx-math-check\scripts')
import math_review

d = json.load(open(r'C:\hcl\hwpx-math-check\data\평가_full.json', encoding='utf-8'))
no_of = {i['loc']: i['no'] for i in d['items']}
findings, stats, details, items, extras = math_review.run(
    [r'C:\hcl\hwpx-math-check\data\평가_full.json'])
ex = list(extras.values())[0]

def nos(locs):
    return sorted(no_of.get(l, -1) for l in locs)

OK, NG = [], []
def cmp(label, ours, claude):
    same = sorted(ours) == sorted(claude)
    (OK if same else NG).append(label)
    print(('  일치 ' if same else '  불일치') + f' {label}')
    print(f'      우리   : {sorted(ours)}')
    print(f'      claude : {sorted(claude)}')

print('=== claude.ai 주장 vs 우리 출력 (문항 번호 기준) ===\n')

# 1. 수식 쪼개짐 — claude: 11(보기①③④), 17(보기① + 해설)
orph = [f for f in findings if f['code'] == 'EQ_ORPHAN_OP']
cmp('수식 쪼개짐 문항', nos([f['loc'] for f in orph]), [11, 17])
print(f'      필드: {[(no_of[f["loc"]], f["want"]) for f in orph]}')

# 2. 완전 중복 3쌍 — claude: 7≡29, 9≡101, 67≡87
ex_dups = [(no_of[dd['a']], no_of[dd['b']]) for dd in ex['dups'] if dd['exact']]
cmp('완전 중복 쌍', [tuple(sorted(t)) for t in ex_dups],
    [(7, 29), (9, 101), (67, 87)])

# 3. 오탈자 — claude: 70(수선이 발), 107(커야한다), 15(2개다)
cmp('오탈자 문항', nos([t['loc'] for t in ex['typos']]), [15, 70, 107])
print(f'      내용: {[(no_of[t["loc"]], t["hit"], t["fix"]) for t in ex["typos"]]}')

# 4. 출처 혼용 — claude: 쎈36/쏀5, 쏀 문항 27,28,30,31,96
c = ex['citations'][0] if ex['citations'] else None
if c:
    print(f'  출처: 우리 {c["major"]}{c["major_n"]}/{c["minor"]}{c["minor_n"]}'
          f'  claude 쎈36/쏀5')
    cmp('쏀 표기 문항', nos(c['locs']), [27, 28, 30, 31, 96])

# 5. 수식 표기 유형별
S = ex['style']
def st(name):
    return nos(S.get(name, {}).get('locs', []))
cmp('첨자 안 쉼표', st('첨자 안 쉼표'), [35, 36, 43, 44, 54, 103])
cmp('숫자 뒤 잔여 공백', st('수식 끝 여분 공백'), [19, 76])
cmp('아래첨자 민형식', st('아래첨자 민형식 a_1'), [43, 47])
cmp('위첨자 민형식', st('위첨자 민형식 a^2'), [44, 46])
cmp('한 수식 내 혼용', st('한 수식 내 위첨자 형식 혼용'), [77])
cmp('비교 연산자 공백', st('비교 연산자 공백 불일치'), [96])
print(f'  분수 중괄호 여분 공백: 우리 {st("중괄호 안 여분 공백")}'
      f'  claude [10,12,40,45,52,53,61]')

# 6. 편집 메모 — claude: 평가 파일엔 0건
print(f'\n  편집 메모: 우리 {len(ex["memos"])}건, claude 0건 '
      + ('일치' if len(ex['memos']) == 0 else '불일치'))

# 7. 통계
s = ex['stats']
print(f'  정답 분포: 우리 {s["dist"]} χ²={s["chi2"]}  '
      f'claude ①15②29③19④26⑤18 χ²=6.41')
print(f'  노출 편향: 우리 {s["longest_n"]}건, claude 6건')

# 8. 수학적 오류 — claude 5건 + 복수정답 1
math_locs = ['CG0C1S2Bb3-01', 'SG0C1S3Ab2-02', 'UG0C1S4Aa3-01',
             'CG0C1S2Ab2-01', 'CG0C1S2Ba1-01', 'CG0C1S4Fb2-01']
caught = [l for l in math_locs if any(f['loc'] == l for f in findings)]
print(f'\n  수학적 오류 {len(math_locs)}건(claude): 우리가 결함으로 잡은 것 {len(caught)}건 {caught}')
todo = set(details[list(details)[0]]['판정불가'] + details[list(details)[0]]['결론없음'])
print(f'  그중 "정독 대상"으로 넘긴 것: {[l for l in math_locs if l in todo]}')

print(f'\n=== 대조 항목 {len(OK)+len(NG)}개 중 일치 {len(OK)} / 불일치 {len(NG)} ===')
if NG:
    print('불일치:', NG)
