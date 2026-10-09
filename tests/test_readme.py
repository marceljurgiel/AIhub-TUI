"""The README renders on GitHub as written."""
import os

README = os.path.join(os.path.dirname(os.path.dirname(__file__)), "README.md")


def test_every_html_line_is_closed_by_a_blank_line():
    """An HTML block (a centred image) runs until a blank line: Markdown
    right below it — a list item — shows on GitHub as raw text (**Memory**)."""
    lines = open(README, encoding="utf-8").read().splitlines()
    stuck = [i + 1 for i, line in enumerate(lines[:-1])
             if line.startswith("<p ") and lines[i + 1].strip()
             and not lines[i + 1].startswith("<p ")]
    assert stuck == [], f"README lines followed by Markdown with no blank line: {stuck}"
