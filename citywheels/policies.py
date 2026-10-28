"""Policy search: Markdown policies split into sections and ranked with BM25."""

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Self

# Standard BM25 values: k1 caps the gain from repeated terms, b scales length normalisation.
BM25_K1 = 1.5
BM25_B = 0.75

# Question words and glue that appear in nearly every query would only add noise to scores.
STOPWORDS = frozenset(
    "a an and are at be by can do does for from how i in is it my of on or the to we what when "
    "where which with you your".split()
)
MIN_LEN_TO_STEM = 4  # keeps short words such as "bus" intact when stripping a plural "s"
MIN_LEN_FOR_ING = 6  # "opening" -> "open" and "bookings" -> "book", but "ring" stays whole

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class PolicySection:
    source: str  # "<file>#<heading>", e.g. "faq.md#Are there age limits?"
    text: str  # heading line + body, as shown to the model


def tokenize(text: str) -> list[str]:
    """Lowercase words and numbers, minus stopwords, with a plural "s" / "ing" removed.

    Light stemming lets "opening hours" match a section that says "open".
    """
    tokens = [t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]
    return [_stem(t) for t in tokens]


def _stem(token: str) -> str:
    if len(token) >= MIN_LEN_TO_STEM and token.endswith("s"):
        token = token[:-1]
    if len(token) >= MIN_LEN_FOR_ING and token.endswith("ing"):
        token = token[:-3]
    return token


class PolicyIndex:
    def __init__(self, sections: list[PolicySection]) -> None:
        self._sections = sections
        # The source (file name + heading) is indexed too, so "cancellation" finds cancellations.md.
        # The ".md" extension is dropped so "md" does not become a term present in every section.
        self._term_counts = [
            Counter(tokenize(f"{s.source.replace('.md#', ' ', 1)} {s.text}")) for s in sections
        ]
        self._lengths = [sum(counts.values()) for counts in self._term_counts]
        self._avg_length = sum(self._lengths) / len(sections) if sections else 0.0
        doc_freq = Counter(term for counts in self._term_counts for term in counts)
        n = len(sections)
        # "1 +" keeps IDF positive even for terms present in most sections.
        self._idf = {
            term: math.log(1 + (n - df + 0.5) / (df + 0.5)) for term, df in doc_freq.items()
        }

    @classmethod
    def from_dir(cls, path: Path) -> Self:
        sections: list[PolicySection] = []
        for file in sorted(path.glob("*.md")):
            sections.extend(_split_sections(file.name, file.read_text(encoding="utf-8")))
        return cls(sections)

    def search(self, query: str, top_k: int = 3) -> list[tuple[PolicySection, float]]:
        """Return up to `top_k` sections with a positive BM25 score, best first."""
        terms = tokenize(query)
        scored = [(section, self._score(terms, i)) for i, section in enumerate(self._sections)]
        hits = [(section, score) for section, score in scored if score > 0]
        return sorted(hits, key=lambda hit: hit[1], reverse=True)[:top_k]

    def _score(self, terms: list[str], i: int) -> float:
        if not self._avg_length:  # every section is empty, nothing can match (and avoids /0)
            return 0.0
        counts, length = self._term_counts[i], self._lengths[i]
        norm = 1 - BM25_B + BM25_B * length / self._avg_length
        score = 0.0
        for term in terms:
            tf = counts.get(term, 0)
            if tf:
                score += self._idf[term] * tf * (BM25_K1 + 1) / (tf + BM25_K1 * norm)
        return score


def _split_sections(filename: str, markdown: str) -> list[PolicySection]:
    """Split on `## ` headings; text before the first one is kept under the `# ` title."""
    parts = re.split(r"^(?=## )", markdown, flags=re.MULTILINE)
    sections: list[PolicySection] = []
    for part in parts:
        part = part.strip()
        if part.startswith("## "):
            heading = part.splitlines()[0][3:].strip()
            sections.append(PolicySection(f"{filename}#{heading}", part))
        elif part.startswith("# "):
            title_line, _, intro = part.partition("\n")
            title = title_line[2:].strip()
            if intro.strip():
                sections.append(
                    PolicySection(f"{filename}#{title}", f"{title_line}\n{intro}".strip())
                )
    return sections
