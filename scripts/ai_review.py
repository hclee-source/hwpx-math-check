#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ai_review.py — Claude API 기반 심층 검수. 규칙으로 못 잡는 것만 맡긴다.

왜 필요한가: eq_answer_check는 `선택지[정답] ↔ 해설 결론`의 동치만 본다.
해설 자체의 계산이 틀렸거나 문제 조건이 불충분하면 정답과 해설은 여전히 서로
일치하므로 검사를 통과한다. 그 사각지대가 이 모듈의 담당 범위다.

설계 원칙 (docs/설계노트.md · README '검수 원칙'을 그대로 따른다):
  1) section0.xml을 컨텍스트에 올리지 않는다. 문항별 텍스트(본문·보기·정답·해설)와
     그 문항의 그림만 보낸다 — 한 요청에 다른 문항이 섞이지 않는다.
  2) 해설을 따라 읽고 수긍하지 말고 **먼저 스스로 푼다.** 그다음 인쇄된 정답과 대조한다.
  3) 오탐이 세 번 나면 아무도 안 쓴다 — 확신도가 낮으면 결함으로 올리지 않는다.
     등급(sev)은 모델이 정하지 않고 이 코드가 확신도에서 환산한다.
  4) 표기·조판 결함은 extra_checks/eq_answer_check가 이미 본다. 중복 보고를 금지한다.
  5) 그림이 없으면 판정하지 않는다. 기하는 그림이 조건의 일부라, --hwpx 로 그림을
     받으면 첨부하고, 못 받았으면 그렇다고 모델에 알려 추측을 막는다.

비용 설계: 문항 1개 = 요청 1개. 기본이 Batch API(50% 절감)이고, 검수 기준
프롬프트는 문항 211개에 걸쳐 프롬프트 캐싱으로 재사용된다. 판정 스키마는
structured outputs로 고정해 파싱 실패가 없다.

  python ai_review.py items.json --estimate            # 토큰·비용만 계산 (API 호출 0)
  python ai_review.py items.json --hwpx 원본.hwpx --limit 5 --sync   # 5문항 시범
  python ai_review.py items.json --hwpx 원본.hwpx --out ai_findings.json  # 전체(Batch)
"""
import argparse, base64, json, os, sys, time

MODEL = 'claude-opus-5'
MAX_TOKENS = 24000
# 2026-07 기준 Opus 5 단가 (USD / 1M tokens). Batch는 50%.
PRICE_IN, PRICE_OUT = 5.0, 25.0

# 확신도 → 등급. 모델에게 등급을 맡기지 않는 게 오탐 방어의 핵심이다.
SEV_BY_CONF = {
    'AI_ANSWER_WRONG':    {'높음': 'high', '보통': 'medium', '낮음': None},
    'AI_EXPL_ERROR':      {'높음': 'medium', '보통': 'low', '낮음': None},
    'AI_ITEM_AMBIGUOUS':  {'높음': 'medium', '보통': 'low', '낮음': None},
    # 그림 첨부가 있어야 판정 가능한 유형 (멀티모달)
    'AI_FIGURE_MISMATCH': {'높음': 'high', '보통': 'medium', '낮음': None},
    'AI_WORDING':         {'높음': 'low', '보통': 'low', '낮음': None},
}

SYSTEM = """당신은 고등학교 기하 문항 은행의 수학 검수자다. 출판 직전 원고를 본다.

# 가장 중요한 규칙
해설을 따라 읽고 수긍하지 마라. **먼저 본문과 보기만 보고 직접 풀어라.**
그다음에야 해설과 인쇄된 정답을 열어 대조한다. 해설의 논리를 먼저 읽으면
틀린 단계를 그대로 승인하게 된다.

# 이미 다른 검사가 처리하는 것 — 보고하지 마라
- 수식 조판(괄호 짝, 연산자에서 쪼개진 수식, 첨자 표기, 중괄호 공백)
- 표기 스타일 통일, 출처 표기, 오탈자, 문항 중복, 정답 분포 편향
- 정답 보기와 해설 결론의 문자열/수식 동치 여부
이것들은 결정론 스크립트가 전수로 잡는다. 중복 보고는 노이즈다.

