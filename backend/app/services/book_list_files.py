"""A PDF list of the PDF document names of every registered book.

Made from the book rows alone: no provider call, no stored file. The bytes are returned to the
browser and forgotten.
"""

import html
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

CSS = """
h1 { font-size: 18pt; margin: 0 0 4pt 0; }
.meta { font-size: 9pt; color: #555; margin: 0 0 16pt 0; }
.row { font-size: 10pt; margin: 0 0 10pt 0; }
.num { color: #777; }
.file { font-size: 9pt; color: #555; }
.empty { font-size: 10pt; color: #555; }
"""


def render_book_list_pdf(books: list[dict[str, Any]]) -> bytes:
    """One page or more of numbered book titles with their source PDF file names."""
    import pymupdf

    rows = "".join(
        f'<p class="row"><span class="num">{number}.</span> '
        f'<strong>{html.escape(str(book.get("title") or "Untitled"))}</strong><br>'
        f'<span class="file">{html.escape(str(book.get("source_filename") or "Unavailable"))}'
        f"</span></p>"
        for number, book in enumerate(books, start=1)
    )
    empty = '<p class="empty">No books are registered.</p>'
    count = f'{len(books)} PDF document{"s" if len(books) != 1 else ""}'
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    document = (
        "<html><body>"
        "<h1>Ingestion book list</h1>"
        f'<p class="meta">{count} &middot; Generated {generated}</p>'
        f"{rows or empty}"
        "</body></html>"
    )
    story = pymupdf.Story(html=document, user_css=CSS)
    buffer = BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    page = pymupdf.paper_rect("a4")
    area = page + (40, 40, -40, -40)
    more = True
    while more:
        device = writer.begin_page(page)
        more, _ = story.place(area)
        story.draw(device)
        writer.end_page()
    writer.close()
    return buffer.getvalue()
