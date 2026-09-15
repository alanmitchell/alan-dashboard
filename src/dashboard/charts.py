"""Chart rendering: matplotlib figures in, inline SVG out.

Three details matter for embedding matplotlib output directly in a page:

* **Unique element ids.**  Half a dozen charts share one document here, and a
  duplicate id makes the browser resolve every reference to whichever copy came
  first -- a chart clipped to another chart's box.  Two mechanisms guard against
  it: each figure gets its own ``svg.hashsalt`` (which is what makes clip-path
  ids differ), and :func:`_clean` then namespaces every remaining id and
  reference per fragment and drops the decorative ones matplotlib emits for
  ``<g>`` grouping, which are never referenced by anything.
* **No XML prolog.**  ``<?xml ...?>`` is only valid at the very top of a
  document, so it is stripped before the fragment is inlined.
* **Text stays text.**  ``svg.fonttype = "none"`` keeps labels as ``<text>``
  rather than glyph outlines: far smaller, selectable, and it inherits the
  page's own font.  Metrics are measured with the bundled DejaVu Sans, but every
  label carries ``text-anchor``, so alignment survives font substitution.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402  (must follow the backend choice)
from matplotlib.ticker import MaxNLocator  # noqa: E402

from .theme import DARK, LIGHT, THEMES, Theme  # noqa: E402

_FONT_STACK = "DejaVu Sans, system-ui, -apple-system, Segoe UI, sans-serif"
_XML_PROLOG = re.compile(r"<\?xml[^>]*\?>\s*|<!DOCTYPE[^>]*>\s*", re.IGNORECASE)
_ID_ATTR = re.compile(r'\bid="([^"]+)"')
_ID_REF = re.compile(r'url\(#([^)]+)\)|(?:xlink:)?href="#([^"]+)"')

matplotlib.rcParams.update(
    {
        # Emit <text>, not outlined glyph paths. See the module docstring.
        "svg.fonttype": "none",
        "font.family": "sans-serif",
        # Bundled with matplotlib, so metrics are computed without a font
        # lookup (and without findfont warnings on a slim image).
        "font.sans-serif": ["DejaVu Sans"],
    }
)


def _namespace_ids(svg: str, prefix: str) -> str:
    """Make every id in one fragment unique to it, and drop the unused ones.

    Matplotlib labels its ``<g>`` elements (``figure_1``, ``axes_1``,
    ``xtick_3``...) for readability. Nothing references them, and repeated
    across charts they are simply duplicate ids in the output, so they go.
    """
    referenced = {
        name
        for match in _ID_REF.finditer(svg)
        for name in match.groups()
        if name
    }

    def rewrite_attr(match: re.Match) -> str:
        name = match.group(1)
        if name not in referenced:
            return ""
        return f'id="{prefix}{name}"'

    def rewrite_ref(match: re.Match) -> str:
        name = match.group(1) or match.group(2)
        if match.group(1):
            return f"url(#{prefix}{name})"
        return f'href="#{prefix}{name}"'

    svg = _ID_ATTR.sub(rewrite_attr, svg)
    return _ID_REF.sub(rewrite_ref, svg)


@dataclass
class Chart:
    """One chart, rendered per theme, plus the data behind it.

    The SVGs are marked ``aria-hidden`` in the template and ``rows`` is rendered
    as a real table, so the data is reachable without relying on the picture --
    and a screen reader never reads the same chart twice.
    """

    light_svg: str
    dark_svg: str
    columns: tuple[str, str]
    rows: list[tuple[str, str]] = field(default_factory=list)
    caption: str = ""

    def svg_for(self, theme_name: str) -> str:
        return self.dark_svg if theme_name == "dark" else self.light_svg


def _clean(svg: str, prefix: str) -> str:
    svg = _XML_PROLOG.sub("", svg).strip()
    # DejaVu Sans is what metrics were measured with but is absent on most
    # viewing machines; name it first and let the browser fall through.
    svg = svg.replace("'DejaVu Sans'", _FONT_STACK)
    svg = svg.replace("font-family:DejaVu Sans", f"font-family:{_FONT_STACK}")
    svg = _namespace_ids(svg, prefix)
    # The figure is sized in inches; let CSS control its width on the page.
    return svg.replace("<svg ", '<svg preserveAspectRatio="xMidYMid meet" ', 1)


def _new_figure(salt: str, theme: Theme, size: tuple[float, float]):
    matplotlib.rcParams["svg.hashsalt"] = f"{salt}-{theme.name}"
    figure, axes = plt.subplots(figsize=size)
    figure.patch.set_alpha(0.0)
    axes.patch.set_alpha(0.0)

    for side in ("top", "right"):
        axes.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        axes.spines[side].set_color(theme.axis)
        axes.spines[side].set_linewidth(1.0)

    axes.tick_params(colors=theme.muted, labelsize=9, length=0, pad=6)
    axes.grid(axis="y", color=theme.grid, linewidth=1.0)
    axes.set_axisbelow(True)
    return figure, axes


def _finish(figure, salt: str, theme: Theme) -> str:
    buffer = io.StringIO()
    figure.tight_layout(pad=0.4)
    figure.savefig(buffer, format="svg", transparent=True, bbox_inches="tight")
    plt.close(figure)
    return _clean(buffer.getvalue(), prefix=f"{salt}-{theme.name}-")


def _render_both(draw, salt: str, size: tuple[float, float]) -> tuple[str, str]:
    """Run ``draw(axes, theme)`` once per theme and return both SVG fragments."""
    rendered: dict[str, str] = {}
    for theme in THEMES:
        figure, axes = _new_figure(salt, theme, size)
        draw(axes, theme)
        rendered[theme.name] = _finish(figure, salt, theme)
    return rendered[LIGHT.name], rendered[DARK.name]


def line_chart(
    salt: str,
    labels: Sequence[str],
    series: Sequence[tuple[str, Sequence[float]]],
    *,
    unit: str = "",
    columns: tuple[str, str] | None = None,
    size: tuple[float, float] = (5.4, 2.2),
) -> Chart:
    """Change over time.  One or two series; a third would need a legend rethink."""

    def draw(axes, theme: Theme) -> None:
        for index, (name, values) in enumerate(series):
            axes.plot(
                range(len(labels)),
                values,
                color=theme.series[index % len(theme.series)],
                linewidth=2.0,
                solid_capstyle="round",
                label=name,
            )
        axes.set_xticks(range(len(labels)))
        axes.set_xticklabels(labels, rotation=0)
        axes.xaxis.set_major_locator(MaxNLocator(nbins=6, integer=True))
        axes.yaxis.set_major_locator(MaxNLocator(nbins=4))
        if unit:
            axes.yaxis.set_major_formatter(lambda value, _pos: f"{value:g}{unit}")
        # A single series is named by the panel title; a legend box would
        # just repeat it.
        if len(series) > 1:
            legend = axes.legend(
                loc="upper left",
                frameon=False,
                fontsize=9,
                ncol=len(series),
                handlelength=1.4,
                columnspacing=1.2,
            )
            for text in legend.get_texts():
                text.set_color(theme.secondary_ink)

    light, dark = _render_both(draw, salt, size)
    rows = [
        (label, "  /  ".join(f"{values[i]:g}{unit}" for _n, values in series))
        for i, label in enumerate(labels)
    ]
    default_columns = ("Time", " / ".join(name for name, _v in series) or "Value")
    return Chart(light, dark, columns or default_columns, rows)


def bar_chart(
    salt: str,
    labels: Sequence[str],
    values: Sequence[float],
    *,
    unit: str = "",
    columns: tuple[str, str] | None = None,
    size: tuple[float, float] = (5.4, 2.2),
) -> Chart:
    """Magnitude across categories.  Single series, baseline anchored at zero."""

    def draw(axes, theme: Theme) -> None:
        axes.bar(
            range(len(labels)),
            values,
            color=theme.series[0],
            # A 2px surface gap between neighbours; bars stay thin.
            width=0.62,
        )
        axes.set_xticks(range(len(labels)))
        axes.set_xticklabels(labels)
        axes.set_ylim(bottom=0)
        axes.yaxis.set_major_locator(MaxNLocator(nbins=4))
        if unit:
            axes.yaxis.set_major_formatter(lambda value, _pos: f"{value:g}{unit}")

    light, dark = _render_both(draw, salt, size)
    rows = [(label, f"{values[i]:g}{unit}") for i, label in enumerate(labels)]
    return Chart(light, dark, columns or ("Category", "Value"), rows)
