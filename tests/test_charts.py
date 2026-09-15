"""Charts are embedded as inline SVG fragments in a shared document, so the
things worth testing are the document-level invariants, not the pixels."""

from __future__ import annotations

import re

from dashboard.charts import _namespace_ids, bar_chart, line_chart

_ID_ATTR = re.compile(r'\bid="([^"]+)"')
_ID_REF = re.compile(r'url\(#([^)]+)\)|(?:xlink:)?href="#([^"]+)"')


def _ids(markup: str) -> list[str]:
    return _ID_ATTR.findall(markup)


def _refs(markup: str) -> set[str]:
    return {name for match in _ID_REF.finditer(markup) for name in match.groups() if name}


def test_namespace_ids_drops_ids_nothing_points_at():
    svg = '<g id="figure_1"><g id="axes_1"><rect id="patch_1"/></g></g>'
    assert _namespace_ids(svg, "x-") == "<g ><g ><rect /></g></g>"


def test_namespace_ids_rewrites_both_kinds_of_reference():
    svg = (
        '<clipPath id="pabc"><rect/></clipPath>'
        '<g clip-path="url(#pabc)"><use xlink:href="#glyph" x="1"/></g>'
        '<path id="glyph" d="M0 0"/>'
    )
    out = _namespace_ids(svg, "chart1-")
    assert 'id="chart1-pabc"' in out
    assert "url(#chart1-pabc)" in out
    assert 'href="#chart1-glyph"' in out
    assert 'id="chart1-glyph"' in out
    # Every reference still resolves.
    assert _refs(out) <= set(_ids(out))


def test_charts_sharing_a_document_have_no_duplicate_ids():
    """Regression: several inlined SVGs previously collided on matplotlib's
    element ids, so a reference resolved to whichever copy came first."""
    first = bar_chart("alpha", ["Mon", "Tue", "Wed"], [1.0, 2.0, 3.0])
    second = line_chart("beta", ["1", "2", "3"], [("Indoor", [20.0, 21.0, 22.0])])

    document = "".join(
        [first.light_svg, first.dark_svg, second.light_svg, second.dark_svg]
    )
    ids = _ids(document)
    assert ids, "expected the SVGs to carry at least one referenced id"
    assert len(ids) == len(set(ids)), "duplicate ids across inlined charts"
    assert _refs(document) <= set(ids), "a reference points at nothing"


def test_fragments_are_inlinable():
    chart = bar_chart("gamma", ["a"], [1.0])
    for svg in (chart.light_svg, chart.dark_svg):
        # An XML prolog is only legal at the very top of a document.
        assert not svg.lstrip().startswith("<?xml")
        assert "<!DOCTYPE" not in svg
        assert svg.lstrip().startswith("<svg")


def test_labels_stay_as_text_not_outlines():
    """svg.fonttype='none' keeps the page small and the text selectable."""
    chart = bar_chart("delta", ["Mon", "Tue"], [1.0, 2.0])
    assert "<text" in chart.light_svg
    assert "DejaVuSans-" not in chart.light_svg


def test_themes_render_with_their_own_palettes():
    chart = bar_chart("epsilon", ["a", "b"], [1.0, 2.0])
    assert "#2a78d6" in chart.light_svg  # light categorical slot 1
    assert "#3987e5" in chart.dark_svg  # dark step of the same hue
    assert chart.light_svg != chart.dark_svg


def test_bar_chart_table_mirrors_the_data():
    chart = bar_chart("zeta", ["Mon", "Tue"], [1.5, 2.0], unit=" kWh",
                      columns=("Day", "Use"))
    assert chart.columns == ("Day", "Use")
    assert chart.rows == [("Mon", "1.5 kWh"), ("Tue", "2 kWh")]


def test_line_chart_table_covers_every_series():
    chart = line_chart(
        "eta",
        ["1", "2"],
        [("Indoor", [20.0, 21.0]), ("Outdoor", [5.0, 6.0])],
        unit="°",
    )
    assert chart.rows == [("1", "20°  /  5°"), ("2", "21°  /  6°")]
    assert chart.columns == ("Time", "Indoor / Outdoor")


def test_svg_for_picks_the_requested_theme():
    chart = bar_chart("theta", ["a"], [1.0])
    assert chart.svg_for("dark") == chart.dark_svg
    assert chart.svg_for("light") == chart.light_svg
    assert chart.svg_for("anything-else") == chart.light_svg


def test_single_series_line_chart_has_no_legend():
    """One series is already named by the panel heading."""
    chart = line_chart("iota", ["1", "2"], [("Only", [1.0, 2.0])])
    assert "Only" not in chart.light_svg
