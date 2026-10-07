"""Korean morphological tokenization with Kiwi (kiwipiepy).

Only content morphemes are kept for BM25. Dropped: punctuation/symbol tags, particles (J*), endings (E*),
suffixes (XS*) and the copulas 이다/아니다 (VCP, VCN), so "세종이" and "세종은" both become ["세종"] and
documents that share only grammatical morphemes (은, 되, 었, 나, ...) with a query do not match it.
Nouns, verb/adjective stems, adverbs, numbers (SN), Latin (SL), Hanja (SH) and Kiwi's W_* tokens (dates,
times) are kept because years like "1443" matter for freshness and conflict checks. Forms are lowercased.

`tokenizer_config()` describes this setting; it is stored in the index manifest and must match at load time.
"""

from __future__ import annotations

import threading

TOKENIZER_NAME = "kiwi-morph"
# Matched with str.startswith, so "J" covers JKS/JKO/JX/JC..., "E" covers EP/EF/EC/ETN/ETM and "XS" covers
# XSN/XSV/XSA (and irregular forms such as XSA-I).
# Kiwi punctuation / symbol tags: SF . ? !, SP , / : ;, SS* quotes and brackets, SE ellipsis,
# SO dashes, SW other symbols, SB list bullets.
PUNCT_TAG_PREFIXES = ("SF", "SP", "SS", "SE", "SO", "SW", "SB")
# Grammatical morphemes: particles, endings, suffixes, positive/negative copula.
GRAMMAR_TAG_PREFIXES = ("J", "E", "XS", "VCP", "VCN")
DROP_TAG_PREFIXES = PUNCT_TAG_PREFIXES + GRAMMAR_TAG_PREFIXES
LOWERCASE = True

_kiwi = None
_lock = threading.Lock()


def _get_kiwi():
    global _kiwi
    if _kiwi is None:
        with _lock:
            if _kiwi is None:
                from kiwipiepy import Kiwi

                _kiwi = Kiwi()
    return _kiwi


def tokenize(text: str) -> list[str]:
    if not text or not text.strip():
        return []
    out = []
    for tok in _get_kiwi().tokenize(text):
        if str(tok.tag).startswith(DROP_TAG_PREFIXES):
            continue
        form = tok.form.strip()
        if LOWERCASE:
            form = form.lower()
        if form:
            out.append(form)
    return out


def _kiwi_version() -> str:
    try:
        from importlib.metadata import version

        return version("kiwipiepy")
    except Exception:  # pragma: no cover - metadata missing
        return "unknown"


def tokenizer_config() -> dict:
    return {
        "name": TOKENIZER_NAME,
        "kiwipiepy": _kiwi_version(),
        "drop_tag_prefixes": list(DROP_TAG_PREFIXES),
        "lowercase": LOWERCASE,
    }
