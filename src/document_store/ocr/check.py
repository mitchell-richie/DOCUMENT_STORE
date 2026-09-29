"""PaddleOCR connectivity check.

Run inside the devcontainer:

    uv run python -m document_store.ocr.check
    uv run python -m document_store.ocr.check --gpu
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from document_store.ocr.paddle import create_engine, run_ocr

SAMPLE_TEXT = "Invoice 12345 Total 99.00"
EXPECTED_TOKEN = "12345"


@dataclass(frozen=True)
class CheckReport:
    device: str
    text: str
    mean_confidence: float
    init_seconds: float
    ocr_seconds: float
    passed: bool


def render_sample_image(path: Path, text: str = SAMPLE_TEXT) -> Path:
    """Render text to a PNG file using PyMuPDF."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=24)
    page.get_pixmap(dpi=200).save(str(path))
    doc.close()
    return path


def run_check(
        work_dir: Path,
        use_gpu: bool = False,
        enable_mkldnn: bool = False
        ) -> CheckReport:
    """Render a sample image, OCR it, and report the result."""
    image = render_sample_image(work_dir / "paddle_check.png")

    init_start = time.perf_counter()
    engine = create_engine(use_gpu=use_gpu, enable_mkldnn=enable_mkldnn)
    init_seconds = time.perf_counter() - init_start

    ocr_start = time.perf_counter()
    result = run_ocr(engine, image)
    ocr_seconds = time.perf_counter() - ocr_start

    passed = EXPECTED_TOKEN in result.text and result.mean_confidence > 0
    return CheckReport(
        device="gpu" if use_gpu else "cpu",
        text=result.text,
        mean_confidence=result.mean_confidence,
        init_seconds=init_seconds,
        ocr_seconds=ocr_seconds,
        passed=passed,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="PaddleOCR connectivity check")
    parser.add_argument("--gpu", action="store_true", help="request GPU mode")
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="directory for the sample image (default: a temporary directory)",
    )
    parser.add_argument(
        "--mkldnn",
        action="store_true",
        help="enable oneDNN acceleration (known broken on paddlepaddle 3.3.1 CPU, see paddle.py)",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        work_dir = args.work_dir or Path(tmp)
        work_dir.mkdir(parents=True, exist_ok=True)
        report = run_check(
            work_dir,
            use_gpu=args.gpu,
            enable_mkldnn=args.mkldnn
            )

    print(f"device:           {report.device}")
    print(f"recognised text:  {report.text!r}")
    print(f"mean confidence:  {report.mean_confidence:.3f}")
    print(f"engine init:      {report.init_seconds:.2f}s")
    print(f"OCR time:         {report.ocr_seconds:.2f}s")
    print(f"result:           {'PASS' if report.passed else 'FAIL'}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())