"""OCR benchmark: compare engines on scans with transcribed ground truth.

Usage:
    uv run python -m document_store.bench.ocr <dataset-dir> [--engines paddleocr,tesseract]

Dataset layout: each image has a transcript with the same stem:
    scan_001.png   scan_001.txt
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from importlib.metadata import version as package_version
from pathlib import Path
from time import perf_counter

from document_store.bench.metrics import character_error_rate
from document_store.ocr.paddle import OcrResult, create_engine, run_ocr
from document_store.ocr.tesseract import tesseract_ocr

log = logging.getLogger(__name__)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}

EngineRunner = Callable[[Path], OcrResult]


@dataclass(frozen=True)
class BenchmarkItem:
    name: str
    image: Path
    reference: str


@dataclass(frozen=True)
class ItemResult:
    item: str
    engine: str
    cer: float
    mean_confidence: float
    seconds: float


@dataclass(frozen=True)
class EngineSummary:
    engine: str
    items: int
    mean_cer: float
    median_cer: float
    mean_confidence: float
    seconds_per_item: float


def discover_items(dataset: Path) -> tuple[list[BenchmarkItem], list[str]]:
    """Pair each image with its transcript. Returns (items, names skipped)."""
    items: list[BenchmarkItem] = []
    skipped: list[str] = []
    for image in sorted(p for p in dataset.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES):
        transcript = image.with_suffix(".txt")
        if not transcript.is_file():
            skipped.append(image.name)
            continue
        items.append(
            BenchmarkItem(
                name=image.stem,
                image=image,
                reference=transcript.read_text(encoding="utf-8"),
            )
        )
    return items, skipped


def _summarise(engine: str, results: list[ItemResult]) -> EngineSummary:
    if not results:
        return EngineSummary(engine, 0, 0.0, 0.0, 0.0, 0.0)
    return EngineSummary(
        engine=engine,
        items=len(results),
        mean_cer=statistics.fmean(r.cer for r in results),
        median_cer=statistics.median(r.cer for r in results),
        mean_confidence=statistics.fmean(r.mean_confidence for r in results),
        seconds_per_item=statistics.fmean(r.seconds for r in results),
    )


def run_benchmark(
    items: list[BenchmarkItem],
    engines: Mapping[str, EngineRunner],
) -> tuple[list[ItemResult], list[EngineSummary]]:
    """Run every engine on every item and summarise the results per engine."""
    results: list[ItemResult] = []
    for item in items:
        for name, run in engines.items():
            start = perf_counter()
            result = run(item.image)
            elapsed = perf_counter() - start
            results.append(
                ItemResult(
                    item=item.name,
                    engine=name,
                    cer=character_error_rate(item.reference, result.text),
                    mean_confidence=result.mean_confidence,
                    seconds=elapsed,
                )
            )
            log.info("benchmarked %s with %s", item.name, name)
    summaries = [
        _summarise(name, [r for r in results if r.engine == name]) for name in engines
    ]
    return results, summaries


def render_markdown(summaries: list[EngineSummary], versions: dict[str, str]) -> str:
    lines = ["# OCR benchmark results", ""]
    lines.append("| Engine | Items | Mean CER | Median CER | Mean confidence | Seconds per item |")
    lines.append("|---|---|---|---|---|---|")
    for s in summaries:
        lines.append(
            f"| {s.engine} | {s.items} | {s.mean_cer:.3f} | {s.median_cer:.3f} "
            f"| {s.mean_confidence:.3f} | {s.seconds_per_item:.2f} |"
        )
    lines.append("")
    lines.append("Versions: " + ", ".join(f"{k} {v}" for k, v in versions.items()))
    return "\n".join(lines) + "\n"


def _versions() -> dict[str, str]:
    versions = {"paddleocr": package_version("paddleocr")}
    try:
        import pytesseract

        versions["tesseract"] = str(pytesseract.get_tesseract_version())
    except Exception:  # noqa: BLE001 -- a missing binary is reported, not fatal
        versions["tesseract"] = "not installed"
    return versions


def build_engines(names: list[str]) -> dict[str, EngineRunner]:
    engines: dict[str, EngineRunner] = {}
    for name in names:
        if name == "paddleocr":
            paddle = create_engine()
            engines[name] = lambda path, engine=paddle: run_ocr(engine, path)
        elif name == "tesseract":
            engines[name] = tesseract_ocr
        else:
            raise ValueError(f"unknown engine: {name}")
    return engines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark OCR engines.")
    parser.add_argument("dataset", type=Path, help="folder of images with .txt transcripts")
    parser.add_argument(
        "--engines",
        default="paddleocr,tesseract",
        help="comma-separated engines to compare (default: paddleocr,tesseract)",
    )
    args = parser.parse_args(argv)

    items, skipped = discover_items(args.dataset)
    if skipped:
        print(f"skipped (no transcript): {', '.join(skipped)}", file=sys.stderr)
    if not items:
        print("no benchmark items found", file=sys.stderr)
        return 2

    engines = build_engines([name.strip() for name in args.engines.split(",") if name.strip()])
    results, summaries = run_benchmark(items, engines)
    versions = _versions()

    (args.dataset / "results.json").write_text(
        json.dumps(
            {
                "versions": versions,
                "summaries": [asdict(s) for s in summaries],
                "items": [asdict(r) for r in results],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    markdown = render_markdown(summaries, versions)
    (args.dataset / "results.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())