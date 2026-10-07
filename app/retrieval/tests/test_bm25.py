from retrieval.bm25 import BM25Index
from retrieval.chunker import chunk_document
from retrieval.loader import load_documents
from retrieval.tokenize import tokenize


def _corpus(fixture_input):
    docs, _ = load_documents(fixture_input)
    chunks = [c for d in docs for c in chunk_document(d)]
    return chunks, BM25Index([tokenize(c.text) for c in chunks])


def test_proper_noun_query_ranks_document_first(fixture_input):
    chunks, bm25 = _corpus(fixture_input)
    ranked = bm25.rank(tokenize("훈민정음"))
    assert ranked, "expected hits"
    assert chunks[ranked[0][0]].source == "hunminjeongeum.md"

    ranked = bm25.rank(tokenize("거중기"))
    assert chunks[ranked[0][0]].source == "hwaseong_b.jsonl"

    ranked = bm25.rank(tokenize("프린터 교체"))
    assert chunks[ranked[0][0]].source == "misc/meeting_notes.txt"


def test_scores_sorted_and_only_overlapping_docs(fixture_input):
    chunks, bm25 = _corpus(fixture_input)
    ranked = bm25.rank(tokenize("경회루"))
    scores = [s for _, s in ranked]
    assert scores == sorted(scores, reverse=True)
    assert {chunks[i].source for i, _ in ranked} == {"palace/gyeongbokgung.md"}


def test_out_of_vocabulary_query_has_no_hits(fixture_input):
    _, bm25 = _corpus(fixture_input)
    assert bm25.rank(tokenize("zzzqqqxyz")) == []
    assert bm25.rank([]) == []


def test_empty_corpus_does_not_crash():
    assert BM25Index([]).rank(["세종"]) == []
