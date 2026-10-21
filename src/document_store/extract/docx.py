"""DOCX text extraction.

Walks the document body in order, producing one block per non-empty
paragraph or heading, and one block per non-empty table row. Word does not
record page numbers for paragraphs, so blocks carry no page number; citations
use the block ordinal instead.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph as DocxParagraph

from document_store.extract.base import Extractor
from document_store.extract.blocks import Block, Heading, Paragraph, TableRow


@dataclass(frozen=True)
class DocxExtraction:
    blocks: tuple[Block, ...]


def _heading_level(style_name: str) -> int | None:
    """Return the level for a 'Heading N' style, or None for other styles."""
    if not style_name.startswith("Heading"):
        return None
    suffix = style_name.split()[-1]
    return int(suffix) if suffix.isdigit() else 1


def _paragraph_block(paragraph: DocxParagraph, ordinal: int) -> Block | None:
    text = paragraph.text.strip()
    if not text:
        return None
    style_name = paragraph.style.name if paragraph.style is not None else ""
    level = _heading_level(style_name)
    if level is None:
        return Paragraph(ordinal=ordinal, text=text)
    return Heading(ordinal=ordinal, text=text, level=level)


def _table_rows(table: Table, table_index: int, start_ordinal: int) -> list[TableRow]:
    rows: list[TableRow] = []
    for row_index, row in enumerate(table.rows, start=1):
        cells = [cell.text.strip() for cell in row.cells]
        if any(cells):
            rows.append(
                TableRow(
                    ordinal=start_ordinal + len(rows),
                    text=" | ".join(cells),
                    table_index=table_index,
                    row_index=row_index,
                )
            )
    return rows


class DocxExtractor(Extractor[DocxExtraction]):
    format_name = "Word document"
    open_errors = (PackageNotFoundError, zipfile.BadZipFile)

    def _open(self) -> Document:
        return Document(self.path)

    def _read(self, source: Document) -> DocxExtraction:
        blocks: list[Block] = []
        table_index = 0
        for child in source.element.body.iterchildren():
            ordinal = len(blocks) + 1
            if child.tag == qn("w:p"):
                block = _paragraph_block(DocxParagraph(child, source), ordinal)
                if block is not None:
                    blocks.append(block)
            elif child.tag == qn("w:tbl"):
                table_index += 1
                blocks.extend(_table_rows(Table(child, source), table_index, ordinal))
        return DocxExtraction(blocks=tuple(blocks))


def extract_docx(path: Path) -> DocxExtraction:
    """Extract headings, paragraphs, and table rows in document order.

    Raises:
        ExtractionError: if the file cannot be opened as a Word document.
    """
    return DocxExtractor(path).extract()