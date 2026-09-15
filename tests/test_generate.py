"""Whole-page generation: failure isolation and the atomic write."""

from __future__ import annotations

import re

import pytest

from dashboard import generate
from dashboard.sources.base import Metric, Panel, Source


class _Working(Source):
    key = "working"
    title = "Working"

    def collect(self, config):
        return self.panel(metrics=[Metric("Fine", "1")])


class _Exploding(Source):
    key = "exploding"
    title = "Exploding"

    def collect(self, config):
        raise RuntimeError("upstream is down")


def test_a_failing_source_costs_only_its_own_panel(monkeypatch, config):
    monkeypatch.setattr(generate, "all_sources", lambda: [_Exploding(), _Working()])
    panels = generate.collect_panels(config)

    broken, working = panels
    assert broken.key == "exploding"
    assert "upstream is down" in broken.error
    assert working.key == "working" and working.error == ""


def test_write_atomically_replaces_content_and_leaves_no_debris(tmp_path):
    target = tmp_path / "nested" / "index.html"
    generate.write_atomically(target, "first")
    generate.write_atomically(target, "second")

    assert target.read_text() == "second"
    assert [p.name for p in target.parent.iterdir()] == ["index.html"]


def test_write_atomically_keeps_the_old_page_when_rendering_fails(tmp_path):
    target = tmp_path / "index.html"
    generate.write_atomically(target, "good page")

    class _Unwritable(str):
        def __len__(self):  # pragma: no cover - not reached
            raise AssertionError

    with pytest.raises(TypeError):
        generate.write_atomically(target, object())  # type: ignore[arg-type]

    assert target.read_text() == "good page"
    assert list(target.parent.iterdir()) == [target]


def _render(config, panels):
    from datetime import datetime

    return generate.render(config, panels, datetime.now(config.timezone))


def test_page_renders_every_panel(config):
    panels = [
        Panel(key="one", title="One", metrics=[Metric("Now", "21", "°C")]),
        Panel(key="two", title="Two", empty_message="Nothing here."),
    ]
    html = _render(config, panels)

    assert re.findall(r'id="panel-(\w+)"', html) == ["one", "two"]
    assert "21" in html and "Nothing here." in html
    assert html.lstrip().startswith("<!doctype html>")


def test_stylesheet_is_inlined_so_the_page_stands_alone(config):
    html = _render(config, [Panel(key="a", title="A")])
    assert "<style>" in html
    assert 'rel="stylesheet"' not in html
    assert "--surface" in html


def test_error_and_stub_states_are_visible_to_the_reader(config):
    panels = [
        Panel(key="bad", title="Bad", error="boom"),
        Panel(key="fake", title="Fake", stub=True),
    ]
    html = _render(config, panels)
    assert "Could not refresh." in html and "boom" in html
    assert ">Sample data<" in html


def test_event_text_is_escaped(config):
    """Calendar summaries are third-party text and land straight in the page."""
    from dashboard.sources.base import Item

    nasty = '<script>alert("x")</script>'
    html = _render(config, [Panel(key="c", title="C", items=[Item(primary=nasty)])])
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_page_refreshes_itself(config):
    html = _render(config, [Panel(key="a", title="A")])
    assert f'content="{config.refresh_seconds}"' in html


def test_main_writes_the_page(monkeypatch, config):
    monkeypatch.setattr(generate, "all_sources", lambda: [_Working(), _Exploding()])
    assert generate.main() == 0
    assert config.index_path.exists()
    assert "Working" in config.index_path.read_text()


def test_inlined_stylesheet_is_not_mangled_by_escaping(config):
    """The stylesheet bypasses autoescaping on purpose; if that ever regresses,
    quoted font names turn into &quot; inside <style> and the stack breaks."""
    html = _render(config, [Panel(key="a", title="A")])
    assert '"Segoe UI"' in html
    assert "&quot;Segoe UI&quot;" not in html


def test_chart_svg_survives_escaping(config):
    from dashboard.charts import bar_chart

    panel = Panel(key="a", title="A", chart=bar_chart("t", ["Mon"], [1.0]))
    html = _render(config, [panel])
    assert "<svg" in html and "&lt;svg" not in html