# 당신이 볼 것 — 규칙으로 못 잡는 것만
1. AI_ANSWER_WRONG — 직접 푼 결과가 인쇄된 정답과 다르다.
2. AI_EXPL_ERROR — 해설 중간 단계가 틀렸거나 비약이다(결론은 맞을 수 있다).
3. AI_ITEM_AMBIGUOUS — 조건이 불충분해 답이 여러 개거나, 중의적이다.
4. AI_FIGURE_MISMATCH — 첨부된 그림이 본문·해설의 서술과 어긋난다.
5. AI_WORDING — 수학 용어가 틀렸거나 문장이 오해를 부른다. 문체 취향은 제외.

# 확신도를 정직하게 매겨라
- 높음: 계산을 두 번 다른 방법으로 검증했고 결론이 확실하다.
- 보통: 틀린 것 같지만 내가 조건을 놓쳤을 가능성이 남아 있다.
- 낮음: 애매하다. 그림이 있어야 판단되거나 근거가 약하다.
**인쇄된 정답을 뒤집는 판정은 단정하지 마라.** 애매하면 `판단불가` + `낮음`을
택하는 게 옳다. 틀린 지적 세 번이면 이 도구는 폐기된다. 확신 없는 지적보다
침묵이 낫다.

# 그림 관련
본문·해설의 `[그림 N]` 표시는 그 자리에 그림이 있다는 뜻이고, 텍스트 뒤에
같은 번호로 실제 이미지가 첨부된다. 기하 문항은 그림이 조건의 일부이므로
**이미지를 실제로 보고** 판단하라. 좌표축 방향, 점의 위치 관계, 각·길이 표시,
직각 기호, 음영 영역이 본문 조건이나 해설 서술과 어긋나면 AI_FIGURE_MISMATCH다.

`[그림 N]` 표시가 있는데 그 번호의 이미지가 첨부되지 않았다면(변환 실패)
그 문항은 `판단불가` / `낮음`으로 두고 추측하지 마라.

