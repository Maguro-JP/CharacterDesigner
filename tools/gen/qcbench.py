"""検品単体（chatdraw/qcmanual.inspect、アプリの「検品する」と同じ経路）の精度の台。

    PYTHONPATH=.cache/simple/lib:.cache/gen/lib python3 tools/gen/qcbench.py [--limit N] [--json 出力.json]

正解は library/feedback/ の組の README の表。人が書いた「崩れ」の欄から、手・足・顔の崩れを部位ごとに読む。
人が「元の大きさで見て崩れを見つけていない」と書いた絵は、崩れの無い絵として使う。
どちらとも読めない行（部位を書いていない加工の記録など）は台に入れない（正解の無い絵で数字を作らない）。

出す数字:
- 取りこぼしの少なさ: 人が崩れと書いた部位のうち、検品がその部位に崩れか「検品できなかった」を返した割合
- 崩れの無い絵を崩れと言わなかった割合
- 場所: 取りこぼさなかった部位のうち、その部位の枠を返した割合（README に画素の枠が無いので、部位の枠があるかで見る）

検品の結果は .cache/qcbench/ に絵ごとに貯め、同じ絵（同じ大きさと更新時刻）は 2 度測らない。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "gen"))
from cdhome import HOME  # noqa: E402  置き場を組むのは cdhome だけ
FEEDBACK = ROOT / "library" / "feedback"
CACHE = HOME / "qcbench"

PARTS = {
    "hands": re.compile(r"(?<!足の)(手|指)(?!首から上)"),
    "feet": re.compile(r"足|つま先|爪先|かかと"),
    "faces": re.compile(r"顔|目|眉|瞳|口元|鼻"),
}
# 部位の語があっても崩れではない句（描けた・数が合う・崩れを見つけていない）
FINE = re.compile(r"描けた|正しい|自然|合っている|そろった|揃った|見つけていない|見つからない|崩れは無|崩れは無い|崩れなし|崩れ無し|[45５] ?本(で|ずつ|と)?(正し|そろ|合)|読めた|読める|直った|通った|元の画素に戻した")
CLEAN = re.compile(r"(目立つ)?崩れ(は|を)?(見つけていない|見つからない|無い|無し|なし)")
NOT_FLAW_WORDS = re.compile(r"検品の崩れ[^、。]*|目で見|網目|編み目|横顔|正面寄り|目の色|目の動き|目線|手前|手本|手順|手元の|手で描|手を加え|手の色の差|指示|指定|指摘|片手間|目立つ|一目|目安|見た目|二つ目|つ目|回目|枚目|番目|段目|目の大きさの比")


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def flaw_parts(text: str) -> set[str]:
    """崩れの欄の文から、崩れのある部位を読む。句ごとに見て、描けた・崩れが無いと書いた句は数えない"""
    out: set[str] = set()
    for sent in re.split(r"[。；;]|(?<=\D)\d\.\s*|、(?=\d\.)", text):
        s = NOT_FLAW_WORDS.sub("", sent)
        if not s.strip() or FINE.search(s):
            continue
        for k, rx in PARTS.items():
            if rx.search(s):
                out.add(k)
    return out


def _resolve(d: Path, name: str) -> list[Path]:
    name = name.strip().strip("`")
    out = []
    for n in re.split(r"\s*/\s*", name):
        if not n:
            continue
        p = d / n
        if p.suffix.lower() in (".jpg", ".png", ".jpeg") and p.exists():
            out.append(p)
            continue
        out += sorted(x for x in d.glob(n + ".*") if x.suffix.lower() in (".jpg", ".png", ".jpeg"))
    return out


def truth() -> list[dict]:
    """台の正解。絵ごとに {path, flaws: 部位の集合, clean: 崩れの無い絵か, text: 人の書いた崩れ}"""
    rows: dict[str, dict] = {}
    for readme in sorted(FEEDBACK.rglob("README.md")):
        head = None
        for line in readme.read_text(encoding="utf-8").splitlines():
            if not line.startswith("|"):
                head = None
                continue
            c = _cells(line)
            if head is None:
                head = c
                continue
            if set("".join(c)) <= set("-: "):
                continue
            col = next((i for i in range(len(head) - 1, -1, -1) if "崩れ" in head[i]), None)
            if col is None or col >= len(c) or "絵" not in head[0]:
                continue
            text = c[col]
            parts = flaw_parts(text)
            clean = not parts and bool(CLEAN.search(text))
            if not parts and not clean:
                continue
            for p in _resolve(readme.parent, c[0]):
                key = str(p.relative_to(ROOT))
                rows[key] = {"path": key, "flaws": sorted(parts), "clean": clean, "text": text[:200]}
    return list(rows.values())


def said(res: dict) -> dict:
    """検品の結果を部位ごとに読む。flag: 崩れか検品できなかったと返した部位、boxed: 崩れの枠を返した部位"""
    flag, boxed = set(), set()
    for k in ("hands", "feet", "faces"):
        for h in res.get(k, []) or []:
            if h.get("bad"):
                flag.add(k)
                if h.get("box"):
                    boxed.add(k)
    from chatdraw import qcmanual
    for line in qcmanual.unplaced(res) + qcmanual.missed(res):
        s = str(line)
        if s.startswith(("手", "指")):
            flag.add("hands")
        elif s.startswith(("足", "脚の指")):
            flag.add("feet")
        elif s.startswith(("顔", "目")):
            flag.add("faces")
    for b in res.get("bad", []):
        s = str(b)
        if s.startswith("顔") or "目" in s[:4]:
            flag.add("faces")
    # 映り込みの矛盾か「比べていない」を返した絵。崩れの無い絵でこれを返せば、崩れの無い絵を崩れと言ったことになる
    m = res.get("mirror") or {}
    if m.get("flaws") or m.get("reason"):
        flag.add("mirror")
    return {"flag": sorted(flag), "boxed": sorted(boxed)}


def _mirror(path: Path) -> dict:
    """映り込みの検品だけ（sanity.check と同じタグと同じ mirrorcheck）"""
    from PIL import Image
    from chatdraw import mirrorcheck
    from chatdraw.paths import use_tools_gen
    use_tools_gen()
    import tagger
    m = mirrorcheck.check(Image.open(path).convert("RGB"), tagger.read(str(path)))
    return {"gated": m.get("gated", []), "flaws": m.get("flaws", []), "reason": m.get("reason")}


def run_one(path: Path) -> dict:
    st = path.stat()
    CACHE.mkdir(parents=True, exist_ok=True)
    key = CACHE / (re.sub(r"[^\w.-]", "_", str(path.relative_to(ROOT))) + ".json")
    stamp = f"{st.st_size}:{int(st.st_mtime)}"
    if key.exists():
        d = json.loads(key.read_text(encoding="utf-8"))
        if d.get("stamp") == stamp:
            if "mirror" not in d["res"]:
                # 映り込みの検品を足す前に貯めた結果。手・足・顔は測り直さず、映り込みだけを足す
                d["res"]["mirror"] = _mirror(path)
                key.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            return d["res"]
    from PIL import Image
    from chatdraw import qcmanual
    res = qcmanual.inspect(Image.open(path))
    keep = {k: res.get(k) for k in ("bad", "body_bad", "reason", "feet_reason", "body_reason", "legs_reason", "readable")}
    keep["hands"] = [{"box": h.get("box"), "bad": h.get("bad")} for h in res.get("hands", []) or []]
    keep["feet"] = [{"box": h.get("box"), "bad": h.get("bad")} for h in res.get("feet", []) or []]
    keep["faces"] = [{"box": h.get("box"), "bad": h.get("bad")} for h in res.get("faces", []) or []]
    m = res.get("mirror") or {}
    keep["mirror"] = {"gated": m.get("gated", []), "flaws": m.get("flaws", []), "reason": m.get("reason")}
    f = res.get("face") or {}
    keep["face"] = {"readable": f.get("readable"), "bad": f.get("bad"), "reason": f.get("reason")}
    key.write_text(json.dumps({"stamp": stamp, "res": keep}, ensure_ascii=False), encoding="utf-8")
    return keep


def score(rows: list[dict], results: dict) -> dict:
    hit = miss = boxed = clean_ok = clean_n = 0
    by = {k: {"hit": 0, "miss": 0} for k in PARTS}
    missed_list = []
    for r in rows:
        if r["path"] not in results:
            continue
        s = said(results[r["path"]])
        for k in r["flaws"]:
            if k in s["flag"]:
                hit += 1
                by[k]["hit"] += 1
                boxed += k in s["boxed"]
            else:
                miss += 1
                by[k]["miss"] += 1
                missed_list.append((r["path"], k, r["text"][:80]))
        if r["clean"]:
            clean_n += 1
            clean_ok += not s["flag"]
    pct = lambda a, b: round(100 * a / b, 1) if b else None   # noqa: E731
    seen = [results[r["path"]] for r in rows if r["path"] in results]
    gated = sum(1 for x in seen if (x.get("mirror") or {}).get("gated"))
    mflag = sum(1 for x in seen if "mirror" in said(x)["flag"])
    return {"mirror_gated": gated, "mirror_flagged": mflag, "flaw_parts": hit + miss, "caught": pct(hit, hit + miss), "clean_images": clean_n,
            "clean_quiet": pct(clean_ok, clean_n), "located": pct(boxed, hit), "by_part": by, "missed": missed_list}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", default="")
    ap.add_argument("--truth-only", action="store_true")
    a = ap.parse_args(argv)
    rows = truth()
    print(f"台: {len(rows)} 枚（崩れのある絵 {sum(bool(r['flaws']) for r in rows)}、崩れの無い絵 {sum(r['clean'] for r in rows)}）", flush=True)
    if a.truth_only:
        for r in rows:
            print(r["path"], r["flaws"], r["clean"])
        return 0
    results = {}
    for i, r in enumerate(rows[: a.limit or None], 1):
        try:
            results[r["path"]] = run_one(ROOT / r["path"])
        except Exception as e:   # noqa: BLE001  落ちた絵は「検品できなかった」として数えない（台から外したと出す）
            print(f"落ちた: {r['path']}: {e}", flush=True)
        if i % 20 == 0:
            print(f"{i}/{len(rows)}", flush=True)
    sc = score(rows, results)
    print(json.dumps({k: v for k, v in sc.items() if k != "missed"}, ensure_ascii=False))
    for m in sc["missed"]:
        print("取りこぼし:", *m)
    if a.json:
        Path(a.json).write_text(json.dumps(sc, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
