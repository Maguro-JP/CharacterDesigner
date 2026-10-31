"""背景だけを描くモード。人物を描かずに、設定資料集の世界観の場所（bible/worlds）から場面を描き、あとで人物と重ねられる背景を出す。

描く処理は layers.background を使い回す（no humans を先頭に置き、目の高さ・地平線を中ほどに描かせる）。
人物が混ざっていないかは、部位分けより軽い絵のタグ（tagger.read）で見る。1girl・solo などが出たら描き直す。
パース（消失点に線が集まるか、柱が傾いていないか）は perspective.measure で測り、qc.json の perspective に残す。
地平線の高さを記録しておくと、合成のときに足元と地平線から人物の大きさが決まる（layers.perspective_height）。

使い方:
  PYTHONPATH=.cache/gen/lib python3 tools/gen/background.py draw <world> <location> <出力フォルダ> \\
      [--count 1] [--seed 7] [--size 1216x832|832x1216]
出力: <world>-<location>-<seed>.png と、その検品の結果 <絵>.qc.json
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

SIZES = {"1216x832": (1216, 832), "832x1216": (832, 1216)}   # 横長が既定（background-artist の決まり）
# 人物がいると出るタグ。数の付いた girl/boy（2girls、6+boys）は名前の形で拾う
PERSON_TAGS = {"solo", "person", "1other", "multiple others", "multiple girls", "multiple boys", "male focus",
               "female focus", "faceless", "silhouette", "crowd", "6+others"}
COUNTED = re.compile(r"^\d+\+?(girl|boy|other)s?$")   # 1girl、2boys、6+girls
PERSON_THRESHOLD = 0.35


def scene_words(world: str, location: str) -> tuple[str, str]:
    """場所の言葉と世界観の言葉から、背景の言葉と描かせない言葉を作る。場所を先に置く（先頭ほど強く効く）"""
    import bible
    import layers
    w = bible.load("worlds", world)
    loc = next((x for x in w["locations"] if x["id"] == location), None)
    if loc is None:
        raise SystemExit(f"世界観 {world} に場所 {location} が無い（{[x['id'] for x in w['locations']]}）")
    scene = ", ".join(t.strip() for t in (loc.get("tags", ""), w.get("tags", "")) if t and t.strip())
    negative = ", ".join(x for x in (layers.BG_NEGATIVE, loc.get("avoid", "")) if x)
    return scene, negative


def person_tags(tags: dict, threshold: float = PERSON_THRESHOLD) -> dict:
    """タグのうち人物を示すものと確からしさ。空なら人物は描かれていない"""
    return {t: p for t, p in tags.items() if p >= threshold and (t in PERSON_TAGS or COUNTED.match(t))}


# パースの崩れの目安。citadel の門と広間で測った値（傾き 1.0 と 7.8 度、集まる割合 0.51 と 0.41）から決めた。
# まだ 2 枚でしか測っていないので、通す・戻すには使わず、気づいた所として qc.json に残すだけにする
TILT_WARN = 5.0          # 縦の線の傾き（度）
GAP_WARN = 0.1           # 2 つの消失点の高さの差（画面の高さの割合）
CONVERGE_WARN = 0.3      # 消失点に集まる奥行きの線の割合


def perspective_check(im) -> dict:
    """背景のパースを測り（perspective.measure）、目安を外れた所を warnings に書く"""
    import perspective
    try:
        m = perspective.measure(im)
    except Exception as e:      # skimage が無い環境でも検品の結果は残す
        return {"error": str(e)}
    w = []
    if m["vertical_tilt"] is not None and m["vertical_tilt"] > TILT_WARN:
        w.append(f"縦の線が傾いている（{m['vertical_tilt']} 度）")
    if m["horizon_gap"] is not None and m["horizon_gap"] > GAP_WARN:
        w.append(f"消失点の高さがそろわない（差 {m['horizon_gap']}）")
    if m["converge"] is not None and m["converge"] < CONVERGE_WARN:
        w.append(f"奥へ向かう線が消失点に集まらない（{m['converge']}）")
    return {**m, "warnings": w}


def write_qc(png: Path, tags: dict, horizon, meta: dict) -> Path:
    found = person_tags(tags)
    qc = {"pass": not found, "reasons": [f"人物のタグ {t}（{p}）" for t, p in sorted(found.items())],
          "person_tags": found, "horizon": None if horizon is None else round(horizon, 4), **meta}
    out = png.with_suffix(".qc.json")
    out.write_text(json.dumps(qc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out


def draw(world: str, location: str, outdir: str, count: int = 1, seed: int = 7, size=(1216, 832)) -> list[dict]:
    import tagger
    import layers
    scene, negative = scene_words(world, location)
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for i in range(count):
        s = seed + i * 1000          # layers.background は描き直しで seed + 100 ずつ進めるので、重ならない間を空ける
        png = out / f"{world}-{location}-{s}.png"
        last = {}

        def check(im):
            # 検品のタグは描き直しの判定と qc.json で1回だけ読む
            im.save(png)
            last["tags"] = tagger.read(str(png))
            return bool(person_tags(last["tags"]))

        im = layers.background(scene, s, size=size, negative=negative, check=check)
        im.save(png)
        try:
            hz = layers.horizon(im)
        except Exception as e:      # 奥行きの模型が無い環境でも検品の結果は残す
            print(f"地平線を測れなかった: {e}", file=sys.stderr)
            hz = None
        meta = {"world": world, "location": location, "seed": s, "size": list(size), "prompt": scene, "negative": negative,
                "perspective": perspective_check(im)}
        results.append({"image": str(png), "qc": str(write_qc(png, last.get("tags", {}), hz, meta))})
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draw")
    d.add_argument("world"); d.add_argument("location"); d.add_argument("outdir")
    d.add_argument("--count", type=int, default=1); d.add_argument("--seed", type=int, default=7)
    d.add_argument("--size", default="1216x832", choices=sorted(SIZES))
    a = ap.parse_args()
    print(json.dumps(draw(a.world, a.location, a.outdir, a.count, a.seed, SIZES[a.size]), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
