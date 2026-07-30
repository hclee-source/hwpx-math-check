#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hwpx_images.py — hwpx에 박힌 그림을 꺼내 Claude vision이 받는 형식으로 바꾼다.

왜 필요한가: 기하 문항은 그림이 있어야 풀리는 게 많다. 텍스트만 보내면 AI가
`판단불가`로 되돌릴 수밖에 없다. 그림을 붙이면 그 문항들도 검수 대상이 된다.

구조 (한글이 저장한 hwpx):
  Contents/content.hpf   <opf:item id="image1" href="BinData/image1.bmp"
                                   media-type="image/bmp"/>   ← 매니페스트
  Contents/section0.xml  <hp:pic><hc:img binaryItemIDRef="image1"/></hp:pic>
  BinData/image1.bmp     실제 바이너리

**BMP는 Claude vision이 받지 않으므로 PNG로 바꿔야 한다.** 여기 들어 있는
변환기는 24bpp 무압축 BMP 전용이고 표준 라이브러리(zlib·struct)만 쓴다 —
한글이 넣는 그림이 전부 그 형식이라, Pillow를 의존성으로 추가하지 않았다.
그 밖의 변종은 조용히 건너뛴다(그림 하나 때문에 검수 전체가 죽으면 안 된다).
"""
import re
import struct
import zlib
import zipfile

MANIFEST = re.compile(r'<opf:item\b([^>]*)/>')
ATTR = re.compile(r'\b([\w:-]+)="([^"]*)"')
# Claude vision이 받는 형식. 이 외에는 변환하거나 버린다.
PASSTHROUGH = {'image/png', 'image/jpeg', 'image/gif', 'image/webp'}


def _png(width, height, rgb_rows):
    """RGB 행 리스트 → PNG 바이트. 필터 0(None) 고정."""
    def chunk(tag, data):
        return (struct.pack('>I', len(data)) + tag + data
                + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)  # 8bit truecolor
    raw = b''.join(b'\x00' + row for row in rgb_rows)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
            + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


def bmp_to_png(raw):
    """24bpp 무압축 BMP → PNG. 그 외 변종은 ValueError.

    BMP는 행이 4바이트 배수로 패딩되고, 기본이 아래에서 위로(bottom-up) 저장되며
    픽셀 순서가 BGR이다. 셋 다 되돌려야 PNG가 된다.
    """
    if raw[:2] != b'BM' or len(raw) < 54:
        raise ValueError('BMP 아님')
    data_off = struct.unpack('<I', raw[10:14])[0]
    hdr_size, w, h, planes, bpp, comp = struct.unpack('<IiiHHI', raw[14:34])
    if bpp != 24 or comp != 0:
        raise ValueError(f'미지원 BMP: {bpp}bpp compression={comp}')
    bottom_up = h > 0
    h = abs(h)
    if w <= 0 or h <= 0:
        raise ValueError(f'잘못된 크기 {w}x{h}')

    stride = (w * 3 + 3) & ~3            # 행 길이를 4바이트 배수로 패딩
    need = data_off + stride * h
    if len(raw) < need:
        raise ValueError(f'데이터 부족: {len(raw)} < {need}')

    rows = []
    for y in range(h):
        s = data_off + stride * y
        line = raw[s:s + w * 3]
        rows.append(bytes(line[i + 2 - j] for i in range(0, w * 3, 3)
                          for j in range(3)))     # BGR → RGB
    if bottom_up:
        rows.reverse()
    return _png(w, h, rows)


def load(path):
    """hwpx → {image_id: (media_type, bytes)}. BMP는 PNG로 변환해 담는다.

    변환 실패한 그림은 결과에서 빠진다 — 호출자는 id가 없으면 '그림 없음'으로
    다루면 된다.
    """
    out = {}
    with zipfile.ZipFile(path) as z:
        try:
            hpf = z.read('Contents/content.hpf').decode('utf-8', 'replace')
        except KeyError:
            return out
        names = set(z.namelist())
        for m in MANIFEST.finditer(hpf):
            a = dict(ATTR.findall(m.group(1)))
            iid, href = a.get('id'), a.get('href')
            mtype = a.get('media-type', '')
            if not (iid and href) or not mtype.startswith('image/'):
                continue
            if href not in names:
                continue
            raw = z.read(href)
            if mtype in PASSTHROUGH:
                out[iid] = (mtype, raw)
                continue
            try:
                out[iid] = ('image/png', bmp_to_png(raw))
            except ValueError:
                pass                     # 그림 하나 때문에 검수를 멈추지 않는다
    return out


if __name__ == '__main__':
    import argparse
    import os
    ap = argparse.ArgumentParser(description='hwpx 그림 추출 (BMP→PNG)')
    ap.add_argument('hwpx')
    ap.add_argument('--dump', help='PNG를 이 디렉터리에 저장')
    a = ap.parse_args()

    imgs = load(a.hwpx)
    with zipfile.ZipFile(a.hwpx) as z:
        n_manifest = sum(1 for m in MANIFEST.finditer(
            z.read('Contents/content.hpf').decode('utf-8', 'replace'))
            if 'image/' in m.group(1))
    print(f'그림 {len(imgs)}/{n_manifest}개 변환 '
          f'(실패 {n_manifest - len(imgs)}개는 미지원 변종)')
    for iid, (mt, data) in list(imgs.items())[:5]:
        print(f'  {iid}: {mt} {len(data):,}B')
    if a.dump:
        os.makedirs(a.dump, exist_ok=True)
        for iid, (mt, data) in imgs.items():
            ext = mt.split('/')[1]
            open(os.path.join(a.dump, f'{iid}.{ext}'), 'wb').write(data)
        print(f'→ {a.dump}')
