"""아이콘 PNG 생성 (외부 라이브러리 없이). icon.svg와 같은 디자인을 래스터화한다.

    python energy/tools/make_icons.py
"""
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "app" / "public"
SS = 3  # 슈퍼샘플링 배수


def rounded_rect(x0, y0, x1, y1, r):
    def inside(x, y):
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            return False
        cx = x0 + r if x < x0 + r else (x1 - r if x > x1 - r else x)
        cy = y0 + r if y < y0 + r else (y1 - r if y > y1 - r else y)
        return (x - cx) ** 2 + (y - cy) ** 2 <= r * r
    return inside


def polygon(points):
    def inside(x, y):
        n = len(points)
        c = False
        j = n - 1
        for i in range(n):
            xi, yi = points[i]
            xj, yj = points[j]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                c = not c
            j = i
        return c
    return inside


def render(size):
    s = size * SS
    px = bytearray(s * s * 3)
    u = s / 512.0

    def shape(test, color):
        r, g, b = color
        for y in range(s):
            yy = y / u
            row = y * s * 3
            for x in range(s):
                if test(x / u, yy):
                    i = row + x * 3
                    px[i] = r
                    px[i + 1] = g
                    px[i + 2] = b

    shape(rounded_rect(0, 0, 512, 512, 0), (0x11, 0x18, 0x28))  # 마스크는 OS가 적용
    shape(rounded_rect(116, 150, 396, 190, 20), (0x1f, 0x2a, 0x44))
    shape(rounded_rect(116, 150, 320, 190, 20), (0x34, 0xd3, 0x99))
    shape(rounded_rect(116, 226, 396, 266, 20), (0x1f, 0x2a, 0x44))
    shape(rounded_rect(116, 226, 272, 266, 20), (0x60, 0xa5, 0xfa))
    shape(polygon([(266, 292), (214, 392), (256, 392), (240, 458), (306, 358), (262, 358)]), (0xfb, 0xbf, 0x24))

    # 다운샘플
    out = bytearray()
    for y in range(size):
        out.append(0)  # PNG 필터 타입
        for x in range(size):
            r = g = b = 0
            for dy in range(SS):
                base = ((y * SS + dy) * s + x * SS) * 3
                for dx in range(SS):
                    i = base + dx * 3
                    r += px[i]
                    g += px[i + 1]
                    b += px[i + 2]
            n = SS * SS
            out += bytes((r // n, g // n, b // n))
    return bytes(out)


def write_png(path, size):
    raw = render(size)

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)
    print(f"[icon] {path.name} ({size}x{size}, {len(png)}B)")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    write_png(OUT / "icon-180.png", 180)
    write_png(OUT / "icon-512.png", 512)
