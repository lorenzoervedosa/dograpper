"""Token counting utilities for dograpper chunks.

Encoding default: cl100k_base (GPT-4, GPT-3.5-turbo).
"""

import logging
from dataclasses import dataclass

import tiktoken

logger = logging.getLogger(__name__)

# Short alias → full tiktoken encoding name.
SUPPORTED_ENCODINGS = {
    "cl100k": "cl100k_base",       # GPT-4, GPT-4-turbo, GPT-3.5-turbo
    "o200k": "o200k_base",         # GPT-4o, GPT-4o-mini
    "p50k": "p50k_base",           # Codex, text-davinci-002/003
}


@dataclass
class TokenCount:
    """Result of a token count."""
    words: int
    tokens: int
    encoding: str


def check_encoding(encoding: str) -> None:
    """Raise ValueError if the alias or full tiktoken name is unknown (no download)."""
    if SUPPORTED_ENCODINGS.get(encoding, encoding) not in tiktoken.list_encoding_names():
        raise ValueError(
            f"Encoding '{encoding}' not recognized. "
            f"Supported options: {', '.join(SUPPORTED_ENCODINGS.keys())}, "
            f"or a full tiktoken name ({', '.join(tiktoken.list_encoding_names())})"
        )


def count_tokens(text: str, encoding: str = "cl100k") -> TokenCount:
    """Count tokens in the text using tiktoken.

    Args:
        text: text to count.
        encoding: encoding alias (key of SUPPORTED_ENCODINGS)
                  or the full tiktoken name (e.g. "cl100k_base").

    Returns:
        TokenCount with words, tokens, and the encoding used.

    Raises:
        ValueError: if the encoding is not recognized by tiktoken.
    """
    words = len(text.split())

    if words == 0:
        return TokenCount(words=0, tokens=0, encoding=encoding)

    # Resolve alias → full name
    enc_name = SUPPORTED_ENCODINGS.get(encoding, encoding)

    try:
        enc = tiktoken.get_encoding(enc_name)
    except ValueError:
        raise ValueError(
            f"Encoding '{encoding}' not recognized. "
            f"Supported options: {', '.join(SUPPORTED_ENCODINGS.keys())}"
        )

    tokens = len(enc.encode(text))
    return TokenCount(words=words, tokens=tokens, encoding=enc_name)


def count_tokens_file(filepath: str, encoding: str = "cl100k") -> TokenCount:
    """Read a file with tolerant encoding and count tokens."""
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    return count_tokens(text, encoding)


def format_token_summary(counts: list) -> str:
    """Format a token-count summary for CLI display.

    Args:
        counts: list of TokenCount, one per chunk.

    Returns:
        Formatted string with total, avg, min, max.
    """
    if not counts:
        return "  Tokens:          (no chunks processed)"

    total = sum(c.tokens for c in counts)
    avg = total // len(counts)
    min_t = min(c.tokens for c in counts)
    max_t = max(c.tokens for c in counts)
    encoding = counts[0].encoding

    lines = []
    lines.append(f"  Tokens per chunk: ~{avg:,} avg (min: {min_t:,}, max: {max_t:,})")
    lines.append(f"  Total tokens:    {total:,}")
    lines.append(f"  Encoding:        {encoding}")
    return "\n".join(lines)
