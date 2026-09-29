# Test Fixtures

Synthetic files used by automated tests. They contain no real case material.

Regenerate everything with:

    uv run python tests/fixtures/build_fixtures.py

| File | Description |
|------|-------------|
| `native.pdf` | Two pages with a text layer |
| `scanned.pdf` | One page, image only (no text layer) |
| `sample.docx` | Heading, two numbered paragraphs, one table |
| `thread_original.eml` | Original message with Message-ID |
| `thread_reply.eml` | Reply with In-Reply-To, References, and quoted text |
| `receipt.png` | Image containing receipt-style text |
| `bank_statement_synthetic_2024-01.pdf` | Named to match the bank statement routing rule |

Do not add real documents to this folder. Real material belongs in `originals/`,
which is excluded from version control.