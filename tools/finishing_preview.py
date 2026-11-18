"""Generate before/after images and numeric diagnostics for manual finishing review.

Run from the repository root after installing the same dependencies as finish-quality.
The script does not change repository samples; it writes only to artifacts/finishing-review.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image, ImageDraw

from chatdraw import finishers

SAMPLE = ROOT / "library" / "daily" / "2026-10-13" / "05-yukionna.png"
OUT = ROOT / "artifacts" / "finishing-review"


def _noise(image: Image.Image) -> float:
    return float(finishers._gen("retouch").noise(np.asarray(image.convert("RGB"), dtype=np.float32)))


def _record(name: str, source: Image.Image, result: Image.Image, report: dict) -> dict:
    a = np.asarray(source.convert("RGB"), dtype=np.uint8)
    b = np.asarray(result.convert("RGB").resize(source.size, Image.LANCZOS), dtype=np.uint8)
    changed = np.any(a != b, axis=2)
    score = finishers.scores(source, result)
    result.save(OUT / f"{name}.png")
    return {
        "name": name,
        "size": list(result.size),
        "changed_pixels": int(changed.sum()),
        "changed_fraction": round(float(changed.mean()), 6),
        "mean_absolute_pixel_delta": round(float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean()), 4),
        "noise_before": round(_noise(source), 5),
        "noise_after": round(_noise(result), 5),
        "scores": score,
        "quality_control": report,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if not SAMPLE.is_file():
        raise FileNotFoundError(SAMPLE)
    source = Image.open(SAMPLE).convert("RGB")
    source.save(OUT / "original.png")

    # A centered selection exercises the masked path; the report records that pixels
    # outside the selection are unchanged.
    mask = Image.new("L", source.size, 0)
    draw = ImageDraw.Draw(mask)
    w, h = source.size
    selection = (w // 4, h // 4, (w * 3) // 4, (h * 3) // 4)
    draw.rectangle(selection, fill=255)

    cases = [
        ("clean", lambda: finishers.run("clean", source)),
        ("denoise", lambda: finishers.run("denoise", source)),
        ("retouch", lambda: finishers.run("retouch", source)),
        ("retouch_full", lambda: finishers.run("retouch_full", source)),
        ("face", lambda: finishers.run("face", source)),
        ("around", lambda: finishers.run("around", source, mask)),
        ("combo_tidy", lambda: finishers.run_chain(("clean", "retouch"), source)),
        ("combo_tidy_color", lambda: finishers.run_chain(("clean", "retouch_full"), source)),
    ]

    rows = []
    for name, action in cases:
        finishers.LAST_QC.clear()
        finishers.LAST_REPORT.clear()
        finishers.LAST_CHAIN.clear()
        result = action().convert("RGB")
        report = {
            "quality_control": dict(finishers.LAST_QC),
            "step_report": list(finishers.LAST_REPORT.get("steps", [])),
            "chain_report": list(finishers.LAST_CHAIN),
        }
        row = _record(name, source, result, report)
        if name == "around":
            outside = np.asarray(mask) == 0
            row["outside_mask_unchanged"] = bool(np.array_equal(
                np.asarray(source)[outside], np.asarray(result)[outside]
            ))
            row["selection_box"] = list(selection)
        rows.append(row)

    labels = ["original"] + [row["name"] for row in rows]
    cols, thumb_w = 3, 256
    thumb_h = max(1, round(source.height * thumb_w / source.width))
    cell_h = thumb_h + 30
    sheet = Image.new("RGB", (cols * thumb_w, ((len(labels) + cols - 1) // cols) * cell_h), "white")
    draw = ImageDraw.Draw(sheet)
    for i, label in enumerate(labels):
        image = Image.open(OUT / f"{label}.png").convert("RGB")
        image.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        x, y = (i % cols) * thumb_w, (i // cols) * cell_h
        sheet.paste(image, (x, y + 24))
        draw.text((x + 6, y + 5), label, fill="black")
    sheet.save(OUT / "contact-sheet.png")

    (OUT / "report.json").write_text(
        json.dumps({"source": str(SAMPLE.relative_to(ROOT)), "results": rows},
                   ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
