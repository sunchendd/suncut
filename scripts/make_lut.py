#!/usr/bin/env python3
"""make_lut —— 程序化生成温和电影感 .cube LUT(suncut 全片统一调色备选).

变换 = 分离调色(阴影偏青/高光偏暖) + S 曲线对比 + 微增饱和;
生成两个强度档供 quality_ab.py 盲评选用,胜者留在 looks/ 即全链生效.

用法: python3 scripts/make_lut.py            # 写 looks/*.cube
      python3 scripts/make_lut.py --dry      # 只打印参数
"""
import sys
from pathlib import Path

LOOKS = Path(__file__).resolve().parent.parent / "looks"

# (文件名, S曲线指数p, 分离调色幅度, 饱和倍率)
VARIANTS = [
    ("warm-film.cube", 1.06, 0.045, 1.04),        # 温和:几乎无损,只提质感
    ("teal-orange-strong.cube", 1.12, 0.080, 1.07),  # 加强:明显青橙对比
]


def _s_curve(x, p):
    """x^p/(x^p+(1-x)^p): p>1 加对比,0.5 处不动,端点收."""
    e = min(max(x, 1e-6), 1 - 1e-6)
    a, b = e ** p, (1 - e) ** p
    return a / (a + b)


def _clamp(x):
    return min(max(x, 0.0), 1.0)


def lut_entry(r, g, b, p, amt, sat):
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
    # 分离调色: 阴影去红加蓝(青),高光加红去蓝(暖)
    sw = max(0.0, (0.5 - luma) / 0.5) ** 2
    hw = max(0.0, (luma - 0.5) / 0.5) ** 2
    r = r - amt * sw + amt * hw
    b = b + amt * sw - amt * hw
    # S 曲线 + 饱和
    out = [_s_curve(c, p) for c in (r, g, b)]
    out = [_clamp(luma + (c - luma) * sat) for c in out]
    return out


def write_cube(path, p, amt, sat, size=33):
    lines = [f'TITLE "suncut {path.stem}"', f"LUT_3D_SIZE {size}",
             "DOMAIN_MIN 0.0 0.0 0.0", "DOMAIN_MAX 1.0 1.0 1.0"]
    step = 1.0 / (size - 1)
    for bi in range(size):            # cube 规范: red 最快, green 次之, blue 最外
        for gi in range(size):
            for ri in range(size):
                r, g, b = lut_entry(ri * step, gi * step, bi * step, p, amt, sat)
                lines.append(f"{r:.6f} {g:.6f} {b:.6f}")
    path.write_text("\n".join(lines) + "\n")
    return len(lines) - 4


def main():
    if "--dry" in sys.argv:
        for name, p, amt, sat in VARIANTS:
            print(f"{name}: S曲线p={p} 分离调色={amt} 饱和={sat}")
        return
    LOOKS.mkdir(exist_ok=True)
    for name, p, amt, sat in VARIANTS:
        n = write_cube(LOOKS / name, p, amt, sat)
        print(f"[make_lut] {LOOKS / name}  {n} 格点")


if __name__ == "__main__":
    main()
