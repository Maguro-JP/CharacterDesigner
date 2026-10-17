"""作画監督の基準を、描いた絵と判定と指摘から学び続ける。

  PYTHONPATH=.cache/gen/lib python3 tools/gen/normlearn.py record 絵.png --verdict pass|reject [--by checker|user] [--reason "..."] [--hair "#rrggbb"]
  PYTHONPATH=.cache/gen/lib python3 tools/gen/normlearn.py learn [--dry]
  PYTHONPATH=.cache/gen/lib python3 tools/gen/normlearn.py status

記録（record）: 絵を measure.py で測り、数字と判定（通す・戻す）と理由を .cache/app/learn/records.jsonl に足す。
  理由の言葉から関わる数字（顔の形、影、髪など）を結びつける。戻された絵で、関わる数字が外れを出していなければ「見逃し」、
  どの数字にも結びつかない理由は「数字にない指摘」として残す（次に作る検品の候補）。
学習（learn）: 基準ごとに、通った絵と戻された絵を最もよく分ける境を計算し直し、config/norms.user.json に書く。
  共通の基準（styles/anime-norms.json）は変えない。判定の時は利用者の基準を上に重ねる（measure.load_norms）。
  境は「通った絵の最大と戻された絵の最小の間」。重なって分けきれないときは境を動かさず、食い違いとして報告する。
  戻された絵は、その基準に関わる理由で戻されたものだけを手本にする（理由の言葉の話題か、その基準が外れを出したもの）。
  利用者の判定（--by user）は作画監督の判定の 3 倍の重みで数える。少ない手本で境が振れないよう、各基準 両側に 2 枚以上そろうまでは動かさない。
記録は利用者のデータなのでリポジトリに入れない。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / ".cache" / "app" / "learn"
RECORDS = STORE / "records.jsonl"
USER_NORMS = ROOT / "config" / "norms.user.json"

# 指摘の言葉と、それに関わる数字。言葉は日本語と英語の両方を持つ（利用者は日本語だけで使うとは限らない）
TOPICS = {
    "face": (["顔", "目", "瞳", "口", "歪", "左右", "face", "eye", "mouth", "asymmetr", "distort"], ["face.rms", "eyes.found"]),
    "shadow": (["影", "光", "明る", "暗", "逆光", "shadow", "light", "bright", "dark"], ["light.inverted", "light.side_conflict", "scene.backlit_front", "limbs.across_max", "limbs.leg_dark_gap"]),
    "hair": (["髪", "毛", "インナー", "白飛", "飛んで", "hair", "blown"], ["hair.blown", "hair.spec_off"]),
    "pairs": (["靴", "籠手", "手袋", "片方", "片手", "pair", "shoe", "glove", "gauntlet", "mismatch"], ["pairs.shoes.color", "pairs.arms.color"]),
}
MIN_EACH_SIDE = 2
USER_WEIGHT = 3


def topics_of(reason: str) -> list[str]:
    r = reason.lower()
    return [t for t, (words, _) in TOPICS.items() if any(w.lower() in r for w in words)]


def _get(d, path):
    for k in path.split("."):
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def record(src, verdict: str, by: str = "checker", reason: str = "", hair: str = "") -> dict:
    import measure
    if verdict not in ("pass", "reject"):
        raise ValueError("verdict は pass か reject")
    m = measure.measure(src, hair)
    flagged = [o["path"] for o in measure.judge(m)]
    tops = topics_of(reason)
    related = [p for t in tops for p in TOPICS[t][1]]
    rec = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "src": str(src), "verdict": verdict, "by": by, "reason": reason,
           "hair": hair, "topics": tops, "flagged": flagged, "measure": m}
    if verdict == "reject":
        # 見逃し: 理由に関わる数字があるのに、どれも外れを出していない
        rec["missed"] = [p for p in related if p not in flagged] if related and not set(related) & set(flagged) else []
        rec["unmeasured"] = bool(reason) and not tops
    else:
        # 誤って外れにした: 通った絵で外れを出した数字
        rec["false_alarm"] = flagged
    STORE.mkdir(parents=True, exist_ok=True)
    with RECORDS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {k: rec[k] for k in ("verdict", "by", "topics", "flagged") } | {k: rec[k] for k in ("missed", "unmeasured", "false_alarm") if k in rec}


def records() -> list[dict]:
    if not RECORDS.exists():
        return []
    out = []
    for line in RECORDS.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    # 同じ絵を何度も判定したら、最後の判定を使う（利用者が作画監督の判定を覆したときなど）
    last = {}
    for r in out:
        last[r["src"]] = r
    return list(last.values())


def _boundary(passed: list[tuple[float, int]], rejected: list[tuple[float, int]], direction: str):
    """値が大きいほど悪い（direction="max"）基準の境を決める。返すのは (境, 分けきれたか, 誤りの重み)"""
    if direction == "min":
        passed = [(-v, w) for v, w in passed]
        rejected = [(-v, w) for v, w in rejected]
    cands = sorted({v for v, _ in passed + rejected})
    best = None
    for i in range(len(cands)):
        t = cands[i] if i + 1 == len(cands) else (cands[i] + cands[i + 1]) / 2
        # 境 t より上を外れとする。誤り = 通った絵を外れにした重み + 戻された絵を見逃した重み（見逃しを 2 倍重く数える）
        err = sum(w for v, w in passed if v > t) + 2 * sum(w for v, w in rejected if v <= t)
        if best is None or err < best[1]:
            best = (t, err)
    t, err = best
    clean = err == 0
    return (-t if direction == "min" else t), clean, err


def learn(dry: bool = False) -> dict:
    import measure
    base = json.loads(measure.NORMS.read_text(encoding="utf-8"))
    recs = records()
    changes, kept = [], []
    user = {"about": "利用者の判定から学んだ基準。styles/anime-norms.json の同じ path の基準を上書きする（tools/gen/normlearn.py learn）",
            "updated": time.strftime("%Y-%m-%d"), "checks": []}
    for c in base["checks"]:
        if c.get("when"):
            continue
        direction = "max" if c.get("max") is not None else "min"
        vals = []
        for r in recs:
            v = _get(r["measure"], c["path"])
            if v is None:
                continue
            v = abs(v) if c.get("abs") else v
            rel = c["path"] in [p for t in r.get("topics", []) for p in TOPICS[t][1]] or c["path"] in r.get("flagged", [])
            vals.append((float(v), r["verdict"], USER_WEIGHT if r.get("by") == "user" else 1, rel))
        passed = [(v, w) for v, verdict, w, _ in vals if verdict == "pass"]
        # 戻された絵は、この基準に関わる理由（理由の言葉の話題、またはこの基準が外れを出したもの）で戻されたものだけを数える。
        # 剣が 2 本で戻された絵まで顔の形の手本に数えると、顔の境が 0.07 から 0.017 まで締まり、正しい顔を外れにした
        rejected = [(v, w) for v, verdict, w, rel in vals if verdict == "reject" and rel]
        if len(passed) < MIN_EACH_SIDE or len(rejected) < MIN_EACH_SIDE:
            kept.append({"path": c["path"], "why": f"手本が足りない（通った {len(passed)}・戻された {len(rejected)}）"})
            continue
        t, clean, err = _boundary(passed, rejected, direction)
        old = c[direction]
        if not clean:
            # 通った絵と戻された絵が重なって分けきれない。境を動かすと片方を必ず誤るので、共通の基準のまま残し、食い違いとして見せる
            kept.append({"path": c["path"], "why": f"通った絵と戻された絵が重なって分けきれない（誤りの重み {err}）。この数字だけでは決まらない崩れか、判定の食い違い"})
            continue
        new = dict(c)
        new[direction] = round(t, 4)
        new["learned"] = {"passed": len(passed), "rejected": len(rejected), "separable": clean, "error_weight": err, "base": old}
        user["checks"].append(new)
        changes.append({"path": c["path"], direction: [old, new[direction]], "separable": clean,
                        "passed": len(passed), "rejected": len(rejected)})
    unmeasured = [{"src": r["src"], "reason": r["reason"]} for r in recs if r.get("unmeasured")]
    missed = [{"src": r["src"], "reason": r["reason"], "missed": r["missed"]} for r in recs if r.get("missed")]
    if not dry and user["checks"]:
        USER_NORMS.parent.mkdir(parents=True, exist_ok=True)
        USER_NORMS.write_text(json.dumps(user, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"changed": changes, "kept": kept, "missed": missed, "unmeasured": unmeasured, "records": len(recs), "written": (not dry and bool(user["checks"]))}


def status() -> dict:
    recs = records()
    return {"records": len(recs), "pass": sum(r["verdict"] == "pass" for r in recs), "reject": sum(r["verdict"] == "reject" for r in recs),
            "by_user": sum(r.get("by") == "user" for r in recs),
            "missed": sum(bool(r.get("missed")) for r in recs), "unmeasured": [r["reason"] for r in recs if r.get("unmeasured")],
            "false_alarm": sum(bool(r.get("false_alarm")) for r in recs), "user_norms": USER_NORMS.exists()}


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("src")
    r.add_argument("--verdict", required=True, choices=["pass", "reject"])
    r.add_argument("--by", default="checker", choices=["checker", "user"])
    r.add_argument("--reason", default="")
    r.add_argument("--hair", default="")
    lp = sub.add_parser("learn")
    lp.add_argument("--dry", action="store_true")
    sub.add_parser("status")
    a = ap.parse_args()
    if a.cmd == "record":
        out = record(a.src, a.verdict, a.by, a.reason, a.hair)
    elif a.cmd == "learn":
        out = learn(a.dry)
    else:
        out = status()
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
