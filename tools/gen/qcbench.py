"""検品単体（chatdraw/qcmanual.inspect、アプリの「検品する」と同じ経路）の精度の台。

    PYTHONPATH=.cache/simple/lib:.cache/gen/lib python3 tools/gen/qcbench.py [--limit N] [--json 出力.json]

正解は library/feedback/ の組の README の表。人が書いた「崩れ」の欄から、手・足・顔の崩れを部位ごとに読む。
人が「元の大きさで見て崩れを見つけていない」と書いた絵は、崩れの無い絵として使う。
どちらとも読めない行（部位を書いていない加工の記録など）は台に入れない（正解の無い絵で数字を作らない）。

出す数字:
- 取りこぼしの少なさ: 人が崩れと書いた部位のうち、検品がその部位に崩れか「検品できなかった」を返した割合
- 崩れの無い絵を崩れと言わなかった割合
- 場所: 取りこぼさなかった部位のうち、その部位の枠を返した割合（README に画素の枠が無いので、部位の枠があるかで見る）

検品の結果は .cache/qcbench/ に絵ごとに貯め、同じ絵（同じ中身）は 2 度測らない。
"""
from __future__ import annotations

import argparse
import hashlib
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
# 検品の仕組みを直したら上げる。貯めた結果を古い検品のまま使わず、途中で止まっても続きから測れる
QC_VERSION = "4"

PARTS = {
    "hands": re.compile(r"(?<!足の)(手|指)(?!首から上)"),
    "feet": re.compile(r"足|つま先|爪先|かかと"),
    "faces": re.compile(r"顔|目|眉|瞳|口元|鼻"),
}
# 部位の語があっても崩れではない句（描けた・数が合う・崩れを見つけていない）
FINE = re.compile(r"描けた|正しい|自然|合っている|そろった|揃った|見つけていない|見つからない|崩れは無|崩れは無い|崩れなし|崩れ無し|[45５] ?本(で|ずつ|と)?(正し|そろ|合)|読めた|読める|直った|通った|元の画素に戻した")
CLEAN = re.compile(r"(目立つ)?崩れ(は|を)?(見つけていない|見つからない|無い|無し|なし)")
# 形の崩れではない句（元の大きさで絵を見て確かめた）: 横顔の向き、設定と違う目の色、正座の座り方
NOT_FLAW_WORDS = re.compile(r"顔が横顔に近い|目が(赤|青|緑|黒|茶|金|紫)い[^、。]*|かかとの上に正座[^、。]*|検品の崩れ[^、。]*|目で見|網目|編み目|横顔|正面寄り|目の色|目の動き|目線|手前|手本|手順|手元の|手で描|手を加え|手の色の差|指示|指定|指摘|片手間|目立つ|一目|目安|見た目|二つ目|つ目|回目|枚目|番目|段目|目の大きさの比")


# 崩れの種類ごとの台（score_cats）。人の書いた崩れの欄を句ごとに読み、どの種類の崩れかを決める。
# 手・足・顔の 3 つでは「片手を腰に当てた」（姿勢）も手の崩れに数え、指の数の崩れと手の形の崩れを分けて測れなかった
CATS = {
    "fingers": ("指の数", re.compile(r"指[^、。]{0,12}(読めない|崩れ|数えにく|数えられ|本数|多い|足りな|[3467６]\s?本|くっつ|透け)")),
    "hand_shape": ("手の形", re.compile(r"手(?![^、。]{0,3}指)[^、。首]{0,10}(崩れ|溶け|潰れ|形が|浮く|読めない)|指が崩れた手")),
    "feet": ("足", re.compile(r"(足先|足首|両足|片足|足の指|つま先|かかと|足が)[^、。]{0,14}(重な|溶け|読め|崩|透け|暗く|形|切れ|寄り|1\s?本)")),
    "eyes": ("目", re.compile(r"片目|目が(隠|ぼや|溶|消|多|無)|瞳|白目|眉")),
    "mouth": ("口", re.compile(r"口|唇|歯")),
    "face": ("顔の歪み", re.compile(r"顔[^、。]{0,10}(歪|半分|浮い|まだら|斑|無く|隠れ|読みにく|崩)|耳の位置|鼻[^、。]{0,4}線")),
    "limbs": ("腕と脚の数", re.compile(r"腕が\s?[3３三]\s?本|腕[^、。]{0,8}本数|脚が[^、。]{0,10}1\s?本に溶け|膝から下が無い|脚が多い|腕が多い")),
    "lr": ("左右の取り違え", re.compile(r"左右[^、。]{0,4}(逆|取り違|入れ替)|右手と左手が逆")),
    "mirror": ("鏡や映り込みの矛盾", re.compile(r"鏡|映り込|映り")),
    "missing": ("頼んだ物が描かれていない", re.compile(r"頼んだ[^、。]{0,10}(無く|無い|描かれていない|消え)|[^、。]{1,8}が消え")),
    "extra": ("頼んでいない物がある", re.compile(r"頼んでいない|剣が\s?2\s?本|2\s?本を持つ")),
}
# 姿勢・位置・見え方の句（崩れではない）。手が見えない・腰に当てたは、指の数の崩れでも手の形の崩れでもない
CAT_SKIP = re.compile(r"[45５]\s?本(読め|ずつ|で正)|指は読める|読めて外れ無し|元の画素に戻した|加工では直さない")


