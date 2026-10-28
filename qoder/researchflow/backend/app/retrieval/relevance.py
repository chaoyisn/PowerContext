"""Relevance scoring and the evidence gate.

Why this module exists: vector ANN always returns *k* nearest rows and seekdb's
``MATCH ... AGAINST`` can return a non-zero score on partial token overlap, so a question
whose answer is **not** in the corpus still produces hits. Acceptance test T3 requires
that such a question must not yield a citation, so relevance is decided by a rule that
can be explained and checked rather than by trusting the raw rank.

Rule (see ``passes_gate``):

* ``coverage`` - fraction of the query's *discriminative* tokens that literally appear in
  the chunk. Stopwords are dropped, ASCII words are split on ``_``/``-``, CJK is compared
  as character bigrams so it works without a Chinese word segmenter.
* ``normalized_score`` - the backend score squashed into 0..1 so the three retrieval modes
  can be compared on one axis (raw scores are still returned untouched).
* A hit passes when ``coverage >= min_coverage``, or - for pure vector mode only - when the
  cosine similarity is high enough that a paraphrase is a plausible match.
"""

from __future__ import annotations

import re

_ASCII_TOKEN = re.compile(r"[a-z0-9]+")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

_EN_STOPWORDS = frozenset(
    """a an the and or but if then than that this these those of to in on for with without
    is are was were be been being do does did done have has had having i you he she it we they
    what which who whom whose when where why how all any both each few more most other some such
    no nor not only own same so too very can will just should now about into over under again
    there here as at by from up down out off below above between during before after""".split()
)

# Function characters that carry no topical signal in Chinese queries.
_CJK_STOP_CHARS = frozenset(
    "的是了在和与有这那我你他它个么什吗呢吧啊或及等对为以于中上下不也都还很更最就只把被让给从到"
    "请问能否可否有没有一些一个我们你们他们它们其及并且但是如果因为所以虽然然而以及关于对于"
)


def content_tokens(text: str) -> set[str]:
    """Discriminative tokens: filtered ASCII words, numbers and CJK bigrams."""
    if not text:
        return set()
    lowered = text.lower()
    tokens: set[str] = {
        word for word in _ASCII_TOKEN.findall(lowered) if len(word) >= 3 and word not in _EN_STOPWORDS
    }
    tokens.update(number for number in _NUMBER.findall(lowered) if len(number) >= 2)
    cjk_chars = [ch for ch in text if _CJK.match(ch) and ch not in _CJK_STOP_CHARS]
    if len(cjk_chars) == 1:
        tokens.add(cjk_chars[0])
    tokens.update(a + b for a, b in zip(cjk_chars, cjk_chars[1:]))
    return tokens


def lexical_coverage(query: str, text: str) -> float:
    query_tokens = content_tokens(query)
    if not query_tokens:
        return 0.0
    text_tokens = content_tokens(text)
    return round(len(query_tokens & text_tokens) / len(query_tokens), 4)


def normalize_score(score: float, score_kind: str, *, rrf_legs: int = 2, rrf_k: int = 60) -> float:
    """Squash a backend score into 0..1. The mapping is monotone, so ranking is unchanged."""
    if score_kind == "cosine_similarity":
        return round(max(0.0, min(1.0, score)), 4)
    if score_kind == "fts_relevance":
        # seekdb's MATCH score is unbounded; x/(x+1) keeps order and maps to (0,1).
        return round(max(0.0, score) / (max(0.0, score) + 1.0), 4)
    if score_kind == "rrf":
        ceiling = rrf_legs / (rrf_k + 1)
        return round(max(0.0, min(1.0, score / ceiling)) if ceiling else 0.0, 4)
    return round(max(0.0, min(1.0, score)), 4)


def combined_relevance(normalized_score: float, coverage: float) -> float:
    return round(0.4 * normalized_score + 0.6 * coverage, 4)


def passes_gate(
    *,
    coverage: float,
    semantic_similarity: float = 0.0,
    min_coverage: float = 0.30,
    vector_confidence: float = 0.62,
) -> bool:
    """Two independent ways a hit can qualify as evidence.

    * ``coverage >= min_coverage`` - the chunk literally contains the query's terms. 0.30
      comes from a measured margin on the demo corpus: answerable questions score
      0.67-1.00, unanswerable ones 0.00-0.14.
    * ``semantic_similarity >= vector_confidence`` - the chunk is a paraphrase or a
      cross-lingual match that shares no literal tokens. This is the cosine similarity between
      the query vector and the stored vector, so it is available in every retrieval mode,
      not just pure vector search.
    """
    if coverage >= min_coverage:
        return True
    return semantic_similarity >= vector_confidence
