#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_mutations.py — 검증의 검증. 코드를 일부러 망가뜨려 테스트가 정말 잡는지 본다.

통과만 하고 실패는 못 하는 테스트는 아무것도 보증하지 않는다. 여기서는
ai_review의 핵심 불변식을 하나씩 깨뜨리고, test_api_e2e가 그 돌연변이를
'실패'로 잡아내는지 확인한다. 하나라도 놓치면 그 불변식은 사실 검증되지
않고 있었다는 뜻이다.

실제로 이 검사가 잡아낸 것:
  · 결함이 있으면 깔끔한 실패가 아니라 KeyError로 죽던 e2e 단정 → .get 체인으로 교체
  · review()가 폴링 간격을 못 받아 테스트가 60초씩 잠들던 문제 → poll 인자 추가

  python tests/test_mutations.py     # anthropic 미설치면 건너뜀
"""
import contextlib
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'scripts'))
sys.path.insert(0, HERE)

MUTATIONS = []


def mutation(name, expect):
    """expect: 이 돌연변이가 실패시켜야 하는 체크 이름."""
    def deco(fn):
        MUTATIONS.append((name, expect, fn))
        return fn
    return deco


def _register(ai):
    """돌연변이 정의. 각각 되돌리는 함수를 반환한다."""

    @mutation('프롬프트 캐싱 제거', 'e2e.wire.캐싱실림')
    def _():
        orig = ai.build_params

        def patched(it, images=None):
            p = orig(it, images)
            p['system'] = [{'type': 'text', 'text': ai.SYSTEM}]
            return p
        ai.build_params = patched
        return lambda: setattr(ai, 'build_params', orig)

    @mutation('확신도 낮음도 결함으로 올림', 'e2e.review.확신도낮음버림')
    def _():
        orig = ai.SEV_BY_CONF
        ai.SEV_BY_CONF = {k: {c: 'high' for c in ('높음', '보통', '낮음')}
                          for k in orig}
        return lambda: setattr(ai, 'SEV_BY_CONF', orig)

    @mutation('등급을 확신도와 무관하게 고정', 'e2e.review.확신도낮음버림')
    def _():
        orig = ai.to_findings

        def patched(loc, no, answer, verdict):
            return [{'code': f['code'], 'sev': 'high', 'no': no, 'loc': loc,
                     'ans': answer, 'want': f.get('where', ''),
                     'tail': f.get('detail', ''), 'evidence': f.get('evidence', ''),
                     'fix': f.get('fix', ''), 'confidence': verdict.get('confidence'),
                     'solved': verdict.get('solved', ''), 'verdict': ''}
                    for f in verdict.get('findings', [])]
        ai.to_findings = patched
        return lambda: setattr(ai, 'to_findings', orig)

    @mutation('한 요청에 다른 문항 섞기', 'e2e.wire.문항격리')
    def _():
        orig = ai._item_text
        ai._item_text = (lambda it: orig(it)
                         + '\n\n[참고] AG0C1S0Aa1-02 AG0C1S0Aa1-03')
        return lambda: setattr(ai, '_item_text', orig)

    @mutation('구조화 출력 스키마 제거', 'e2e.wire.구조화출력')
    def _():
        orig = ai.build_params

        def patched(it, images=None):
            p = orig(it, images)
            p['output_config'] = {'effort': 'high'}
            return p
        ai.build_params = patched
        return lambda: setattr(ai, 'build_params', orig)

    @mutation('배치 결과를 custom_id 대신 순서로 매칭', 'e2e.batch.역순에도정합')
    def _():
        orig = ai.run_batch

        def patched(items, poll=30, progress=None, images=None):
            res, usage = orig(items, poll=poll, progress=progress, images=images)
            vals = list(res.values())
            return {it['loc']: vals[i] for i, it in enumerate(items)}, usage
        ai.run_batch = patched
        return lambda: setattr(ai, 'run_batch', orig)

    @mutation('그림을 첨부하지 않음', 'e2e.img.블록구성')
    def _():
        orig = ai._content
        ai._content = lambda it, images=None: [
            {'type': 'text', 'text': ai._item_text(it)}]
        return lambda: setattr(ai, '_content', orig)

    @mutation('변환 실패한 그림을 조용히 넘김', 'e2e.img.누락고지')
    def _():
        """없는 그림을 안 알리면 모델이 상상해서 판정한다 = 오탐."""
        orig = ai._content

        def patched(it, images=None):
            blocks = orig(it, images)
            return [b for b in blocks
                    if '첨부하지 못했다' not in b.get('text', '')]
        ai._content = patched
        return lambda: setattr(ai, '_content', orig)

    @mutation('그림 라벨 없이 이미지만 보냄', 'e2e.img.라벨동행')
    def _():
        """라벨이 없으면 어느 그림이 [그림 N]인지 모델이 알 수 없다."""
        orig = ai._content

        def patched(it, images=None):
            return [b for b in orig(it, images)
                    if not re.fullmatch(r'\[그림 \d+\]', b.get('text', ''))]
        ai._content = patched
        return lambda: setattr(ai, '_content', orig)

    @mutation('refusal을 정상 판정으로 처리', 'e2e.sync.refusal분리')
    def _():
        orig = ai.run_sync

        def patched(items, progress=None, images=None):
            res, usage = orig(items, progress=progress, images=images)
            for k, v in res.items():
                if v.get('error') == 'refusal':
                    res[k] = {'solved': '', 'answer_verdict': '일치',
                              'confidence': '높음', 'findings': []}
            return res, usage
        ai.run_sync = patched
        return lambda: setattr(ai, 'run_sync', orig)


def main():
    try:
        import anthropic                       # noqa: F401
    except ImportError:
        print('  (anthropic 미설치 — 돌연변이 검사 생략. pip install anthropic)')
        return 0

    import ai_review
    import test_api_e2e as e2e
    _register(ai_review)

    def run_once():
        e2e.PASS.clear(); e2e.FAIL.clear()
        e2e.SEEN.clear(); e2e.RETRIEVES.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            e2e.main()
        return set(e2e.FAIL)

    base = run_once()
    print(f'기준(무돌연변이): 실패 {len(base)}건 {sorted(base) or "없음"}')
    if base:
        print('  기준이 이미 실패한다 — 돌연변이 검사는 의미가 없다')
        return 1

    caught = 0
    for name, expect, setup in MUTATIONS:
        undo = setup()
        try:
            failed = run_once() - base
        finally:
            undo()
        hit = expect in failed
        caught += hit
        print(f"  {'잡음  ' if hit else '놓침!!'} {name}")
        print(f'         기대 {expect} / 실제 {sorted(failed) or "없음"}')

    print(f'\n돌연변이 {len(MUTATIONS)}개 중 {caught}개 검출')
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == '__main__':
    sys.exit(main())