def flaw_cats(text: str) -> set[str]:
    """崩れの欄の文から、崩れの種類を読む。句ごとに見て、描けた・読めたと書いた句は数えない"""
    out: set[str] = set()
    for sent in re.split(r"[。；;、]|(?<=\D)\d\.\s*", text):
        s = NOT_FLAW_WORDS.sub("", sent)
        if not s.strip() or CAT_SKIP.search(s):
            continue
        for k, (_, rx) in CATS.items():
            if rx.search(s):
                out.add(k)
    return out


def asked_tags(cell: str) -> str:
    """README の「言葉」の欄から、絵の模型に渡したタグ（英語のカンマ区切り）だけを取る。日本語の説明は捨てる"""
    out = []
    for frag in re.findall(r"[A-Za-z][A-Za-z0-9 ,:()'_.-]*", cell.replace("`", "")):
        for t in frag.split(","):
            t = re.sub(r"[():]|\b\d+(\.\d+)?\b", "", t).strip().lower()
            if len(t) > 1 and t not in out:
                out.append(t)
    return ", ".join(out)


def tags_of(path: Path) -> dict:
    """絵のタグ（wd-vit-tagger-v3、確からしさ 0.05 以上）。中身の sha1 で .cache/qcbench/tags/ に貯める"""
    d = CACHE / "tags"
    d.mkdir(parents=True, exist_ok=True)
    key = d / (hashlib.sha1(path.read_bytes()).hexdigest() + ".json")
    if key.exists():
        return json.loads(key.read_text(encoding="utf-8"))
    from chatdraw.requestcheck import _tagger
    got = _tagger(False).read(str(path), threshold=0.05)
    key.write_text(json.dumps(got), encoding="utf-8")
    return got


def request_of(path: Path, asked: str) -> dict:
    """頼んだ物の検品（chatdraw/requestcheck.py と同じ missing / extras / people）を、貯めたタグで流す"""
    from chatdraw import requestcheck
    if not asked:
        return {}
    got = tags_of(path)
    tg = requestcheck._tagger(False)
    return {"readable": True, "missing": tg.missing(asked, got), "extra": tg.extras(asked, got),
            "people": requestcheck.people(asked, got)}


UNREAD = re.compile(r"読めない|読めません|数えられない|数えきれない|見つからず|部品がありません|検品できなかった")


def said_cats(res: dict) -> tuple[set[str], set[str]]:
    """検品の結果を種類ごとに読む。(崩れと言い切った種類, 読めない・検品できなかったと返した種類)"""
    sure, unread = set(), set()

    def put(k, line):
        (unread if UNREAD.search(str(line)) else sure).add(k)
    for h in res.get("hands", []) or []:
        for b in h.get("bad", []) or []:
            put("fingers" if re.search(r"指が(足りない|多い)|薄い指|指を数え|指の扇", str(b)) else "hand_shape", b)
    for h in res.get("feet", []) or []:
        for b in h.get("bad", []) or []:
            put("feet", b)
    face_lines = list((res.get("face") or {}).get("bad") or []) + [b for f in res.get("faces", []) or [] for b in f.get("bad", []) or []]
    for b in face_lines:
        s = str(b)
        put("mouth" if "口" in s else "eyes" if "目" in s else "face", s)
    for b in res.get("body_bad", []) or []:
        s = str(b)
        if s.startswith(("目",)):
            put("eyes", s)
        elif s.startswith("口"):
            put("mouth", s)
        elif s.startswith(("顔", "頭", "額")):
            put("face", s)
        elif s.startswith(("腕", "脚", "体", "人")):
            put("limbs", s)
        elif "左右" in s:
            put("lr", s)
    for b in res.get("bad", []) or []:
        s = str(b)
        if s.startswith("脚") or "脚の本数" in s:
            put("limbs", s)
    m = res.get("mirror") or {}
    if m.get("flaws"):
        sure.add("mirror")
    elif m.get("gated") and m.get("reason"):
        unread.add("mirror")   # 鏡か映り込みを読んだのに比べられなかった。比べていない映り込みを通さない
    r = res.get("request") or {}
    if r.get("missing"):
        sure.add("missing")
    if r.get("extra"):
        sure.add("extra")
    if r and not r.get("readable", True):
        unread |= {"missing", "extra"}
    for line in (res.get("feet_reason"),):
        if line:
            unread.add("feet")
    if res.get("reason"):
        unread |= {"fingers", "hand_shape"}
    f = res.get("face") or {}
    if f and not f.get("readable") and not f.get("bad") and f.get("reason") and "写っていない" not in str(f.get("reason")):
        unread |= {"eyes", "mouth", "face"}
    return sure, unread - sure


