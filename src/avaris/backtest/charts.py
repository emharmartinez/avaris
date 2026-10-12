from collections.abc import Callable
from html import escape

import numpy as np
import pandas as pd

# Static SVG for the markdown report: the default validated categorical slots 1-3 on an
# explicit light surface, so the charts read the same in light and dark viewers
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
REFERENCE = "#9a9993"
SERIES = ("#2a78d6", "#eb6834", "#1baf7a")
FAMILY = "font-family='system-ui, sans-serif'"
FONT = f"{FAMILY} font-size='12'"
WIDTH, HEIGHT = 440, 380
LEFT, RIGHT, TOP, BOTTOM = 56, 20, 64, 48


def _frame(title: str) -> list[str]:
    return [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{WIDTH}' height='{HEIGHT}' "
        f"viewBox='0 0 {WIDTH} {HEIGHT}' role='img' aria-label='{escape(title)}'>",
        f"<title>{escape(title)}</title>",
        f"<rect width='{WIDTH}' height='{HEIGHT}' fill='{SURFACE}'/>",
        f"<text x='{LEFT}' y='22' {FAMILY} font-size='14' font-weight='600' fill='{INK}'>"
        f"{escape(title)}</text>",
    ]


def _axes(
    x_ticks: list[float], y_ticks: list[float], sx: Callable[[float], float],
    sy: Callable[[float], float], x_label: str,
    y_label: str, x_fmt: str = "{:.1f}", y_fmt: str = "{:.1f}",
) -> list[str]:
    out = []
    for t in y_ticks:
        y = sy(t)
        out.append(f"<line x1='{LEFT}' x2='{WIDTH - RIGHT}' y1='{y:.1f}' y2='{y:.1f}' "
                   f"stroke='{GRID}' stroke-width='1'/>")
        out.append(f"<text x='{LEFT - 8}' y='{y + 4:.1f}' {FONT} fill='{INK_2}' "
                   f"text-anchor='end'>{y_fmt.format(t)}</text>")
    for t in x_ticks:
        x = sx(t)
        out.append(f"<text x='{x:.1f}' y='{HEIGHT - BOTTOM + 18}' {FONT} fill='{INK_2}' "
                   f"text-anchor='middle'>{x_fmt.format(t)}</text>")
    out.append(f"<text x='{(LEFT + WIDTH - RIGHT) / 2}' y='{HEIGHT - 10}' {FONT} "
               f"fill='{INK_2}' text-anchor='middle'>{escape(x_label)}</text>")
    mid = (TOP + HEIGHT - BOTTOM) / 2
    out.append(f"<text x='14' y='{mid}' {FONT} fill='{INK_2}' text-anchor='middle' "
               f"transform='rotate(-90 14 {mid})'>{escape(y_label)}</text>")
    return out


def _legend(names: list[str], colors: list[str]) -> list[str]:
    out, x = [], LEFT
    for name, color in zip(names, colors, strict=True):
        out.append(f"<rect x='{x}' y='36' width='10' height='10' rx='2' fill='{color}'/>")
        out.append(f"<text x='{x + 14}' y='45' {FONT} fill='{INK}'>{escape(name)}</text>")
        x += 24 + 7 * len(name)
    return out


def reliability_svg(series: dict[str, pd.DataFrame], title: str) -> str:
    # Mean predicted probability vs observed home-win frequency per bin; the diagonal is
    # perfect calibration
    x0, x1, y0, y1 = LEFT, WIDTH - RIGHT, HEIGHT - BOTTOM, TOP

    def sx(v: float) -> float:
        return x0 + v * (x1 - x0)

    def sy(v: float) -> float:
        return y0 - v * (y0 - y1)

    ticks = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    out = _frame(title) + _axes(ticks, ticks, sx, sy, "Predicted home win probability",
                                "Observed home win rate")
    out.append(f"<line x1='{sx(0)}' y1='{sy(0)}' x2='{sx(1)}' y2='{sy(1)}' "
               f"stroke='{REFERENCE}' stroke-width='1.5' stroke-dasharray='4 4'/>")
    names = list(series)
    colors: list[str] = list(SERIES[: len(names)])
    for name, color in zip(names, colors, strict=True):
        t = series[name]
        points = " ".join(f"{sx(p):.1f},{sy(f):.1f}" for p, f in zip(t["mean_p"], t["freq"],
                                                                        strict=True))
        out.append(f"<polyline points='{points}' fill='none' stroke='{color}' "
                   f"stroke-width='2' stroke-linejoin='round'/>")
        for r in t.to_dict("records"):
            out.append(
                f"<circle cx='{sx(r['mean_p']):.1f}' cy='{sy(r['freq']):.1f}' r='4' "
                f"fill='{color}' stroke='{SURFACE}' stroke-width='2'><title>"
                f"{escape(name)}: predicted {r['mean_p']:.3f}, observed {r['freq']:.3f}, "
                f"{int(r['n'])} games</title></circle>"
            )
    out += _legend(names, colors)
    out.append("</svg>")
    return "\n".join(out)


def pit_svg(counts: np.ndarray, title: str) -> str:
    # PIT histogram: flat bars at the uniform line mean the N(mu, sigma) spread is right;
    # a U shape means sigma is too small, a hump means too large
    bins = len(counts)
    expected = counts.sum() / bins
    top = max(float(counts.max()), expected) * 1.1
    x0, x1, y0, y1 = LEFT, WIDTH - RIGHT, HEIGHT - BOTTOM, TOP
    width = (x1 - x0) / bins

    def sx(v: float) -> float:
        return x0 + v * (x1 - x0)

    def sy(v: float) -> float:
        return y0 - v / top * (y0 - y1)

    step = _nice_step(top)
    y_ticks = [float(v) for v in np.arange(0, top, step)]
    out = _frame(title) + _axes([0.0, 0.5, 1.0], y_ticks, sx, sy, "PIT value", "Games",
                                y_fmt="{:.0f}")
    for i, c in enumerate(counts):
        left, right, y = x0 + i * width + 1, x0 + (i + 1) * width - 1, sy(float(c))
        r = min(4.0, (y0 - y) / 2, (right - left) / 2)
        out.append(
            f"<path d='M{left:.1f},{y0} V{y + r:.1f} Q{left:.1f},{y:.1f} {left + r:.1f},"
            f"{y:.1f} H{right - r:.1f} Q{right:.1f},{y:.1f} {right:.1f},{y + r:.1f} "
            f"V{y0} Z' fill='{SERIES[0]}'><title>PIT {i / bins:.1f}-{(i + 1) / bins:.1f}: "
            f"{int(c)} games</title></path>"
        )
    ey = sy(expected)
    out.append(f"<line x1='{x0}' x2='{x1}' y1='{ey:.1f}' y2='{ey:.1f}' stroke='{REFERENCE}' "
               f"stroke-width='1.5' stroke-dasharray='4 4'/>")
    out.append(f"<text x='{x1}' y='{ey - 6:.1f}' {FONT} fill='{INK_2}' text-anchor='end'>"
               f"uniform</text>")
    out.append("</svg>")
    return "\n".join(out)


def _nice_step(top: float) -> float:
    raw = top / 5
    magnitude = 10 ** np.floor(np.log10(raw))
    return float(next(m * magnitude for m in (1, 2, 5, 10) if m * magnitude >= raw))
