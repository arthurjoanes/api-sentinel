"""Small, offline token highlighter for the languages used by the runbooks.

This is presentation only: every character is escaped and preserved, and no
command is parsed for execution. Unknown languages remain plain text.
"""

import re
from html import escape

_ALIASES = {"ps1": "powershell", "bash": "sh", "shell": "sh"}
_PATTERNS = {
    "promql": re.compile(
        r"(?P<comment>\#[^\n]*)"
        r'|(?P<string>"(?:\\.|[^"\\])*"|\x27(?:\\.|[^\x27\\])*\x27|`[^`]*`)'
        r"|(?P<keyword>\b(?:by|without|on|ignoring|group_left|group_right|bool|offset|and|or|unless)\b)"
        r"|(?P<number>(?<![\w:])(?:\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)(?:ms|[smhdwy])?\b)"
        r"|(?P<function>[a-zA-Z_][\w:]*(?=\s*\())"
        r"|(?P<property>[a-zA-Z_][\w:]*(?=\s*(?:=~|!~|!=|=)))"
        r"|(?P<operator>=~|!~|!=|==|>=|<=|[+*/%^=<>-])"
    ),
    "powershell": re.compile(
        r"(?P<comment>\#[^\n]*)"
        r'|(?P<string>"(?:`.|[^"`])*"|\x27(?:\x27\x27|[^\x27])*\x27)'
        r"|(?P<variable>\$(?:\{[^}]*\}|[\w:]+))"
        r"|(?P<keyword>\b(?:if|else|elseif|foreach|while|function|param|return|try|catch)\b)"
        r"|(?P<command>\b(?:docker|python|python3|curl|Invoke-RestMethod|Invoke-WebRequest)\b)"
        r"|(?P<property>(?<!\S)--?[a-zA-Z][\w-]*)"
        r"|(?P<number>(?<![\w.-])\d+(?:\.\d+)?(?![\w.-]))"
        r"|(?P<operator>[|=&;])",
        re.IGNORECASE,
    ),
    "sh": re.compile(
        r"(?P<comment>\#[^\n]*)"
        r'|(?P<string>"(?:\\.|[^"\\])*"|\x27[^\x27]*\x27)'
        r"|(?P<variable>\$(?:\{[^}]*\}|[\w]+))"
        r"|(?P<keyword>\b(?:if|then|else|fi|for|do|done|in|export)\b)"
        r"|(?P<command>\b(?:docker|python|python3|curl)\b)"
        r"|(?P<property>(?<!\S)--?[a-zA-Z][\w-]*)"
        r"|(?P<number>(?<![\w.-])\d+(?:\.\d+)?(?![\w.-]))"
        r"|(?P<operator>[|=&;])"
    ),
}
_LABELS = {"promql": "PromQL", "powershell": "PowerShell", "sh": "Shell", "text": "Texto"}


def code_block(source: str, language: str) -> str:
    """Return highlighted HTML with an exact source textContent, including whitespace."""
    language = _ALIASES.get(language.lower(), language.lower())
    if language not in _PATTERNS:
        language = "text"
    pattern = _PATTERNS.get(language)
    fragments: list[str] = []
    cursor = 0
    if pattern is not None:
        for token in pattern.finditer(source):
            fragments.append(escape(source[cursor : token.start()]))
            fragments.append(
                f'<span class="syntax-{token.lastgroup}">{escape(token.group())}</span>'
            )
            cursor = token.end()
    fragments.append(escape(source[cursor:]))
    label = _LABELS[language]
    return (
        f'<div class="code-block"><span class="code-language">{label}</span>'
        f'<pre tabindex="0" aria-label="Código {label}"><code class="language-{language}">'
        + "".join(fragments)
        + "</code></pre></div>"
    )
