"""Chunking and BM25 search for the tuition policy document.

The document is split by its headings:
  - every "### N.M Heading" subsection becomes one chunk
  - a "## N. Heading" section without subsections becomes one chunk

The index is built once (when the server starts) and then only searched.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

MAX_TOP_K = 10

SECTION_RE = re.compile(r"^##\s+(\d+)\.\s+(.+?)\s*$")
SUBSECTION_RE = re.compile(r"^###\s+(\d+\.\d+)\s+(.+?)\s*$")
DOCUMENT_ID_RE = re.compile(r"\*\*Document ID:\*\*\s*([A-Za-z0-9-]+)")
TOKEN_RE = re.compile(r"[a-z0-9]+")

# small english stopword list, enough for short policy questions
STOPWORDS = {
    "a", "about", "after", "all", "also", "am", "an", "and", "any", "are", "as", "at",
    "be", "been", "before", "being", "by", "can", "could", "did", "do", "does", "for",
    "from", "get", "had", "has", "have", "he", "her", "here", "him", "his", "how", "i",
    "if", "in", "into", "is", "it", "its", "me", "my", "no", "not", "of", "on", "or",
    "our", "she", "should", "so", "such", "than", "that", "the", "their", "them",
    "then", "there", "these", "they", "this", "those", "to", "under", "until", "was",
    "we", "were", "what", "when", "where", "which", "who", "why", "will", "with",
    "would", "you", "your",
}

# words that describe the whole document, not one section. Without this, "installment rules"
# ranks 4.1 "Late fee rule" first only because "rule" is a rare word in the document.
GENERIC_WORDS = {
    "rule", "rules", "policy", "policies", "regulation", "regulations",
    "guideline", "guidelines",
}
STOPWORDS |= GENERIC_WORDS


class PolicySearchError(ValueError):
    """Raised for bad search input (empty query, wrong top_k)."""


@dataclass
class Chunk:
    section: str          # "3.2", or "1" for a section without subsections
    heading: str          # "Number and size of installments"
    parent_heading: str   # "Installment policy"
    text: str


def _stem(word: str) -> str:
    # very light plural handling so "installments" matches "installment"
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    words = TOKEN_RE.findall(text.lower())
    return [_stem(w) for w in words if w not in STOPWORDS]


def _clean(lines: list[str]) -> str:
    text = "\n".join(lines).strip()
    text = text.replace("**", "")
    return re.sub(r"\n{3,}", "\n\n", text)


def split_into_chunks(markdown: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    section_no = section_title = None
    sub_no = sub_title = None
    section_lines: list[str] = []   # text directly under "## N." (before any ###)
    sub_lines: list[str] = []
    has_subsections = False

    def close_subsection():
        if sub_no is not None:
            chunks.append(Chunk(sub_no, sub_title, section_title, _clean(sub_lines)))

    def close_section():
        if section_no is not None and not has_subsections:
            chunks.append(Chunk(section_no, section_title, section_title, _clean(section_lines)))

    for line in markdown.splitlines():
        sec = SECTION_RE.match(line)
        sub = SUBSECTION_RE.match(line)
        if sec:
            close_subsection()
            close_section()
            section_no, section_title = sec.group(1), sec.group(2)
            sub_no = sub_title = None
            section_lines, sub_lines = [], []
            has_subsections = False
        elif sub and section_no is not None:
            close_subsection()
            sub_no, sub_title = sub.group(1), sub.group(2)
            sub_lines = []
            has_subsections = True
        elif sub_no is not None:
            sub_lines.append(line)
        elif section_no is not None:
            section_lines.append(line)
        # lines before the first "##" (title, metadata) are not indexed

    close_subsection()
    close_section()
    return chunks


class BM25:
    """Plain BM25 (Okapi) over a list of tokenized documents."""

    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_count = len(docs)
        self.doc_lengths = [len(d) for d in docs]
        self.avg_length = sum(self.doc_lengths) / self.doc_count if self.doc_count else 0.0
        self.term_freqs = [Counter(d) for d in docs]

        doc_freq: Counter = Counter()
        for d in docs:
            doc_freq.update(set(d))
        # idf with +1 inside the log so it never becomes negative
        self.idf = {
            term: math.log((self.doc_count - df + 0.5) / (df + 0.5) + 1)
            for term, df in doc_freq.items()
        }

    def scores(self, query_tokens: list[str]) -> list[float]:
        result = [0.0] * self.doc_count
        for term in set(query_tokens):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, tf in enumerate(self.term_freqs):
                freq = tf.get(term, 0)
                if not freq:
                    continue
                norm = 1 - self.b + self.b * self.doc_lengths[i] / self.avg_length
                result[i] += idf * freq * (self.k1 + 1) / (freq + self.k1 * norm)
        return result


@dataclass
class PolicyIndex:
    document: str
    document_id: str
    chunks: list[Chunk]
    bm25: BM25 = field(repr=False)
    built_at: str = ""

    @classmethod
    def build(cls, markdown: str, document: str) -> "PolicyIndex":
        match = DOCUMENT_ID_RE.search(markdown)
        document_id = match.group(1) if match else ""
        chunks = split_into_chunks(markdown)
        if not chunks:
            raise ValueError(f"No sections found in {document}")
        # heading words are added twice so a matching heading counts a bit more
        token_lists = [
            tokenize(c.parent_heading) + tokenize(c.heading) * 2 + tokenize(c.text)
            for c in chunks
        ]
        built_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return cls(document, document_id, chunks, BM25(token_lists), built_at)

    @classmethod
    def from_file(cls, path: str | Path) -> "PolicyIndex":
        path = Path(path)
        return cls.build(path.read_text(encoding="utf-8"), path.name)

    def search(self, query: str, top_k: int = 3) -> dict:
        if query is None or not query.strip():
            raise PolicySearchError("query must not be empty. Ask a question about tuition policies, e.g. 'late fee'.")
        if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= MAX_TOP_K:
            raise PolicySearchError(f"top_k must be an integer between 1 and {MAX_TOP_K}.")

        query = query.strip()
        scores = self.bm25.scores(tokenize(query))
        ranked = sorted(
            (i for i, s in enumerate(scores) if s > 0),
            key=lambda i: scores[i],
            reverse=True,
        )[:top_k]

        return {
            "document": self.document,
            "documentId": self.document_id,
            "query": query,
            "matches": [
                {
                    "section": self.chunks[i].section,
                    "heading": self.chunks[i].heading,
                    "parentHeading": self.chunks[i].parent_heading,
                    "text": self.chunks[i].text,
                    "score": round(scores[i], 4),
                }
                for i in ranked
            ],
        }
