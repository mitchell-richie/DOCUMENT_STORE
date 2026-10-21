"""Export a Hugging Face OCR dataset into the benchmark folder layout.

Each exported sample becomes:
    <name>.png      the degraded image
    <name>.txt      the ground-truth text (ocr_text)
    <name>.params.json  the degradation parameters, for breakdown by noise level

Usage:
    uv run --group bench python -m document_store.bench.export_hf \
        racineai/ocr-pdf-degraded ~/case-dms-benchmark/hf --limit 30
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path


def export(
    dataset_name: str,
    out_dir: Path,
    split: str = "train",
    limit: int = 30,
    seed: int = 0,
) -> int:
    """Write up to `limit` samples with non-empty ground truth. Returns the count."""
    from datasets import load_dataset

    dataset = load_dataset(dataset_name, split=split)
    indices = list(range(len(dataset)))
    random.Random(seed).shuffle(indices)

    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for index in indices:
        if written >= limit:
            break
        sample = dataset[index]
        text = sample["ocr_text"]
        if not text or not text.strip():
            continue

        name = f"hf_{index:06d}"
        sample["image"].save(out_dir / f"{name}.png")
        (out_dir / f"{name}.txt").write_text(text, encoding="utf-8")
        params = sample.get("params")
        if params:
            (out_dir / f"{name}.params.json").write_text(
                json.dumps(json.loads(params), sort_keys=True), encoding="utf-8"
            )
        written += 1
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a Hugging Face OCR dataset.")
    parser.add_argument("dataset", help="dataset name, e.g. racineai/ocr-pdf-degraded")
    parser.add_argument("out_dir", type=Path, help="folder to write samples into")
    parser.add_argument("--split", default="train")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    written = export(args.dataset, args.out_dir, args.split, args.limit, args.seed)
    print(f"exported {written} samples to {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())