def score_cats(rows: list[dict], results: dict) -> dict:
    """種類ごとの見つけた率と誤報の率。
    見つけた率: 人がその種類の崩れを書いた絵のうち、検品がその種類に崩れか「読めない」を返した割合（読めないは崩れとして数える決まり）。
    言い切った率: 同じ絵のうち、「読めない」ではなく崩れと言い切った割合。
    誤報の率: 人がその種類の崩れを書いていない絵のうち、検品がその種類に崩れと言い切った割合（人は目立つ崩れだけを書くので、
    本当の崩れも混じる。上限の見積もり）。崩れの無い絵（人が崩れを見つけていないと書いた絵）での誤報は clean_false に分けて出す"""
    out = {}
    for k, (name, _) in CATS.items():
        pos = hit = sure_hit = neg = fp = unread_neg = cneg = cfp = 0
        for r in rows:
            if r["path"] not in results:
                continue
            sure, unread = said_cats(results[r["path"]])
            if k in r.get("cats", []):
                pos += 1
                hit += k in sure or k in unread
                sure_hit += k in sure
            else:
                neg += 1
                fp += k in sure
                unread_neg += k in unread
                if r["clean"]:
                    cneg += 1
                    cfp += k in sure or k in unread
        pct = lambda a, b: round(100 * a / b, 1) if b else None   # noqa: E731
        out[k] = {"name": name, "positives": pos, "caught": pct(hit, pos), "sure": pct(sure_hit, pos),
                  "negatives": neg, "false": pct(fp, neg), "unread_on_neg": pct(unread_neg, neg),
                  "clean": cneg, "clean_false": pct(cfp, cneg)}
    return out


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


def truth(with_cats: bool = False) -> list[dict]:
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
            wcol = next((i for i, x in enumerate(head) if "言葉" in x), None)
            asked = asked_tags(c[wcol]) if wcol is not None and wcol < len(c) else ""
            parts = flaw_parts(text)
            cats = flaw_cats(text)
            clean = not parts and not cats and bool(CLEAN.search(text))
            if not parts and not clean and not (cats and with_cats):
                continue
            for p in _resolve(readme.parent, c[0]):
                key = str(p.relative_to(ROOT))
                rows[key] = {"path": key, "flaws": sorted(parts), "cats": sorted(cats), "clean": clean, "text": text[:200], "asked": asked}
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
    # 体の検品（chatdraw/sanity.py）の崩れ: 余分な目・口・顔・頭は顔、腕は手、脚は足として数える。
    # 「目が多い」「腕が多い」は手・足・顔で始まらないので、台で数えられていなかった
    for b in res.get("body_bad", []) or []:
        s = str(b)
        if s.startswith(("目", "口", "顔", "頭", "額")):
            flag.add("faces")
        elif s.startswith(("腕", "手")):
            flag.add("hands")
        elif s.startswith(("脚", "足")):
            flag.add("feet")
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


def cached(path: Path) -> dict | None:
    """貯めた結果（同じ中身・同じ版の検品）。無ければ None"""
    key = CACHE / (re.sub(r"[^\w.-]", "_", str(path.relative_to(ROOT))) + ".json")
    if not key.exists():
        return None
    d = json.loads(key.read_text(encoding="utf-8"))
    stamp = "sha1:" + hashlib.sha1(path.read_bytes()).hexdigest() + ":" + QC_VERSION
    return d["res"] if d.get("stamp") == stamp else None


