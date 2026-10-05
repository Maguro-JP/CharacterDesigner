"""亜人の設定資料（正面・斜め前・斜め後ろ・背面を1枚）を、3D の素体を下絵にして描く。

言葉の指示だけで描くと、尾の付け根が腰の横や水着の布の上になり、向きによって尾が消えた（docs/knowledge/demihuman-anatomy.md）。
画像を作る AI は「尾がある」ことは描けても「どこから生えるか」を決めない。そこで付け根の位置を 3D の骨で決める。

流れ:
  1. 下絵: 3D の素体（tools/engine/viewer/vrm-base.html）に部品（猫: 獣耳と尾、悪魔: 角と翼と尾）を付け、4方向から撮る。
     同じ向きで、部品の位置の型（尾は赤、翼は桃、頭の部品は黄、肌は緑）も撮る
  2. 描く: 下絵から Animagine XL 3.1 で描き直す（img2img）。構図と部品の位置は下絵から、画風と顔は指示から来る
  3. 検品: 型の位置に部品が残っているかを、向きと部品ごとに数える。背景か肌の色に置き換わっていたら「消えた」とみなす。
     数えて通ったものを、docs/knowledge/demihuman-anatomy.md の項目で目で見る（人の耳が残っていないか、など）

使い方:
  python3 tools/gen/demi.py setup                       # 3D の素体と表示の部品を .cache/engine/vrm に取る（初回だけ）
  PYTHONPATH=.cache/gen/lib python3 tools/gen/demi.py run succubus <出力フォルダ> [--strength 0.6] [--tries 3]
  python3 tools/gen/demi.py underlay succubus <出力フォルダ>   # 下絵と型だけ撮る（数秒〜1分）
描く亜人は casts/demi3d.json に書く。
"""
import argparse
import base64
import functools
import http.server
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
CACHE = ROOT / ".cache" / "engine" / "vrm"
PAGE = ROOT / "tools" / "engine" / "viewer" / "vrm-base.html"
SHOOT = ROOT / "tools" / "engine" / "vrm_shoot.mjs"
CASES = ROOT / "casts" / "demi3d.json"
# 素体: VRoid Studio の公式サンプル（CC0）。入手元の一覧は docs/references.md
VRM_URL = "https://raw.githubusercontent.com/madjin/vrm-samples/master/vroid/beta/HairSample_Female.vrm"
LIBS = {
    "three.min.js": "https://cdn.jsdelivr.net/npm/three@0.147.0/build/three.min.js",
    "GLTFLoader.js": "https://cdn.jsdelivr.net/npm/three@0.147.0/examples/js/loaders/GLTFLoader.js",
    "OrbitControls.js": "https://cdn.jsdelivr.net/npm/three@0.147.0/examples/js/controls/OrbitControls.js",
    "three-vrm.min.js": "https://cdn.jsdelivr.net/npm/@pixiv/three-vrm@1.0.6/lib/three-vrm.min.js",
}
# 向き（カメラの横の角度、度）。並べる順に左から
VIEWS = [("front", 0), ("front34", 35), ("back34", 145), ("back", 180)]
SIZE = (1216, 832)
FIG_H = 790          # 人物の高さの上限（px）。翼が横に広い種は、全向きを同じ倍率で縮める
FOOT_Y = 818         # 足元の高さ
PART_COLORS = {"tail": (255, 0, 0), "wing": (255, 0, 255), "head": (255, 255, 0)}
# 数える最小の大きさ（型の点の数）。これより小さい向きは数えない
MIN_PX = {"tail": 300, "wing": 300, "head": 100}
PART_JA = {"extra": "下絵に無い部品（余分な尾など）", "tail": "尾", "wing": "翼", "head": "頭の部品（角・獣耳）"}
VIEW_JA = {"front": "正面", "front34": "斜め前", "back34": "斜め後ろ", "back": "背面"}
FONT = "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"


# ---- 1. 3D の素体を用意して撮る ----

def setup():
    """素体を取り、画像を 1024px に縮めて base64 の文字にする。表示の部品も手元に置く（画面なしのブラウザは外に出られないため）。"""
    CACHE.mkdir(parents=True, exist_ok=True)
    vrm = CACHE / "base.vrm"
    if not vrm.exists():
        subprocess.run(["curl", "-sSfL", "-o", str(CACHE / "orig.vrm"), VRM_URL], check=True)
        subprocess.run([sys.executable, str(ROOT / "tools" / "engine" / "vrm_repack.py"), str(CACHE / "orig.vrm"), str(vrm), "1024"], check=True)
    txt = CACHE / "base-vrm.txt"
    if not txt.exists():
        txt.write_text(base64.b64encode(vrm.read_bytes()).decode())
    for name, url in LIBS.items():
        if not (CACHE / name).exists():
            subprocess.run(["curl", "-sSfL", "-o", str(CACHE / name), url], check=True)
    write_page()
    print("用意できた:", CACHE)


