import pytest

from indexer import MAX_TOP_K, PolicySearchError, split_into_chunks, tokenize

EXPECTED_SECTIONS = [
    "1",
    "2.1", "2.2", "2.3",
    "3.1", "3.2", "3.3", "3.4",
    "4.1", "4.2", "4.3",
    "5.1", "5.2",
    "6.1", "6.2", "6.3",
    "7.1", "7.2", "7.3", "7.4",
    "8.1", "8.2", "8.3", "8.4",
    "9",
]


# ---------- chunking ----------

def test_document_is_split_into_25_sections(index):
    assert len(index.chunks) == 25
    assert [c.section for c in index.chunks] == EXPECTED_SECTIONS


def test_document_id_is_read_from_the_file(index):
    assert index.document == "University_Tuition_Policies.md"
    assert index.document_id == "UNI-TUITION-2026-01"


def test_subsection_has_heading_parent_and_text(index):
    chunk = next(c for c in index.chunks if c.section == "3.2")
    assert chunk.heading == "Number and size of installments"
    assert chunk.parent_heading == "Installment policy"
    assert "up to three installments" in chunk.text
    assert "**" not in chunk.text
    # text of the next subsection must not leak into this one
    assert "Installment schedule" not in chunk.text


def test_section_without_subsections_is_one_chunk(index):
    first = index.chunks[0]
    assert first.section == "1"
    assert first.heading == first.parent_heading == "Scope and terminology"
    assert "Outstanding balance" in first.text
    last = index.chunks[-1]
    assert last.section == "9"
    assert "search_tuition_policies" in last.text


def test_header_before_first_section_is_not_indexed(index):
    assert all("Document ID" not in c.text for c in index.chunks)


def test_split_small_markdown():
    md = "# Title\nintro\n## 1. Alpha\nalpha text\n## 2. Beta\n### 2.1 One\none text\n### 2.2 Two\ntwo text\n"
    chunks = split_into_chunks(md)
    assert [(c.section, c.heading, c.parent_heading, c.text) for c in chunks] == [
        ("1", "Alpha", "Alpha", "alpha text"),
        ("2.1", "One", "Beta", "one text"),
        ("2.2", "Two", "Beta", "two text"),
    ]


def test_tokenize_lowercases_and_drops_stopwords_and_punctuation():
    assert tokenize("What is the Late-Fee, for $1,000?") == ["late", "fee", "1", "000"]
    assert tokenize("installments refunds fees deliveries") == ["installment", "refund", "fee", "delivery"]


# ---------- search: different queries ----------

def top_sections(result):
    return [m["section"] for m in result["matches"]]


def test_payment_deadline_query_returns_section_2_1(index):
    result = index.search("What is the payment deadline for the Fall term?")
    assert top_sections(result)[0] == "2.1"
    assert "September 30, 2026" in result["matches"][0]["text"]


def test_installment_query_returns_installment_policy(index):
    result = index.search("How many installments can I split my tuition into?")
    sections = top_sections(result)
    assert any(s.startswith("3.") for s in sections)
    assert "3.2" in sections


@pytest.mark.parametrize("query", ["installment rules", "installment policy"])
def test_installment_rules_query_returns_section_3_2_first(index, query):
    # sample query from the assignment: "installment rules" -> section 3.2
    sections = top_sections(index.search(query))
    assert sections[0] == "3.2"
    assert all(s.startswith("3.") for s in sections)


def test_generic_words_are_ignored():
    assert tokenize("installment rules") == tokenize("installment policy") == ["installment"]


def test_refund_query_returns_section_6_1(index):
    result = index.search("Do I get a refund if I withdraw early?")
    assert top_sections(result)[0] == "6.1"
    assert "80%" in result["matches"][0]["text"]


def test_late_fee_query_returns_section_4_1(index):
    result = index.search("Is there a penalty for paying late?")
    assert top_sections(result)[0] == "4.1"
    assert "2%" in result["matches"][0]["text"]


def test_late_fee_rule_and_example_both_come_first(index):
    # 4.2 (the worked example) is short and repeats "late fee" and "overdue",
    # so for this wording it can be ranked just above the rule itself
    result = index.search("late fee for overdue tuition")
    assert set(top_sections(result)[:2]) == {"4.1", "4.2"}


def test_scholarship_query_returns_section_5_1(index):
    assert top_sections(index.search("merit scholarship percentage"))[0] == "5.1"


def test_result_format(index):
    result = index.search("late fee", top_k=2)
    assert set(result) == {"document", "documentId", "query", "matches"}
    assert result["document"] == "University_Tuition_Policies.md"
    assert result["documentId"] == "UNI-TUITION-2026-01"
    assert result["query"] == "late fee"
    for m in result["matches"]:
        assert {"section", "heading", "text", "score"} <= set(m)
        assert m["score"] > 0
    scores = [m["score"] for m in result["matches"]]
    assert scores == sorted(scores, reverse=True)


def test_query_without_known_words_returns_no_matches(index):
    result = index.search("xyzzy qwerty")
    assert result["matches"] == []


# ---------- input checks ----------

@pytest.mark.parametrize("query", ["", "   ", None])
def test_empty_query_raises_error(index, query):
    with pytest.raises(PolicySearchError, match="query must not be empty"):
        index.search(query)


@pytest.mark.parametrize("top_k", [0, -1, MAX_TOP_K + 1, True])
def test_top_k_out_of_range_raises_error(index, top_k):
    with pytest.raises(PolicySearchError, match="top_k"):
        index.search("late fee", top_k=top_k)


def test_top_k_limits_number_of_matches(index):
    assert len(index.search("tuition payment", top_k=1)["matches"]) == 1
    assert len(index.search("tuition payment", top_k=5)["matches"]) == 5
    assert len(index.search("tuition payment", top_k=MAX_TOP_K)["matches"]) <= MAX_TOP_K
