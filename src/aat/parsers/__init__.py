"""Document parser plugin registry."""

from aat.parsers.markdown_parser import MarkdownParser

PARSER_REGISTRY: dict[str, type] = {
    ".md": MarkdownParser,
    ".txt": MarkdownParser,
}

__all__ = [
    "MarkdownParser",
    "PARSER_REGISTRY",
]