def write_page():
    """表示のページを、手元の部品を読む形に書き換えて置く。舞台の背景は透明にする（下絵の背景を後から白で塗るため）。"""
    s = PAGE.read_text()
    for name, url in LIBS.items():
        s = s.replace(url, name)
    s = '<meta charset="utf-8">\n' + s.replace("</style>", "html, body, .stage { background: transparent !important; border: 0 !important }\n.load { display: none }\n</style>", 1)
    (CACHE / "index.html").write_text(s)


def serve():
    """CACHE を手元だけで配る。戻り値は URL と止める関数。"""
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(CACHE))
    h.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}/index.html", srv.shutdown


def node_env():
    env = dict(os.environ)
    # この環境に入っている Playwright と Chromium を既定にする。別の環境では PLAYWRIGHT_MODULE と CHROMIUM_PATH で指す
    for key, path in [("PLAYWRIGHT_MODULE", "/opt/node22/lib/node_modules/playwright/index.mjs"),
                      ("CHROMIUM_PATH", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")]:
        if key not in env and Path(path).exists():
            env[key] = path
    return env


def underlay(case, outdir):
    """下絵（underlay.png）と部品の型（mask.png）を作る。"""
    if not (CACHE / "base-vrm.txt").exists():
        sys.exit("先に python3 tools/gen/demi.py setup を実行する")
    write_page()
    outdir.mkdir(parents=True, exist_ok=True)
    url, stop = serve()
    t = time.time()
    try:
        arg = {"url": url, "out": str(outdir / "shot"), "kind": case.get("kind", "none"), "parts": case.get("parts"),
               "hair": case.get("hair_3d", "keep"), "hairColor": case.get("hair_color"), "body": "ideal", "pose": case.get("pose", "stand"), "views": [a for _, a in VIEWS]}
        subprocess.run(["node", str(SHOOT), json.dumps(arg)], check=True, env=node_env(), timeout=900)
    finally:
        stop()
    compose(outdir)
    print(f"下絵: {time.time() - t:.0f} 秒", flush=True)


def compose(outdir):
    """向きごとの絵を1枚に並べる。全向きを同じ倍率にし（大きさが揃わないと描き直しで別人に見える）、足元をそろえる。"""
    shots = []
    for i in range(len(VIEWS)):
        c = Image.open(outdir / f"shot-color-{i}.png").convert("RGBA")
        m = Image.open(outdir / f"shot-mask-{i}.png").convert("RGBA")
        box = c.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
        shots.append((c.crop(box), m.crop(box)))
    slot = SIZE[0] // len(shots)
    k = min(min(FIG_H / c.height, (slot - 6) / c.width) for c, _ in shots)
    under = Image.new("RGB", SIZE, "white")
    mask = Image.new("RGB", SIZE, "black")
    for i, (c, m) in enumerate(shots):
        w, h = round(c.width * k), round(c.height * k)
        x, y = i * slot + (slot - w) // 2, FOOT_Y - h
        c = c.resize((w, h), Image.LANCZOS)
        under.paste(c, (x, y), c)
        m = m.resize((w, h), Image.NEAREST)
        mask.paste(m.convert("RGB"), (x, y), m.getchannel("A").point(lambda v: 255 if v > 128 else 0))
    under.save(outdir / "underlay.png")
    mask.save(outdir / "mask.png")


# ---- 2. 描く ----

_I2I = None


def img2img():
    global _I2I
    if _I2I is None:
        import people
        from diffusers import StableDiffusionXLImg2ImgPipeline
        # 文字から描く部品（people.pipe）と同じ重みをそのまま渡して組む。from_pipe は読み込み直後（約 7GB）に
        # メモリ不足で強制終了された（15GB の環境、終了コード 137）。下絵の変換（VAE）はタイルに分けて山を低くする
        base = people.pipe()
        _I2I = StableDiffusionXLImg2ImgPipeline(**{k: v for k, v in base.components.items()
                                                   if k in StableDiffusionXLImg2ImgPipeline._optional_components + [
                                                       "vae", "text_encoder", "text_encoder_2", "tokenizer", "tokenizer_2", "unet", "scheduler"]})
        _I2I.vae.enable_tiling()
    return _I2I


def prompt_of(case):
    import people
    rules = json.loads((ROOT / "casts" / "demihuman-cards.json").read_text())["anatomy"]
    tags = [rules[a]["tags"] for a in case.get("anatomy", []) if a in rules]
    neg = [rules[a]["negative"] for a in case.get("anatomy", []) if a in rules]
    prompt = ", ".join(["1girl", "solo", "adult woman", case["tags"], *tags, case["hair"], "white bikini, barefoot",
                        people.SHEET, "white background, simple background", people.QUALITY])
    negative = ", ".join([people.NEGATIVE.replace("multiple views, ", ""), "different characters, mismatched outfits",
                          *neg, case.get("negative", "")])
    return prompt, negative


def draw(case, outdir, strength, tries, steps=30):
    """下絵から描き直す。部品の数え上げで落ちたら seed を変える（最大 tries 回）。通った絵を sheet.png に置く。"""
    import torch
    import design
    prompt, negative = prompt_of(case)
    under = Image.open(outdir / "underlay.png").convert("RGB")
    report = []
    for k in range(tries):
        seed = case.get("seed", 1) + k * 100
        t = time.time()
        pipe = img2img()
        pe, ne, pp, np_ = design.encode_xl(pipe, prompt, negative)
        im = pipe(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp, negative_pooled_prompt_embeds=np_,
                  image=under, strength=strength, num_inference_steps=steps, guidance_scale=6.0,
                  generator=torch.Generator().manual_seed(seed)).images[0]
        out = outdir / f"try-{k}.png"
        im.save(out)
        result = check(out, outdir / "mask.png")
        lost = [r for r in result if not r["ok"]]
        print(f"{out}: {time.time() - t:.0f} 秒 seed {seed} " + ("通った" if not lost else "落とした: " +
              "、".join(f"{VIEW_JA[r['view']]}の{PART_JA[r['part']]}" for r in lost)), flush=True)
        report.append({"try": k, "seed": seed, "strength": strength, "result": result})
        inspect_sheet(out, outdir / "mask.png", result, outdir / f"try-{k}-inspect.png")
        if not lost:
            im.save(outdir / "sheet.png")
            break
    (outdir / "report.json").write_text(json.dumps({"prompt": prompt, "negative": negative, "tries": report}, ensure_ascii=False, indent=1))
    return report


# ---- 3. 検品（部品が型の位置に残っているか） ----

def _region(mask, color, erode=5):
    """型の中の、ある色の範囲（縁を削った 0/255 の画像）。描き直しで線が少しずれても、内側だけを数える。"""
    import numpy as np
    a = np.asarray(mask).astype(int)
    on = (np.abs(a - np.array(color)).sum(axis=2) < 60).astype("uint8") * 255
    im = Image.fromarray(on)
    return im.filter(ImageFilter.MinFilter(erode)) if erode else im


def check(sheet, mask_path):
    """向きと部品ごとに、型の位置に部品が残っているかを数える。

    色のある部品: 下絵の部品の色に近い点と、背景でも肌でもない点を「残っている」と数え、半分に満たなければ「消えた」。
      狐の耳は髪と同じ橙で肌の色にも近く、「肌に置き換わった」と誤って落とした。下絵の色と比べることで避ける
    白い部品（兎の耳、天使の羽）: 白は背景と見分けられないので、輪郭や陰（背景でも肌でもない点）が 12% 以上あれば「残っている」
    肌の色は、型の肌（緑）の位置の色の中央値。水着の白は背景と見分けられないので、肌の見本から外す。
    """
    import numpy as np
    img = np.asarray(Image.open(sheet).convert("RGB")).astype(int)
    mask = Image.open(mask_path).convert("RGB")
    lum_min = img.min(axis=2)
    bg = (lum_min > 225) & ((img.max(axis=2) - lum_min) < 20)
    skin_area = (np.asarray(_region(mask, (0, 255, 0))) > 0) & ~bg
    skin = np.median(img[skin_area], axis=0) if skin_area.any() else np.array([240, 205, 185])
    is_skin = np.abs(img - skin).sum(axis=2) < 60
    under_path = Path(mask_path).with_name("underlay.png")
    under = np.asarray(Image.open(under_path).convert("RGB")).astype(int) if under_path.exists() else img
    slot = SIZE[0] // len(VIEWS)
    out = []
    for part, color in PART_COLORS.items():
        # 尾と角は細いので縁を削らない（削ると数える点がほとんど残らなかった）。翼は広いので内側だけ数える
        region = np.asarray(_region(mask, color, erode=5 if part == "wing" else 0)) > 0
        for i, (view, _) in enumerate(VIEWS):
            r = np.zeros_like(region)
            r[:, i * slot:(i + 1) * slot] = region[:, i * slot:(i + 1) * slot]
            n = int(r.sum())
            if n < MIN_PX[part]:
                continue   # この向きでは隠れているか、先が少し見えるだけ（正面の尾。決まりでは見えなくてよい）
            ref = np.median(under[r], axis=0)
            other = ~bg[r] & ~is_skin[r]
            if ref.min() > 200:   # 白い部品
                kept = float(other.mean())
                ok = kept >= 0.12
            else:
                kept = float((other | (np.abs(img[r] - ref).sum(axis=1) < 90)).mean())
                ok = kept >= 0.5
            out.append({"view": view, "part": part, "pixels": n, "gone": round(1 - kept, 3), "ok": ok})
    out += extra_parts(img, mask, bg, Path(mask_path).with_name("underlay.png"))
    return out


def extra_parts(img, mask, bg, underlay_path, grow=12, min_px=250):
    """下絵に無い所に出た暗い部品（尾が2本、手の上に出た尾の先）を数える。

    下絵で明るかった所（肌・水着・背景）に、描いた絵で暗い点（明るさ 90 未満）が固まって出たら「余分」とみなす。
    髪・角・尾・翼は下絵でも暗いので、下絵の暗い所を少し広げた範囲は数えない。
    最初は「人物の外」で数えたが、手の上に重なって出た尾の先を見逃した。
    """
    import numpy as np
    if not underlay_path.exists():
        return []
    under = np.asarray(Image.open(underlay_path).convert("L"))
    dark_under = Image.fromarray((under < 120).astype("uint8") * 255).filter(ImageFilter.MaxFilter(grow * 2 + 1))
    dark = img.mean(axis=2) < 90
    near = dark & ~(np.asarray(dark_under) > 0)
    slot = SIZE[0] // len(VIEWS)
    out = []
    for i, (view, _) in enumerate(VIEWS):
        n = int(near[:, i * slot:(i + 1) * slot].sum())
        if n >= min_px:
            out.append({"view": view, "part": "extra", "pixels": n, "gone": 0.0, "ok": False})
    return out


def inspect_sheet(sheet, mask_path, result, out):
    """目で見るための図: 描いた絵に、型の部品の輪郭（向きごとに通ったら緑、消えたら赤）と判定を重ねる。"""
    import numpy as np
    im = Image.open(sheet).convert("RGB")
    mask = Image.open(mask_path).convert("RGB")
    d = ImageDraw.Draw(im)
    slot = SIZE[0] // len(VIEWS)
    for part, color in PART_COLORS.items():
        region = _region(mask, color, erode=0)
        grown = np.asarray(region.filter(ImageFilter.MaxFilter(5))) > 0
        edge = Image.fromarray((grown & ~(np.asarray(region) > 0)).astype("uint8") * 255)   # 範囲の外側の細い輪郭
        for r in [r for r in result if r["part"] == part]:
            i = [v for v, _ in VIEWS].index(r["view"])
            sub = Image.new("L", im.size, 0)
            sub.paste(edge.crop((i * slot, 0, (i + 1) * slot, SIZE[1])), (i * slot, 0))
            im.paste((40, 180, 60) if r["ok"] else (220, 30, 30), (0, 0), sub)
    font = ImageFont.truetype(FONT, 18) if Path(FONT).exists() else None
    for i, (view, _) in enumerate(VIEWS):
        rs = [r for r in result if r["view"] == view]
        text = VIEW_JA[view] + " " + " ".join(PART_JA[r["part"]][0] + ("○" if r["ok"] else "×") for r in rs)
        d.text((i * slot + 8, 6), text, fill=(30, 30, 30), font=font)
    im.save(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["setup", "underlay", "run", "check"])
    ap.add_argument("case", nargs="?")
    ap.add_argument("outdir", nargs="?", type=Path)
    ap.add_argument("--strength", type=float, default=None, help="下絵から離れる強さ（既定は亜人ごとの strength、無ければ 0.6）。大きいほど画風が強く、部品の位置がずれやすい")
    ap.add_argument("--tries", type=int, default=3)
    a = ap.parse_args()
    if a.cmd == "setup":
        return setup()
    cases = json.loads(CASES.read_text())["cases"]
    if a.case not in cases or not a.outdir:
        sys.exit(f"亜人の名前（{', '.join(cases)}）と出力フォルダを渡す")
    case = cases[a.case]
    if a.cmd in ("underlay", "run"):
        underlay(case, a.outdir)
    if a.cmd == "run":
        draw(case, a.outdir, a.strength if a.strength is not None else case.get("strength", 0.6), a.tries)
    if a.cmd == "check":
        sheet = a.outdir / "sheet.png"
        r = check(sheet, a.outdir / "mask.png")
        inspect_sheet(sheet, a.outdir / "mask.png", r, a.outdir / "inspect.png")
        print(json.dumps(r, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
