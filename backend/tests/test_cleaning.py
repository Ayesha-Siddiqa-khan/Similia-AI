"""Text cleaning tests: hyphenation, page numbers, repeated headers."""

from app.ai.ingestion.cleaning import clean_pages, clean_text
from app.ai.ingestion.extraction import PageText


def test_rejoins_hyphenated_words() -> None:
    assert clean_text("A multi-\nfarious remedy.") == "A multifarious remedy."


def test_removes_page_number_lines() -> None:
    text = "Rubric text here.\n\n42\n\nMore rubric text."
    result = clean_text(text)
    assert "42" not in result.split("\n")
    assert "Rubric text here." in result


def test_normalizes_whitespace_and_nbsp() -> None:
    assert clean_text("a\xa0b   c") == "a b c"


def test_drops_headers_repeated_across_most_pages() -> None:
    pages = [
        PageText(page=i, text=f"REPERTORY OF THE HOMEOPATHIC MATERIA MEDICA\n\nBody {i}.\n\n{i}")
        for i in range(1, 6)
    ]
    result = clean_pages(pages)
    assert len(result) == 5
    assert all("REPERTORY" not in p.text for p in result)
    assert "Body 3." in result[2].text


def test_unique_lines_are_kept() -> None:
    pages = [PageText(page=i, text=f"Unique header {i}\n\nText {i}.") for i in range(1, 4)]
    result = clean_pages(pages)
    assert all("Unique header" in p.text for p in result)
