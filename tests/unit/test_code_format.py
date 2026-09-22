from html.parser import HTMLParser
from pathlib import Path

import pytest

from alert_receiver.code_format import code_block
from alert_receiver.ui import runbook_page


class CodeText(HTMLParser):
    def __init__(self, document: str):
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self.active = False
        self.feed(document)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "code":
            self.active = True
            self.blocks.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag == "code":
            self.active = False

    def handle_data(self, data: str) -> None:
        if self.active:
            self.blocks[-1] += data


@pytest.mark.parametrize(
    ("language", "source"),
    [
        ("promql", 'sum by (job) (rate(up{job="<script>&\\""}[5m])) > 0\n# observação'),
        ("powershell", '$x = "<img src=x onerror=alert(1)>"\n\tdocker logs --tail 100 api  '),
        ("sh", 'export X="a & b"\npython scripts/check.py --value 2\n'),
        ('unknown" onclick="x', '  <script>alert("x")</script>\r\n\t& # 123  '),
    ],
)
def test_highlight_preserves_exact_source_without_executable_markup(
    language: str, source: str
) -> None:
    rendered = code_block(source, language)
    assert CodeText(rendered).blocks == [source]
    assert "<script>" not in rendered
    assert "<img " not in rendered
    assert 'onclick="' not in rendered
    assert 'class="syntax-' in rendered if language in {"promql", "powershell", "sh"} else True


def test_runbook_fences_select_language_and_keep_unclosed_code() -> None:
    source = 'sum(up{job="api"})\n  # janela'
    rendered = runbook_page("replica", "# Consulta\n```promql\n" + source)
    assert CodeText(rendered).blocks == [source]
    assert 'class="language-promql"' in rendered
    assert 'class="syntax-function">sum' in rendered
    assert 'class="syntax-property">job' in rendered


def test_all_current_runbook_code_blocks_round_trip() -> None:
    for path in (Path(__file__).resolve().parents[2] / "docs" / "runbooks").glob("*.md"):
        # The receiver displays fenced source with line breaks, without fence markers.
        expected: list[str] = []
        language = None
        source: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("```"):
                if language is None:
                    language, source = line[3:].strip(), []
                else:
                    rendered = code_block("\n".join(source), language)
                    expected.append("\n".join(source))
                    assert CodeText(rendered).blocks == [expected[-1]]
                    assert 'class="syntax-' in rendered
                    language = None
            elif language is not None:
                source.append(line)
        assert expected, path.name
