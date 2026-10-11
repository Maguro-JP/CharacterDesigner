"""設定資料集: キャラクターと世界観を保存し、場面・構図・服・ポーズを変えても同じキャラクターとして描かせる。

画像生成の AI はキャラクターを覚えない。同じ頼み方でも、描くたびに顔・髪・服の細部・色が変わる。
そこで、キャラクターごとに「変えない言葉」（髪・目・体・いつもの服）、色見本、装飾と持ち物、手本の絵を残し、
描くときは毎回それを組み立て直して渡す。手本の絵は IP-Adapter で読ませ、言葉で決めきれない顔つきや配色を寄せる。
世界観も同じく、世界ごとに雰囲気の言葉と場所（背景）を残す。

置き場所: bible/characters/<id>.json と bible/characters/<id>/（手本の絵）、bible/worlds/<id>.json と bible/worlds/<id>/

  python3 tools/gen/bible.py new-character knight --name 灯りの騎士 --look "1girl, brown hair, ..." --outfit "silver plate armor, ..."
  python3 tools/gen/bible.py add-item knight lantern --name ランタン --tags "holding lantern" [--image path]
  python3 tools/gen/bible.py add-image knight color path/to/image.png      # 手本の絵（color / lineart / sheet など）
  python3 tools/gen/bible.py palette knight                                # 手本の色の絵から色見本を取る
  python3 tools/gen/bible.py new-world citadel --name 灯りの城塞 --tags "medieval fantasy, snowy mountains, ..."
  python3 tools/gen/bible.py add-location citadel gate --name 城門 --tags "castle gate, snow, night, torches"
  python3 tools/gen/bible.py prompt knight --scene "walking" --pose "looking back" --world citadel --location gate --items lantern
  python3 tools/gen/bible.py draw knight OUTDIR --scene ... [--outfit "差し替える服"] [--ref-scale 0.6] [--count 2]
  python3 tools/gen/bible.py show knight
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BIBLE = ROOT / "bible"


def _path(kind: str, ident: str) -> Path:
    return BIBLE / kind / f"{ident}.json"


def load(kind: str, ident: str) -> dict:
    p = _path(kind, ident)
    if not p.exists():
        raise SystemExit(f"{kind} の {ident} は保存されていない（{p}）")
    return json.loads(p.read_text(encoding="utf-8"))


def save(kind: str, data: dict) -> Path:
    p = _path(kind, data["id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return p


def new_character(ident: str, name: str, look: str, outfit: str, negative: str = "", notes: str = "") -> dict:
    data = {"id": ident, "name": name,
            "look": look,          # 変えない見た目（性別・髪・目・体つき）
            "outfit": outfit,      # いつもの服（描くときに差し替えられる）
            "negative": negative,  # このキャラクターで描かせたくないもの
            "items": [],           # 装飾・持ち物・道具
            "images": {},          # 手本の絵（color: 色の手本、lineart: 線画、sheet: 設定画）
            "palette": [],         # 色見本（手本の色の絵から取る）
            "notes": notes}
    save("characters", data)
    return data


def add_item(ident: str, item: str, name: str, tags: str, desc: str = "", image: str | None = None) -> dict:
    data = load("characters", ident)
    entry = {"id": item, "name": name, "tags": tags, "desc": desc}
    if image:
        entry["image"] = _copy(image, "characters", ident, f"item-{item}")
    data["items"] = [i for i in data["items"] if i["id"] != item] + [entry]
    save("characters", data)
    return entry


def _copy(src: str, kind: str, ident: str, stem: str) -> str:
    from PIL import Image
    d = BIBLE / kind / ident
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{stem}.jpg"
    im = Image.open(src).convert("RGB")
    im.thumbnail((832, 1216))
    im.save(out, quality=88)
    return str(out.relative_to(ROOT))


def add_image(ident: str, role: str, src: str) -> str:
    data = load("characters", ident)
    data["images"][role] = _copy(src, "characters", ident, role)
    save("characters", data)
    return data["images"][role]


def palette(ident: str, n: int = 8) -> list[str]:
    """色の手本の人物の中から、多い色を n 色取る（背景は除く）。描いた絵の色がずれたかを見比べるのに使う"""
    import numpy as np
    from PIL import Image
    sys.path.insert(0, str(Path(__file__).parent))
    import design
    data = load("characters", ident)
    src = ROOT / data["images"]["color"]
    im = Image.open(src).convert("RGB")
    alpha = np.asarray(design.cut_background(im).getchannel("A")) > 0
    px = np.asarray(im)[alpha]
    q = Image.fromarray(px.reshape(-1, 1, 3)).quantize(colors=n, method=Image.Quantize.MEDIANCUT)
    counts = sorted(q.getcolors(), reverse=True)
    pal = q.getpalette()
    data["palette"] = ["#%02x%02x%02x" % tuple(pal[i * 3:i * 3 + 3]) for _, i in counts]
    save("characters", data)
    return data["palette"]


def new_world(ident: str, name: str, tags: str, desc: str = "") -> dict:
    data = {"id": ident, "name": name, "tags": tags, "desc": desc, "locations": []}
    save("worlds", data)
    return data


def add_location(ident: str, loc: str, name: str, tags: str, desc: str = "", image: str | None = None) -> dict:
    data = load("worlds", ident)
    entry = {"id": loc, "name": name, "tags": tags, "desc": desc}
    if image:
        entry["image"] = _copy(image, "worlds", ident, f"loc-{loc}")
    data["locations"] = [x for x in data["locations"] if x["id"] != loc] + [entry]
    save("worlds", data)
    return entry


def prompt(ident: str, scene: str = "", pose: str = "", outfit: str | None = None, items: list[str] | None = None,
           world: str | None = None, location: str | None = None, framing: str = "full body") -> tuple[str, str]:
    """描く言葉を組み立てる。変えない見た目を先頭に置く（後ろほど 77 語の上限で切れやすく、効きも弱い）。
    服は差し替えがあればそれを、無ければいつもの服。持ち物は名前で選ぶ（省くと全部）。場所があれば背景を付ける"""
    c = load("characters", ident)
    chosen = [i for i in c["items"] if items is None or i["id"] in items]
    parts = [c["look"], outfit if outfit is not None else c["outfit"], *(i["tags"] for i in chosen), pose, scene, framing]
    if world:
        w = load("worlds", world)
        loc = next((x for x in w["locations"] if x["id"] == location), None) if location else None
        parts += [loc["tags"] if loc else "", w["tags"]]
    else:
        parts.append("simple background, white background")
    pos = ", ".join(p.strip() for p in parts if p and p.strip())
    return pos, c.get("negative", "")


def draw(ident: str, outdir: str, count: int = 1, seed: int = 0, ref_scale: float = 0.6, **kw) -> list[str]:
    """組み立てた言葉で描く。色の手本があれば IP-Adapter で読ませる（顔つき・配色を寄せる）。
    ref_scale を上げるほど手本に似るが、構図やポーズも手本に引っ張られる"""
    import torch
    from PIL import Image
    sys.path.insert(0, str(Path(__file__).parent))
    import design
    import free_text
    import people
    c = load("characters", ident)
    pos, neg = prompt(ident, **kw)
    pos, neg = free_text.full_prompt(pos, neg)
    pipe = people.pipe()
    ref = None
    if c["images"].get("color") and ref_scale > 0:
        people.use_reference()
        ref = Image.open(ROOT / c["images"]["color"]).convert("RGB")
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    pe, ne, pp, np_ = design.encode_xl(pipe, pos, neg)
    names = []
    for k in range(count):
        args = dict(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp, negative_pooled_prompt_embeds=np_,
                    width=832, height=1216, num_inference_steps=24, guidance_scale=6.0,
                    generator=torch.Generator().manual_seed(seed + k))
        if ref is not None:
            pipe.set_ip_adapter_scale(ref_scale)
            args["ip_adapter_image"] = ref
        im = pipe(**args).images[0]
        name = f"{ident}-{seed + k}.png"
        im.save(out / name)
        names.append(name)
    (out / f"{ident}-prompt.txt").write_text(pos + "\n\nnegative: " + neg + "\n", encoding="utf-8")
    return names


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("new-character"); s.add_argument("id"); s.add_argument("--name", required=True)
    s.add_argument("--look", required=True); s.add_argument("--outfit", default=""); s.add_argument("--negative", default="")
    s.add_argument("--notes", default="")
    s = sub.add_parser("add-item"); s.add_argument("id"); s.add_argument("item"); s.add_argument("--name", required=True)
    s.add_argument("--tags", required=True); s.add_argument("--desc", default=""); s.add_argument("--image")
    s = sub.add_parser("add-image"); s.add_argument("id"); s.add_argument("role"); s.add_argument("src")
    s = sub.add_parser("palette"); s.add_argument("id")
    s = sub.add_parser("new-world"); s.add_argument("id"); s.add_argument("--name", required=True)
    s.add_argument("--tags", required=True); s.add_argument("--desc", default="")
    s = sub.add_parser("add-location"); s.add_argument("id"); s.add_argument("loc"); s.add_argument("--name", required=True)
    s.add_argument("--tags", required=True); s.add_argument("--desc", default=""); s.add_argument("--image")
    for name in ("prompt", "draw"):
        s = sub.add_parser(name); s.add_argument("id")
        if name == "draw":
            s.add_argument("out"); s.add_argument("--count", type=int, default=1); s.add_argument("--seed", type=int, default=0)
            s.add_argument("--ref-scale", type=float, default=0.6)
        s.add_argument("--scene", default=""); s.add_argument("--pose", default=""); s.add_argument("--outfit")
        s.add_argument("--items", help="持ち物の id をカンマ区切りで。省くと全部"); s.add_argument("--world"); s.add_argument("--location")
        s.add_argument("--framing", default="full body")
    s = sub.add_parser("show"); s.add_argument("id")
    a = ap.parse_args()
    kw = {}
    if a.cmd in ("prompt", "draw"):
        kw = dict(scene=a.scene, pose=a.pose, outfit=a.outfit, world=a.world, location=a.location, framing=a.framing,
                  items=a.items.split(",") if a.items else None)
    r = {
        "new-character": lambda: new_character(a.id, a.name, a.look, a.outfit, a.negative, a.notes),
        "add-item": lambda: add_item(a.id, a.item, a.name, a.tags, a.desc, a.image),
        "add-image": lambda: add_image(a.id, a.role, a.src),
        "palette": lambda: palette(a.id),
        "new-world": lambda: new_world(a.id, a.name, a.tags, a.desc),
        "add-location": lambda: add_location(a.id, a.loc, a.name, a.tags, a.desc, a.image),
        "prompt": lambda: dict(zip(("prompt", "negative"), prompt(a.id, **kw))),
        "draw": lambda: draw(a.id, a.out, a.count, a.seed, a.ref_scale, **kw),
        "show": lambda: load("characters", a.id),
    }[a.cmd]()
    print(json.dumps(r, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