# 한글 수식 스크립트 문법 ($...$ 안)
{}over{} 분수 · sqrt{} 제곱근 · root n of x · ^{} 위첨자 · _{} 아래첨자
TIMES CDOT 곱 · bar{AB} 선분 · LEFT| |RIGHT 절댓값 · +- 복호 · != ≠
GEQ LEQ ≥≤ · DEG 도 · ANGLE 각 · TRIANGLE 삼각형 · CDOTS ⋯
& 와 # 는 여러 줄 정렬 수식의 구분자(#로 줄이 나뉘고 &는 정렬 기준)
백틱(`)과 ~ 는 공백 · it, rm 은 서체 지정자(수학적 의미 없음)

findings의 `evidence`에는 당신의 계산 근거를 짧고 검증 가능하게 적어라
(어떤 식에서 어떤 값이 나왔는지). 사람이 그 줄만 보고 재현할 수 있어야 한다.
`fix`에는 무엇을 어떻게 고치면 되는지 적어라. 모르면 빈 문자열로 둔다."""

VERDICT_SCHEMA = {
    'type': 'object',
    'properties': {
        'solved': {
            'type': 'string',
            'description': '해설을 보기 전에 직접 푼 결과. 값과 보기 번호를 함께 적는다.',
        },
        'answer_verdict': {
            'type': 'string',
            'enum': ['일치', '불일치', '판단불가'],
            'description': '직접 푼 결과와 인쇄된 정답의 대조 결과.',
        },
        'confidence': {'type': 'string', 'enum': ['높음', '보통', '낮음']},
        'findings': {
            'type': 'array',
            'description': '결함이 없으면 빈 배열. 확신 없는 지적은 넣지 않는다.',
            'items': {
                'type': 'object',
                'properties': {
                    'code': {'type': 'string',
                             'enum': list(SEV_BY_CONF)},
                    'where': {'type': 'string',
                              'description': '본문 / 보기N / 해설 중 어디인지'},
                    'detail': {'type': 'string', 'description': '무엇이 문제인지 한두 문장'},
                    'evidence': {'type': 'string', 'description': '재현 가능한 계산 근거'},
                    'fix': {'type': 'string', 'description': '수정 제안. 모르면 빈 문자열'},
                },
                'required': ['code', 'where', 'detail', 'evidence', 'fix'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['solved', 'answer_verdict', 'confidence', 'findings'],
    'additionalProperties': False,
}


def _item_text(it):
    """문항 하나를 검수용 텍스트로. XML도, 다른 문항도 섞지 않는다."""
    meta = it.get('meta', {})
    lines = [f"문항id: {it.get('loc', '')}",
             f"난이도: {meta.get('난이도', '')} / 지식단위: {meta.get('지식단위', '')}",
             '', '[본문]', it.get('q', ''), '', '[보기]']
    for k, o in enumerate(it.get('opts', []), 1):
        lines.append(f'{k}) {o}')
    lines += ['', f"[인쇄된 정답] {it.get('answer')}번", '', '[해설]',
              it.get('expl', '')]
    return '\n'.join(lines)


def _content(it, images=None):
    """user 컨텐츠 블록. 그림이 있으면 `[그림 N]` 라벨과 함께 이미지를 붙인다.

    images: {image_id: (media_type, bytes)} — hwpx_images.load() 산출.
    문항의 images 목록과 `[그림 N]` 번호가 같은 순서라, 라벨을 붙여 보내면
    모델이 어느 그림이 어느 표시인지 알 수 있다. 첨부 못 한 그림은 그렇다고
    적어 준다 — 없는 걸 상상해서 판정하면 그게 오탐이다.
    """
    blocks = [{'type': 'text', 'text': _item_text(it)}]
    if not images:
        return blocks
    missing = []
    for n, iid in enumerate(it.get('images', []), 1):
        got = images.get(iid)
        if not got:
            missing.append(n)
            continue
        mtype, data = got
        blocks.append({'type': 'text', 'text': f'[그림 {n}]'})
        blocks.append({'type': 'image',
                       'source': {'type': 'base64', 'media_type': mtype,
                                  'data': base64.standard_b64encode(data).decode()}})
    if missing:
        blocks.append({'type': 'text',
                       'text': '[그림 ' + ', '.join(map(str, missing))
                               + '] 은(는) 첨부하지 못했다 — 추측하지 말 것.'})
    return blocks


def build_params(it, images=None):
    """문항 1개에 대한 Messages API 파라미터.

    system은 문항마다 동일하므로 cache_control로 캐싱한다(문항 수만큼 재사용).
    판정 스키마는 output_config.format으로 고정 — 파싱 실패가 없다.
    effort는 high: 수학 검산은 얕게 생각하면 틀린다.
    """
    return {
        'model': MODEL,
        'max_tokens': MAX_TOKENS,
        'system': [{'type': 'text', 'text': SYSTEM,
                    'cache_control': {'type': 'ephemeral'}}],
        'output_config': {
            'effort': 'high',
            'format': {'type': 'json_schema', 'schema': VERDICT_SCHEMA},
        },
        'messages': [{'role': 'user', 'content': _content(it, images)}],
    }


def to_findings(loc, no, answer, verdict):
    """모델 판정 → 이 저장소의 finding 스키마(code/sev/no/loc/want/tail).

    등급은 모델이 아니라 여기서 확신도로 환산한다. 확신도 '낮음'은 버린다.
    """
    out = []
    conf = verdict.get('confidence', '낮음')
    for f in verdict.get('findings', []):
        sev = SEV_BY_CONF.get(f.get('code'), {}).get(conf)
        if sev is None:                     # 확신 없는 지적은 올리지 않는다
            continue
        out.append({
            'code': f['code'], 'sev': sev, 'no': no, 'loc': loc, 'ans': answer,
            'want': f.get('where', ''), 'tail': f.get('detail', ''),
            'evidence': f.get('evidence', ''), 'fix': f.get('fix', ''),
            'confidence': conf, 'solved': verdict.get('solved', ''),
            'verdict': verdict.get('answer_verdict', ''),
        })
    return out


def _parse(text):
    """구조화 출력이므로 첫 text 블록이 그대로 JSON이다."""
    return json.loads(text)


def _text_of(content):
    for b in content:
        if b.type == 'text':
            return b.text
    return ''


def estimate(items, images=None):
    """API 호출 없이 입력 토큰만 세어 비용 범위를 알려준다."""
    import anthropic
    client = anthropic.Anthropic()
    n_in = 0
    for it in items:
        p = build_params(it, images)
        n_in += client.messages.count_tokens(
            model=MODEL, system=p['system'], messages=p['messages']).input_tokens
    return n_in


def run_sync(items, progress=None, images=None):
    """즉시 실행. 소수 문항 시범용 — 전체는 Batch가 절반 값이다."""
    import anthropic
    client = anthropic.Anthropic()
    results, usage = {}, {'in': 0, 'out': 0}
    for i, it in enumerate(items, 1):
        # max_tokens가 크면 SDK가 비스트리밍 요청을 거부한다 → 스트리밍으로 받는다
        with client.messages.stream(**build_params(it, images)) as st:
            msg = st.get_final_message()
        usage['in'] += msg.usage.input_tokens
        usage['out'] += msg.usage.output_tokens
        if msg.stop_reason == 'refusal':
            results[it['loc']] = {'error': 'refusal'}
        else:
            results[it['loc']] = _parse(_text_of(msg.content))
        if progress:
            progress(i, len(items), it['loc'])
    return results, usage


def run_batch(items, poll=30, progress=None, images=None):
    """Batch API — 표준가의 50%. 보통 1시간 내, 최대 24시간."""
    import anthropic
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    client = anthropic.Anthropic()

    batch = client.messages.batches.create(requests=[
        Request(custom_id=it['loc'],
                params=MessageCreateParamsNonStreaming(**build_params(it, images)))
        for it in items])
    if progress:
        progress(f'배치 생성 {batch.id} — 문항 {len(items)}개')

    while True:
        batch = client.messages.batches.retrieve(batch.id)
        if batch.processing_status == 'ended':
            break
        if progress:
            c = batch.request_counts
            progress(f'  {batch.processing_status} 처리중 {c.processing} / '
                     f'성공 {c.succeeded} / 실패 {c.errored}')
        time.sleep(poll)

    results, usage = {}, {'in': 0, 'out': 0}
    # 결과 순서는 보장되지 않는다 — custom_id로 맞춘다
    for r in client.messages.batches.results(batch.id):
        if r.result.type != 'succeeded':
            results[r.custom_id] = {'error': r.result.type}
            continue
        msg = r.result.message
        usage['in'] += msg.usage.input_tokens
        usage['out'] += msg.usage.output_tokens
        if msg.stop_reason == 'refusal':
            results[r.custom_id] = {'error': 'refusal'}
        else:
            results[r.custom_id] = _parse(_text_of(msg.content))
    return results, usage


def review(items, sync=False, progress=None, poll=30, images=None):
    """items → (findings, results, usage). 실패 문항은 결함이 아니라 '검수 못함'.

    poll: 배치 상태 조회 간격(초). sync=True 면 무시된다.
    """
    if sync:
        results, usage = run_sync(items, progress=progress, images=images)
    else:
        results, usage = run_batch(items, poll=poll, progress=progress, images=images)
    by_loc = {i['loc']: i for i in items}
    findings, failed = [], []
    for loc, v in results.items():
        it = by_loc.get(loc)
        if it is None:
            continue
        if 'error' in v:
            failed.append({'loc': loc, 'why': v['error']})
            continue
        findings += to_findings(loc, it.get('no'), it.get('answer'), v)
    findings.sort(key=lambda x: ({'high': 0, 'medium': 1, 'low': 2}[x['sev']],
                                 x['code'], x.get('no') or 0))
    return findings, results, {**usage, 'failed': failed, 'batch': not sync}


def cost(usage, batch=True):
    rate = 0.5 if batch else 1.0
    return (usage['in'] / 1e6 * PRICE_IN + usage['out'] / 1e6 * PRICE_OUT) * rate


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('items_json')
    ap.add_argument('--out', help='판정 결과 JSON 저장 경로 (재실행 없이 재사용)')
    ap.add_argument('--limit', type=int, help='앞 N문항만 (시범 실행)')
    ap.add_argument('--sync', action='store_true',
                    help='Batch 대신 즉시 실행 (2배 비싸다 — 소수 문항만)')
    ap.add_argument('--estimate', action='store_true',
                    help='입력 토큰·예상 비용만 계산하고 끝낸다 (검수 호출 안 함)')
    ap.add_argument('--hwpx',
                    help='원본 hwpx — 그림을 꺼내 함께 보낸다 (기하는 그림이 조건의 일부)')
    a = ap.parse_args()

    data = json.load(open(a.items_json, encoding='utf-8'))
    items = data['items'][:a.limit] if a.limit else data['items']

    images = None
    if a.hwpx:
        import hwpx_images
        images = hwpx_images.load(a.hwpx)
        need = {i for it in items for i in it.get('images', [])}
        print(f'그림 {len(images)}개 추출, 이 문항들이 쓰는 것 {len(need)}개 '
              f'(첨부 불가 {len(need - set(images))}개)')
    elif any(it.get('images') for it in items):
        n = sum(1 for it in items if it.get('images'))
        print(f'※ 그림이 있는 문항 {n}개인데 --hwpx 를 주지 않았다. '
              f'그 문항은 AI가 판단불가로 되돌린다.', file=sys.stderr)

    if not (os.environ.get('ANTHROPIC_API_KEY')
            or os.environ.get('ANTHROPIC_AUTH_TOKEN')):
        print('ANTHROPIC_API_KEY 가 없다. 환경변수로 넣거나 `ant auth login` 후 실행.',
              file=sys.stderr)
        if not a.estimate:
            sys.exit(1)

    if a.estimate:
        n_in = estimate(items, images)
        # 출력 토큰은 실측 전이라 범위로 제시한다 (사고 과정 포함, 문항당 2~6천)
        for lo, hi in ((2000, 6000),):
            for label, rate in (('Batch(50%)', 0.5), ('즉시', 1.0)):
                c_lo = (n_in / 1e6 * PRICE_IN + len(items) * lo / 1e6 * PRICE_OUT) * rate
                c_hi = (n_in / 1e6 * PRICE_IN + len(items) * hi / 1e6 * PRICE_OUT) * rate
                print(f'{label}: ${c_lo:.2f} ~ ${c_hi:.2f}')
        print(f'문항 {len(items)}개 / 입력 {n_in:,} 토큰 '
              f'(검수 기준 프롬프트는 캐싱되어 실제로는 더 낮다)')
        sys.exit(0)

    def prog(*x):
        print(x[0] if len(x) == 1 else f'  [{x[0]}/{x[1]}] {x[2]}', flush=True)

    findings, results, usage = review(items, sync=a.sync, progress=prog,
                                      images=images)

    if a.out:
        json.dump({'model': MODEL, 'findings': findings, 'results': results,
                   'usage': {k: v for k, v in usage.items() if k != 'batch'}},
                  open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'판정 결과 → {a.out}')

    from collections import Counter
    print(f"문항 {len(items)}개 검수 → 결함 후보 {len(findings)}건 "
          f"(검수 실패 {len(usage['failed'])}건)")
    for k, v in Counter(f['code'] for f in findings).most_common():
        print(f'   {k}: {v}')
    print(f"토큰 입력 {usage['in']:,} / 출력 {usage['out']:,} "
          f"≈ ${cost(usage, usage['batch']):.2f}")
    for f in findings[:20]:
        print(f"   [{f['sev']}/{f['code']}] #{f.get('no')} {f['loc']} "
              f"({f['confidence']}) {f['want']} | {f['tail'][:60]}")
