"""Structural blocks produced by text extractors.

Each block type carries only the fields that apply to it, so no field is
None for the wrong kind of block.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Block:
    ordinal: int  # 1-based position in document order
    text: str


@dataclass(frozen=True)
class Heading(Block):
    level: int


@dataclass(frozen=True)
class Paragraph(Block):
    pass


@dataclass(frozen=True)
class TableRow(Block):
    table_index: int  # 1-based table number within the document
    row_index: int  # 1-based row number within the table