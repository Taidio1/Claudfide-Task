from pathlib import Path

import pytest

from citywheels.config import POLICIES_DIR
from citywheels.policies import PolicyIndex, PolicySection, _split_sections, tokenize


@pytest.fixture(scope="module")
def index() -> PolicyIndex:
    return PolicyIndex.from_dir(POLICIES_DIR)


def test_tokenize_lowercases_drops_stopwords_and_plural_s() -> None:
    assert tokenize("The Bikes are 20 EUR, bus") == ["bike", "20", "eur", "bus"]


def test_tokenize_strips_ing_but_keeps_short_words() -> None:
    assert tokenize("opening bookings ring") == ["open", "book", "ring"]


def test_split_title_without_intro_makes_no_title_section() -> None:
    sections = _split_sections("a.md", "# Title\n\n## One\nbody1\n## Two\nbody2\n")

    assert [s.source for s in sections] == ["a.md#One", "a.md#Two"]
    assert sections[0].text == "## One\nbody1"


def test_split_title_with_intro_makes_intro_section() -> None:
    sections = _split_sections("a.md", "# Title\nintro text\n\n## One\nbody1\n")

    assert [s.source for s in sections] == ["a.md#Title", "a.md#One"]
    assert sections[0].text == "# Title\nintro text"


def test_from_dir_reads_only_md_files(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# T\n## One\nzebra\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("## Hidden\nzebra\n", encoding="utf-8")

    hits = PolicyIndex.from_dir(tmp_path).search("zebra")

    assert [s.source for s, _ in hits] == ["a.md#One"]


def test_extension_is_not_indexed(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("## One\nzebra\n", encoding="utf-8")

    assert PolicyIndex.from_dir(tmp_path).search("md") == []


def test_all_empty_sections_do_not_crash() -> None:
    assert PolicyIndex([PolicySection("", "")]).search("x") == []


def test_section_text_is_heading_plus_body(index: PolicyIndex) -> None:
    section, _ = index.search("dogs baskets", top_k=1)[0]

    assert section.text.startswith("## Can I take my dog?\n")
    assert "Dogs are not allowed" in section.text


def test_intro_before_first_heading_becomes_own_section(index: PolicyIndex) -> None:
    section, _ = index.search("prices euros VAT", top_k=1)[0]

    assert section.source == "prices.md#Prices"


@pytest.mark.parametrize(
    ("query", "expected_source"),
    [
        ("opening hours", "faq.md#When are you open?"),
        ("e-bike price per day", "prices.md#Bike rental"),
        ("age limit electric bike", "faq.md#Are there age limits?"),
        ("refund cancel booking", "cancellations.md#Cancelling a booking"),
        ("storm weather", "cancellations.md#Bad weather"),
    ],
)
def test_finds_relevant_section(index: PolicyIndex, query: str, expected_source: str) -> None:
    results = index.search(query)

    assert results[0][0].source == expected_source


def test_no_match_returns_empty(index: PolicyIndex) -> None:
    assert index.search("capital australia") == []


def test_top_k_limits_results(index: PolicyIndex) -> None:
    assert len(index.search("bike", top_k=50)) > 2
    assert len(index.search("bike", top_k=2)) == 2


def test_results_are_sorted_by_descending_positive_score(index: PolicyIndex) -> None:
    scores = [score for _, score in index.search("bike rental price", top_k=10)]

    assert scores == sorted(scores, reverse=True)
    assert all(score > 0 for score in scores)


def test_empty_index_returns_empty() -> None:
    assert PolicyIndex([]).search("bike") == []


def test_section_is_immutable() -> None:
    section = PolicySection(source="a.md#B", text="## B\nbody")

    with pytest.raises(AttributeError):
        section.text = "x"  # type: ignore[misc]