def run_one(path: Path, fresh: bool = False) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    key = CACHE / (re.sub(r"[^\w.-]", "_", str(path.relative_to(ROOT))) + ".json")
    # 中身の sha1 で見る。更新時刻は worktree ごとに違い、同じ絵を 40 分かけて測り直していた
    stamp = "sha1:" + hashlib.sha1(path.read_bytes()).hexdigest() + ":" + QC_VERSION
    if key.exists() and not fresh:
        d = json.loads(key.read_text(encoding="utf-8"))
        if d.get("stamp") == stamp:
            if "mirror" not in d["res"]:
                # 映り込みの検品を足す前に貯めた結果。手・足・顔は測り直さず、映り込みだけを足す
                try:
                    d["res"]["mirror"] = _mirror(path)
                except Exception:   # noqa: BLE001  タグを読む部品が無い・読めない絵。映り込みは測らず、貯めた結果をそのまま使う
                    return d["res"]
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
    false_by = {k: 0 for k in PARTS}   # 崩れの無い絵で、部位ごとに崩れと言った枚数（誤報がどの部位から出るか）
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
            for k in s["flag"]:
                false_by[k] += 1
    pct = lambda a, b: round(100 * a / b, 1) if b else None   # noqa: E731
    seen = [results[r["path"]] for r in rows if r["path"] in results]
    gated = sum(1 for x in seen if (x.get("mirror") or {}).get("gated"))
    mflag = sum(1 for x in seen if "mirror" in said(x)["flag"])
    return {"mirror_gated": gated, "mirror_flagged": mflag, "flaw_parts": hit + miss, "caught": pct(hit, hit + miss), "clean_images": clean_n,
            "clean_quiet": pct(clean_ok, clean_n), "false_by_part": false_by, "located": pct(boxed, hit), "by_part": by, "missed": missed_list}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", default="")
    ap.add_argument("--truth-only", action="store_true")
    ap.add_argument("--score-only", action="store_true", help="貯めた結果だけで採点する（測らない）")
    ap.add_argument("--shard", default="", help="i/n: 台の絵を n に分けた i 番目（0 から）だけを測る（Actions で並べて流す）")
    ap.add_argument("--fresh", action="store_true", help="貯めた結果を使わず測り直す（検品の仕組みを直したあと）")
    a = ap.parse_args(argv)
    rows = truth(with_cats=True)
    print(f"台: {len(rows)} 枚（崩れのある絵 {sum(bool(r['flaws']) for r in rows)}、崩れの無い絵 {sum(r['clean'] for r in rows)}）", flush=True)
    if a.truth_only:
        for r in rows:
            print(r["path"], r["flaws"], r["clean"])
        return 0
    results = {}
    if a.shard:
        k, n = (int(x) for x in a.shard.split("/"))
        rows = rows[k::n]
    for i, r in enumerate(rows[: a.limit or None], 1):
        try:
            if a.score_only:
                got = cached(ROOT / r["path"])
                if got is None:
                    continue
                results[r["path"]] = dict(got)
            else:
                results[r["path"]] = dict(run_one(ROOT / r["path"], a.fresh))
            try:
                results[r["path"]]["request"] = request_of(ROOT / r["path"], r.get("asked", ""))
            except Exception as e:   # noqa: BLE001  タグを読む部品が無い。頼んだ物は「検品できなかった」として数える
                results[r["path"]]["request"] = {"readable": False, "reason": str(e)}
        except Exception as e:   # noqa: BLE001  落ちた絵は「検品できなかった」として数えない（台から外したと出す）
            print(f"落ちた: {r['path']}: {e}", flush=True)
        if i % 20 == 0:
            print(f"{i}/{len(rows)}", flush=True)
    old = [r for r in rows if r["flaws"] or r["clean"]]
    sc = score(old, results)
    sc["cats"] = score_cats(rows, results)
    print(json.dumps({k: v for k, v in sc.items() if k not in ("missed", "cats")}, ensure_ascii=False))
    print("| 種類 | 崩れの絵 | 見つけた率 | 言い切った率 | 誤報の率 | 崩れの無い絵での誤報 |")
    for v in sc["cats"].values():
        print(f"| {v['name']} | {v['positives']} | {v['caught']} | {v['sure']} | {v['false']} | {v['clean_false']}（{v['clean']} 枚） |")
    for m in sc["missed"]:
        print("取りこぼし:", *m)
    if a.json:
        Path(a.json).write_text(json.dumps(sc, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
