"""検品の精度を、正解の付いた手本（tests/fixtures/qc-labels.json）で測る。崩れの種類ごとに、見つけた数と見逃した数を出す。

  PYTHONPATH=.cache/gen/lib python3 tools/gen/qc_eval.py [--labels tests/fixtures/qc-labels.json]

検品の処理を足したら、ここで見逃しが減ったかを数字で確かめる（足しただけで「精度が上がった」と言わない）。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 検品の結果の種類 → 正解の崩れの種類（1 つの検品が複数の崩れを見つけることがある）
FOUND_BY = {"手の指": ["hands", "hands_clasped"], "頭身": ["heads_tall"], "背景の継ぎ目": ["seam"],
            "浮いた塊": ["extra_item", "background_pattern"], "靴の左右": ["shoes_mismatch"],
            "目の左右": ["eyes_closed"], "目の数": [], "端の切れ": [], "体の決まり": ["legs_overlap", "feet_perspective"],
            "背景の模様": ["background_pattern"], "余分な持ち物": ["extra_item"], "足りない持ち物": ["missing_item"],
            "服の色": ["outfit_color"], "輪郭の光": ["glow_outline"], "眉": ["eyebrow"], "目の開き": ["eyes_closed"]}


def kinds_found(r: dict) -> set[str]:
    out = set()
    for p in r["problems"] + r.get("look", []):
        out |= set(FOUND_BY.get(p["kind"], []))
        if p["kind"] == "測った値の外れ":
            path = json.dumps(p["detail"], ensure_ascii=False)
            if "eyes" in path or "face" in path:
                out.add("eyes_closed")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default=str(Path(__file__).resolve().parents[2] / "tests/fixtures/qc-labels.json"))
    a = ap.parse_args()
    import design  # noqa: F401
    import inspect_image
    lab = json.loads(Path(a.labels).read_text(encoding="utf-8"))
    root = Path(lab["root"])
    hit, miss = Counter(), Counter()
    rows = []
    for rel, want in lab["images"].items():
        r = inspect_image.inspect(str(root / rel), character=lab.get("characters", {}).get(rel))
        got = kinds_found(r)
        for k in want:
            (hit if k in got else miss)[k] += 1
        rows.append({"image": rel, "want": want, "found": sorted(got & set(want)), "missed": sorted(set(want) - got),
                     "raw": [p["kind"] for p in r["problems"] + r.get("look", [])]})
    total = sum(hit.values()) + sum(miss.values())
    print(json.dumps({"found": sum(hit.values()), "total": total, "by_kind": {k: f"{hit[k]}/{hit[k] + miss[k]}" for k in sorted(set(hit) | set(miss))},
                      "images": rows}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
