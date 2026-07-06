from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "web/styles.css").read_text()


def test_interactive_controls_have_focus_visible_ring():
    selector = re.search(
        r":where\(button, input, textarea, select, \[tabindex\]\):focus-visible\s*\{([^}]+)\}",
        CSS,
    )
    assert selector
    assert "outline: 3px solid var(--focus-ring)" in selector.group(1)
    assert "outline-offset: 2px" in selector.group(1)


def test_light_and_dark_themes_define_focus_color():
    assert CSS.count("--focus-ring:") == 2
    assert "--focus-ring: #005fcc" in CSS
    assert "--focus-ring: #8bd5ff" in CSS


def test_composer_exposes_focus_without_suppressing_controls_globally():
    assert ".composer:focus-within" in CSS
    assert "outline: none" not in CSS
