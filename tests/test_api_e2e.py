#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_api_e2e.py — ai_review를 실제 Anthropic SDK로 끝까지 태워 검증한다.

로컬 목 HTTP 서버를 띄우고 ANTHROPIC_BASE_URL로 SDK를 그쪽으로 돌린다.
따라서 검증되는 것이 모킹된 단위 테스트보다 훨씬 넓다:

  · SDK가 우리 요청 파라미터를 실제로 직렬화해 전송하는가 (오타·구식 파라미터 검출)
  · 프롬프트 캐싱·structured outputs가 요청 본문(wire)에 제대로 실리는가
  · run_sync의 SSE 스트림 수신·누적이 되는가
  · run_batch의 폴링 루프가 실제로 폴링하고 종료 조건을 지키는가
  · 배치 결과 JSONL을 순서 무관하게 custom_id로 맞추는가
  · refusal·errored 문항을 결함이 아니라 '검수 실패'로 분리하는가
  · 그림을 base64 image 블록으로 `[그림 N]` 라벨과 함께 전송하는가 (멀티모달)
  · 그림을 안 넘겼을 때 image 블록이 없는가 (쓸데없는 토큰을 안 태우는가)
  · 토큰 사용량 누적과 Batch 50% 단가 환산

검증되지 않는 것: Anthropic 서버의 실제 판정 품질. 그건 코드로 검증할 수 없다.

  python tests/test_api_e2e.py     # anthropic 미설치면 건너뜀
