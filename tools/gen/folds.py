"""服のしわを置く場所と向きを、体の形から決める（線はまだ引かない。場所の印だけ）。

人の描き手はしわを乱数で散らさない。布が体の出っ張りに引っかかり、余った布が引かれ・寄る所にだけ置く
（docs/knowledge/folds-and-lines.md、CLIP STUDIO 講座 151672・149934・159937）。ここで扱う場所と出典の決まり:

- elbow / knee: 曲げた関節の内側に布が寄る。内側から関節の出っ張りへ向かって走る（151672 の肘）。
  強さは曲げの角度で決める（力点に近いほど強い、149934）。まっすぐな腕・脚には置かない（脚はつっぱってしわになりにくい、151672）
- belt: 腰を締める服は、締めた所の下に寄りじわが出る（151672 の「三角形の寄りじわ」）。向きは下へ
- armpit: 肩の出っ張りの上には無く、脇から肩筋の終わりへ細かいしわ（151672）
関節が取れない絵（確からしさ 0.3 未満）と、その場所が服でない所には置かない。

  python3 tools/gen/folds.py IMAGE OUT.png
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

LEAST = 0.3
CLOTH = (4, 5, 6, 7)   # 部位分けの上着・スカート・ズボン・ワンピース
BELT = 8


def metal_mask(img: np.ndarray, cloth: np.ndarray) -> np.ndarray:
    """服の部位の中の金属（鎧）。部位分けは鎧も服に数えるので、鎧の板にしわを置かないために使う。
    金属は彩度が低く、つやで明るさが細かく散らばる。散らばりは板の縁の線でも出るので、開きで細い線を除き、
    閉じと穴埋めで平らな板の内側を埋める。騎士の絵で、胸・腕・腰の鎧が金属、スカート・マフラー・タイツが布に分かれた。照り返しの条件で黒いローブを外した"""
    from scipy.ndimage import binary_closing, binary_fill_holes, binary_opening, uniform_filter
    rgb = img[..., :3].astype(float)
    mx, mn = rgb.max(2), rgb.min(2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1) * 255, 0)
    lum = rgb @ np.array([0.299, 0.587, 0.114])
    spread = np.sqrt(np.maximum(uniform_filter(lum * lum, 15) - uniform_filter(lum, 15) ** 2, 0))
    # 黒い布もしわの陰影で明るさが散らばり、鎧と取った（ローブの魔女で服の 31%）。金属は強い照り返しがあるので、
    # 近く（31 画素四方）に明るさ 170 を超える所があることも条件にする
    from scipy.ndimage import maximum_filter
    shine = maximum_filter(lum, 31) > 170
    m = cloth & (uniform_filter(sat, 11) < 50) & (uniform_filter(spread, 15) > 12) & shine
    m = binary_opening(m, np.ones((9, 9)))
    return binary_fill_holes(binary_closing(m, np.ones((25, 25)))) & cloth


def bend(a, b, c) -> float:
    """b で曲がる角度（度）。まっすぐなら 0、折り畳むと 180 に近づく"""
    u, v = np.subtract(a, b), np.subtract(c, b)
    cos = np.dot(u, v) / max(np.linalg.norm(u) * np.linalg.norm(v), 1e-6)
    return float(180 - np.degrees(np.arccos(np.clip(cos, -1, 1))))


def inner(a, b, c) -> np.ndarray:
    """b で曲がった関節の内側（へこむ側）への単位ベクトル。2 本の骨の向きの和の向き"""
    u, v = np.subtract(a, b), np.subtract(c, b)
    s = u / max(np.linalg.norm(u), 1e-6) + v / max(np.linalg.norm(v), 1e-6)
    n = np.linalg.norm(s)
    return s / n if n > 1e-6 else np.zeros(2)


def sites(points: list[dict], lab: np.ndarray, img: np.ndarray | None = None, least_bend: float = 25.0) -> list[dict]:
    """しわの候補の場所。各要素は kind・x・y（場所）・dx・dy（しわの走る向き）・strength（0〜1）・rule（出典の決まり）"""
    P = {p["name"]: p for p in points}
    ok = lambda *ns: all(P[n]["score"] >= LEAST for n in ns)
    xy = lambda n: np.array([P[n]["x"], P[n]["y"]])
    H, W = lab.shape
    cloth = np.isin(lab, CLOTH)
    if img is not None:
        cloth &= ~metal_mask(img, cloth)     # 鎧の板は布でない
    arms = np.isin(lab, (14, 15))
    on_cloth = lambda q: 0 <= int(q[1]) < H and 0 <= int(q[0]) < W and cloth[int(q[1]), int(q[0])]
    out = []
    for side in ("left", "right"):
        for kind, (a, b, c) in (("elbow", (f"{side}_shoulder", f"{side}_elbow", f"{side}_wrist")),
                                ("knee", (f"{side}_hip", f"{side}_knee", f"{side}_ankle"))):
            if not ok(a, b, c):
                continue
            ang = bend(xy(a), xy(b), xy(c))
            if ang < least_bend:
                continue
            n = inner(xy(a), xy(b), xy(c))
            bone = min(np.linalg.norm(xy(a) - xy(b)), np.linalg.norm(xy(c) - xy(b)))
            at = xy(b) + n * bone * 0.12          # 関節の内側、骨の長さの 12% だけ寄せた所
            if not on_cloth(at):
                continue
            out.append({"kind": kind, "side": side, "x": float(at[0]), "y": float(at[1]), "dx": float(-n[0]), "dy": float(-n[1]),
                        "strength": round(min(ang / 90, 1.0), 2), "bend": round(ang, 1),
                        "rule": "曲げた内側に布が寄り、内側から出っ張りへ走る（151672）"})
        if ok(f"{side}_shoulder", f"{side}_hip", f"{side}_elbow"):
            sh, hp = xy(f"{side}_shoulder"), xy(f"{side}_hip")
            # 脇: 肩の真下、胴の長さの 18% 下。腰へ向けて下ろすと、腰が肩より内側にある分だけ胸の内側に寄った
            pit = sh + np.array([0.0, (hp[1] - sh[1]) * 0.18])
            d = sh - pit
            d = d / max(np.linalg.norm(d), 1e-6)
            # 前に出した腕や手で隠れた脇には置かない（見えない所のしわは描かない）
            hidden = arms[max(int(pit[1]) - 8, 0):int(pit[1]) + 8, max(int(pit[0]) - 8, 0):int(pit[0]) + 8].any()
            if on_cloth(pit) and not hidden:
                out.append({"kind": "armpit", "side": side, "x": float(pit[0]), "y": float(pit[1]), "dx": float(d[0]), "dy": float(d[1]),
                            "strength": 0.3, "rule": "肩の出っ張りの上は無し。脇から肩筋の終わりへ細かいしわ（151672）"})
    belt = lab == BELT
    # ベルトは肩と腰の間にあるものだけ（首元のマフラーの結び目をベルトと取った）
    if ok("left_shoulder", "right_shoulder", "left_hip", "right_hip"):
        top = min(P["left_shoulder"]["y"], P["right_shoulder"]["y"])
        hip = max(P["left_hip"]["y"], P["right_hip"]["y"])
        rows = np.arange(H)[:, None]
        # 胴の下 6 割から腰の少し下まで（腰の点は脚の付け根なので、ベルトはそれより上にも下にも来る）
        belt &= (rows > top + 0.4 * (hip - top)) & (rows < hip + 0.15 * (hip - top))
    else:
        belt[:] = False
    if belt.sum() > 50:
        ys, xs = np.nonzero(belt)
        below = (float(xs.mean()), float(ys.max() + 4))
        if on_cloth(below):
            out.append({"kind": "belt", "side": "", "x": below[0], "y": below[1], "dx": 0.0, "dy": 1.0, "strength": 0.6,
                        "rule": "腰を締めた所の下に寄りじわ（151672）"})
    return out


def draw(src: str, found: list[dict], out: str):
    im = Image.open(src).convert("RGB")
    d = ImageDraw.Draw(im)
    color = {"elbow": (255, 60, 60), "knee": (255, 160, 0), "armpit": (60, 160, 255), "belt": (60, 220, 90)}
    for s in found:
        L = 18 + 40 * s["strength"]
        x, y = s["x"], s["y"]
        d.ellipse([x - 6, y - 6, x + 6, y + 6], outline=color[s["kind"]], width=3)
        d.line([(x, y), (x + s["dx"] * L, y + s["dy"] * L)], fill=color[s["kind"]], width=3)
    im.save(out)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    sys.path.insert(0, str(Path(__file__).parent))
    import edit
    import joints
    src = sys.argv[1]
    lab = np.asarray(edit.parts(src).resize(Image.open(src).size, Image.NEAREST))
    found = sites(joints.find(src), lab, np.asarray(Image.open(src).convert("RGB")))
    draw(src, found, sys.argv[2])
    print(json.dumps(found, ensure_ascii=False))