"""
import base64
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'scripts'))

PASS, FAIL = [], []


def check(name, cond, msg=''):
    (PASS if cond else FAIL).append(name)
    if not cond:
        print(f'  FAIL {name}  {msg}')


# 목 서버가 문항별로 돌려줄 판정. 실제 모델 출력 형태를 그대로 흉내낸다.
VERDICTS = {
    'AG0C1S0Aa1-01': {'solved': '내가 푼 값은 3, 보기 3번',
                      'answer_verdict': '불일치', 'confidence': '높음',
                      'findings': [{'code': 'AI_ANSWER_WRONG', 'where': '해설',
                                    'detail': '해설 2행에서 부호가 뒤집혔다',
                                    'evidence': 'c^2=a^2-b^2 여야 하는데 a^2+b^2 로 계산',
                                    'fix': '정답을 3번으로'}]},
    'AG0C1S0Aa1-02': {'solved': '1번', 'answer_verdict': '일치',
                      'confidence': '높음', 'findings': []},
    # 확신도 낮음 → 결함으로 올리지 않고 버려야 한다 (오탐 방어)
    'AG0C1S0Aa1-03': {'solved': '불명', 'answer_verdict': '불일치',
                      'confidence': '낮음',
                      'findings': [{'code': 'AI_ANSWER_WRONG', 'where': '본문',
                                    'detail': '틀린 것 같다', 'evidence': '감',
                                    'fix': ''}]},
    'AG0C1S0Aa1-04': {'solved': '그림 필요', 'answer_verdict': '판단불가',
                      'confidence': '낮음', 'findings': []},
}
REFUSED = 'AG0C1S0Aa1-05'      # stop_reason=refusal 로 돌려줄 문항
ERRORED = 'AG0C1S0Aa1-06'      # 배치 결과가 errored 인 문항

SEEN = []                      # 서버가 받은 요청 본문 (검증용)
RETRIEVES = []                 # 배치 조회 횟수 (폴링 루프 검증용)
# N번째 조회부터 ended 로 응답. 2보다 크게 두면 폴링 루프를 실제로 돌게 만든다 —
# 루프가 ended 전에 빠져나오면 results_url 이 없어 SDK가 예외를 던지므로 바로 잡힌다.
BATCH_ENDED_AFTER = 3


def _msg(loc, refusal=False):
    """Messages API 응답 1건. 구조화 출력이므로 text 블록이 곧 JSON이다."""
    return {
        'id': f'msg_{loc}', 'type': 'message', 'role': 'assistant',
        'model': 'claude-opus-5',
        'content': ([] if refusal else
                    [{'type': 'text',
                      'text': json.dumps(VERDICTS[loc], ensure_ascii=False)}]),
        'stop_reason': 'refusal' if refusal else 'end_turn',
        'stop_sequence': None,
        'usage': {'input_tokens': 1000, 'output_tokens': 2000,
                  'cache_creation_input_tokens': 0,
                  'cache_read_input_tokens': 0},
    }


def _sse(msg):
    """비스트리밍 응답 하나를 SDK가 받아들이는 SSE 시퀀스로 변환."""
    text = msg['content'][0]['text'] if msg['content'] else ''
    ev = [('message_start', {'type': 'message_start',
                             'message': {**msg, 'content': [],
                                         'stop_reason': None}})]
    if text:
        ev += [
            ('content_block_start', {'type': 'content_block_start', 'index': 0,
                                     'content_block': {'type': 'text', 'text': ''}}),
            ('content_block_delta', {'type': 'content_block_delta', 'index': 0,
                                     'delta': {'type': 'text_delta', 'text': text}}),
            ('content_block_stop', {'type': 'content_block_stop', 'index': 0}),
        ]
    ev += [
        ('message_delta', {'type': 'message_delta',
                           'delta': {'stop_reason': msg['stop_reason'],
                                     'stop_sequence': None},
                           'usage': {'output_tokens': msg['usage']['output_tokens']}}),
        ('message_stop', {'type': 'message_stop'}),
    ]
    return ''.join(f'event: {n}\ndata: {json.dumps(d)}\n\n' for n, d in ev)


def _batch(status):
    return {
        'id': 'msgbatch_test', 'type': 'message_batch',
        'processing_status': status,
        'request_counts': {'processing': 0 if status == 'ended' else 6,
                           'succeeded': 6 if status == 'ended' else 0,
                           'errored': 0, 'canceled': 0, 'expired': 0},
        'created_at': '2026-07-30T00:00:00Z',
        'expires_at': '2026-07-31T00:00:00Z',
        'ended_at': '2026-07-30T00:05:00Z' if status == 'ended' else None,
        'archived_at': None, 'cancel_initiated_at': None,
        'results_url': ('http://127.0.0.1:%d/v1/messages/batches/msgbatch_test/results'
                        % PORT[0]) if status == 'ended' else None,
    }


PORT = [0]


def _text_body(body):
    """요청 본문의 user 컨텐츠에서 text 블록만 이어붙인다 (블록 리스트 구조)."""
    c = body['messages'][0]['content']
    if isinstance(c, str):
        return c
    return '\n'.join(b.get('text', '') for b in c if b.get('type') == 'text')


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, ctype='application/json', raw=None):
        body = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(200)
        self.send_header('content-type', ctype)
        self.send_header('content-length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get('content-length', 0))
        body = json.loads(self.rfile.read(n) or b'{}')
        path = self.path

        if path.endswith('/count_tokens'):
            SEEN.append(('count_tokens', body))
            return self._send({'input_tokens': 1234})

        if path.endswith('/batches'):
            SEEN.append(('batch_create', body))
            RETRIEVES.clear()
            return self._send(_batch('in_progress'))

        # 단건 메시지 (run_sync) — 우리는 스트리밍으로 호출한다
        SEEN.append(('message', body))
        loc = _text_body(body).split('\n')[0].split(': ')[1]
        msg = _msg(loc, refusal=(loc == REFUSED))
        if body.get('stream'):
            return self._send(None, 'text/event-stream', _sse(msg).encode())
        return self._send(msg)

    def do_GET(self):
        if self.path.endswith('/results'):
            lines = []
            # 순서를 일부러 뒤집는다 — custom_id로 맞추지 않으면 여기서 깨진다
            for loc in reversed(list(VERDICTS) + [REFUSED, ERRORED]):
                if loc == ERRORED:
                    r = {'type': 'errored',
                         'error': {'type': 'error',
                                   'error': {'type': 'api_error',
                                             'message': 'boom'}}}
                else:
                    r = {'type': 'succeeded',
                         'message': _msg(loc, refusal=(loc == REFUSED))}
                lines.append(json.dumps({'custom_id': loc, 'result': r}))
            return self._send(None, 'application/x-ndjson',
                              ('\n'.join(lines) + '\n').encode())

        RETRIEVES.append(self.path)
        status = 'ended' if len(RETRIEVES) >= BATCH_ENDED_AFTER else 'in_progress'
        return self._send(_batch(status))


def item(no, loc, ans=1):
    return {'no': no, 'loc': loc, 'q': f'본문 {no} $x ^{{2}}$', 'answer': ans,
            'opts': [f'${k}$' for k in range(1, 6)],
            'expl': f'풀이 {no}\n따라서 ${ans}$',
            'meta': {'문항id': loc, '난이도': '2', '지식단위': 'G0C1S0A'}}


def main():
    try:
        import anthropic                       # noqa: F401
    except ImportError:
        print('  (anthropic 미설치 — 실제 SDK 검증 생략. pip install anthropic)')
        return 0

    srv = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    PORT[0] = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ['ANTHROPIC_BASE_URL'] = f'http://127.0.0.1:{PORT[0]}'
    os.environ['ANTHROPIC_API_KEY'] = 'sk-ant-test'

    import ai_review as ai
    locs = list(VERDICTS) + [REFUSED, ERRORED]
    items = [item(i, l, ans=1) for i, l in enumerate(locs, 1)]

    # ── 1. run_sync: 실제 SSE 스트림을 SDK로 수신 ────────────────────
    SEEN.clear()
    sync_items = [i for i in items if i['loc'] != ERRORED]
    res, usage = ai.run_sync(sync_items)
    check('e2e.sync.전문항수신', set(res) == {i['loc'] for i in sync_items},
          str(sorted(res)))
    check('e2e.sync.판정파싱', res['AG0C1S0Aa1-01']['confidence'] == '높음',
          str(res.get('AG0C1S0Aa1-01'))[:80])
    check('e2e.sync.refusal분리', res[REFUSED] == {'error': 'refusal'},
          str(res.get(REFUSED)))
    check('e2e.sync.토큰누적',
          usage == {'in': 1000 * len(sync_items), 'out': 2000 * len(sync_items)},
          str(usage))

    # ── 2. 전송된 요청 본문(wire) 검증 ──────────────────────────────
    # 결함이 있어도 예외로 죽지 않고 '실패'로 보고해야 한다 → 전부 .get 체인으로 본다
    def dig(d, *keys, default=None):
        for k in keys:
            if isinstance(d, list):
                d = d[k] if isinstance(k, int) and len(d) > k else default
            elif isinstance(d, dict):
                d = d.get(k, default)
            else:
                return default
            if d is default:
                return default
        return d

    sent = [b for kind, b in SEEN if kind == 'message']
    check('e2e.wire.요청수', len(sent) == len(sync_items), str(len(sent)))
    b0 = sent[0] if sent else {}
    check('e2e.wire.모델', dig(b0, 'model') == 'claude-opus-5', str(dig(b0, 'model')))
    check('e2e.wire.스트리밍', dig(b0, 'stream') is True, str(dig(b0, 'stream')))
    check('e2e.wire.캐싱실림',
          dig(b0, 'system', 0, 'cache_control', 'type') == 'ephemeral',
          str(dig(b0, 'system'))[:90])
    check('e2e.wire.구조화출력',
          dig(b0, 'output_config', 'format', 'type') == 'json_schema'
          and dig(b0, 'output_config', 'format', 'schema', 'properties',
                  'confidence', 'enum') == ['높음', '보통', '낮음'],
          str(dig(b0, 'output_config'))[:140])
    check('e2e.wire.effort', dig(b0, 'output_config', 'effort') == 'high',
          str(dig(b0, 'output_config', 'effort')))
    check('e2e.wire.시스템동일', len({json.dumps(dig(b, 'system'), sort_keys=True,
                                            ensure_ascii=False)
                                 for b in sent}) == 1,
          '검수 기준이 문항마다 달라지면 프롬프트 캐시가 안 맞는다')
    # 문항 격리: 한 요청에 다른 문항이 섞이면 안 된다
    bodies = [_text_body(b) for b in sent]
    leak = [t for t in bodies if sum(l in t for l in locs) != 1]
    check('e2e.wire.문항격리', sent and not leak, f'{len(leak)}건 누출')
    check('e2e.wire.XML안보냄',
          all('<hp:' not in t and '<hs:' not in t for t in bodies))
    # 그림을 안 넘겼으면 image 블록이 없어야 한다 (쓸데없는 토큰을 태우지 않는다)
    check('e2e.wire.그림없음',
          all(not any(x.get('type') == 'image'
                      for x in dig(b, 'messages', 0, 'content', default=[]))
              for b in sent))

    # ── 2.5 멀티모달: 그림을 실제로 전송하는가 ──────────────────────
    SEEN.clear()
    fig_items = [dict(items[0], loc=locs[0],
                      q='본문 [그림 1] 에서', images=['imgA', 'imgB'])]
    png = (b'\x89PNG\r\n\x1a\n' + b'\x00' * 40)
    ai.run_sync(fig_items, images={'imgA': ('image/png', png)})   # imgB는 변환 실패
    blocks = dig([b for k, b in SEEN if k == 'message'][0],
                 'messages', 0, 'content', default=[])
    kinds = [x.get('type') for x in blocks]
    check('e2e.img.블록구성', kinds == ['text', 'text', 'image', 'text'], str(kinds))
    src = dig(blocks, 2, 'source', default={})
    check('e2e.img.base64전송',
          src.get('type') == 'base64' and src.get('media_type') == 'image/png'
          and base64.b64decode(src.get('data', '')) == png, str(src)[:100])
    check('e2e.img.라벨동행', dig(blocks, 1, 'text') == '[그림 1]',
          str(dig(blocks, 1, 'text')))
    check('e2e.img.누락고지', '첨부하지 못했다' in str(dig(blocks, 3, 'text')),
          str(dig(blocks, 3, 'text')))

    # ── 3. run_batch: 폴링 루프 + 순서 무관 custom_id 매칭 ───────────
    # ended 전에 루프를 빠져나오면 results_url 이 None 이라 SDK가 AnthropicError를
    # 던진다 — 즉 이 호출이 성공했다는 것 자체가 '끝까지 폴링했다'는 증거다.
    res_b, usage_b = ai.run_batch(items, poll=0)
    # SDK의 results()가 내부적으로 retrieve를 한 번 더 하므로 우리 폴링 횟수보다 1 크다
    check('e2e.batch.폴링함', len(RETRIEVES) >= BATCH_ENDED_AFTER,
          f'조회 {len(RETRIEVES)}회 (ended 되기 전까지 폴링해야 한다)')
    check('e2e.batch.전문항수신', set(res_b) == set(locs), str(sorted(res_b)))
    check('e2e.batch.역순에도정합',
          dig(res_b, 'AG0C1S0Aa1-01', 'findings', 0, 'code') == 'AI_ANSWER_WRONG',
          'custom_id 대신 순서로 맞추면 여기서 깨진다: '
          + str(dig(res_b, 'AG0C1S0Aa1-01'))[:80])
    check('e2e.batch.errored분리', res_b.get(ERRORED) == {'error': 'errored'},
          str(res_b.get(ERRORED))[:80])
    check('e2e.batch.refusal분리', res_b.get(REFUSED) == {'error': 'refusal'},
          str(res_b.get(REFUSED))[:80])
    # errored 문항은 message가 없으므로 토큰에 안 잡힌다
    check('e2e.batch.토큰누적', usage_b['in'] == 1000 * (len(locs) - 1),
          str(usage_b))

    # ── 4. review(): 결함 환산 + 실패 분리 ─────────────────────────
    findings, results, usage_r = ai.review(items, sync=False, poll=0)
    codes = [f['code'] for f in findings]
    check('e2e.review.결함1건', codes == ['AI_ANSWER_WRONG'], str(codes))
    f0 = findings[0] if findings else {}
    check('e2e.review.high', dig(f0, 'sev') == 'high'
          and dig(f0, 'loc') == 'AG0C1S0Aa1-01', str(f0)[:100])
    check('e2e.review.근거보존',
          '부호' in str(dig(f0, 'tail', default=''))
          and 'c^2' in str(dig(f0, 'evidence', default=''))
          and dig(f0, 'fix'), str(f0)[:160])
    check('e2e.review.확신도낮음버림', 'AG0C1S0Aa1-03' not in
          [f['loc'] for f in findings],
          '확신도 낮음이 결함으로 올라왔다 — 오탐 방어 실패')
    check('e2e.review.실패2건',
          sorted(x['loc'] for x in usage_r['failed']) == sorted([ERRORED, REFUSED]),
          str(usage_r['failed']))
    check('e2e.review.배치표시', usage_r['batch'] is True)

    # ── 5. 비용 환산 (Batch = 표준가의 50%) ────────────────────────
    exp = (usage_r['in'] / 1e6 * ai.PRICE_IN
           + usage_r['out'] / 1e6 * ai.PRICE_OUT) * 0.5
    check('e2e.cost.batch절반', abs(ai.cost(usage_r, True) - exp) < 1e-9,
          f'{ai.cost(usage_r, True)} vs {exp}')
    check('e2e.cost.sync2배',
          abs(ai.cost(usage_r, False) - 2 * ai.cost(usage_r, True)) < 1e-9)

    # ── 6. estimate(): count_tokens 경로 (검수 호출 0) ─────────────
    SEEN.clear()
    n_in = ai.estimate(items)
    kinds = {k for k, _ in SEEN}
    check('e2e.estimate.토큰수', n_in == 1234 * len(items), str(n_in))
    check('e2e.estimate.검수호출없음', kinds == {'count_tokens'}, str(kinds))

    # ── 7. 보고서 렌더링 (실제 판정으로) ───────────────────────────
    import report_html
    html = report_html.render(findings, {}, {}, ['t'],
                              items={i['loc']: i for i in items})
    check('e2e.report.근거표시', 'c^2' in html or 'c ^{2}' in html, 'AI 근거가 안 보인다')
    check('e2e.report.확신도표시', '확신도' in html and '높음' in html)
    check('e2e.report.재검산경고', '재검산' in html)

    srv.shutdown()
    print(f'\n실제 SDK 검증: 통과 {len(PASS)} / 실패 {len(FAIL)}')
    if FAIL:
        print('실패 목록:', FAIL)
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
