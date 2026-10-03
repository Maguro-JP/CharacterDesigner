"""手本の全コマから特徴の分布を学び、自分のスプライトがどこで外れているかを点数にする。

1体の手本だけを見て直すと、その1体の癖まで写してしまい、別の手本とは食い違う。
手本のシートを全コマに切り分け、同じ数え方で特徴を数えて平均とばらつき（標準偏差）を取る。
自分のスプライトは特徴ごとに「手本の平均から標準偏差いくつ分ずれているか」（z）で測り、
|z| の大きい特徴から順に直す。数え方が手本と同じなので、どれか1体に寄らない。

手本の画像はリポジトリに置かない。学んだ数字だけを styles/<作風>.learned.json に書く。

使い方:
  学ぶ:   python3 tools/learn.py fit styles/diorama.learned.json <手本シート.png> [...]
  測る:   python3 tools/learn.py score styles/diorama.learned.json characters/*/sprite.json
"""
import colorsys
import json
import math
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import sprite  # noqa: E402

# 人物1体として数えるコマの大きさ。シートには効果や小物のコマも混ざるので外す
FRAME_W = (12, 40)
FRAME_H = (26, 50)


def split_sheet(path):
    """透明な行と列で区切って、シートを1コマずつに切る。"""
    im = Image.open(path).convert("RGBA")
    a = im.getchannel("A").load()
    W, H = im.size

    def runs(flags):
        out, s = [], None
        for i, f in enumerate(list(flags) + [False]):
            if f and s is None:
                s = i
            if not f and s is not None:
                out.append((s, i))
                s = None
        return out

    frames = []
    for y0, y1 in runs(any(a[x, y] for x in range(W)) for y in range(H)):
        for x0, x1 in runs(any(a[x, y] for y in range(y0, y1)) for x in range(W)):
            box = im.crop((x0, y0, x1, y1))
            bb = box.getchannel("A").getbbox()
            if not bb:
                continue
            box = box.crop(bb)
            if FRAME_W[0] <= box.width <= FRAME_W[1] and FRAME_H[0] <= box.height <= FRAME_H[1]:
                frames.append(box)
    return frames


def _lum(c):
    return (c[0] + c[1] + c[2]) / 3


def features(im):
    """1コマの特徴。手本にも自分のスプライトにも同じ数え方を使う。"""
    im = im.convert("RGBA")
    bb = im.getchannel("A").getbbox()
    im = im.crop(bb)
    W, H = im.size
    px = im.load()
    on = lambda x, y: 0 <= x < W and 0 <= y < H and px[x, y][3] > 0  # noqa: E731
    cells = [(x, y) for y in range(H) for x in range(W) if on(x, y)]
    n = len(cells)
    cols = [px[x, y][:3] for x, y in cells]
    lums = [_lum(c) for c in cols]
    sats = [colorsys.rgb_to_hsv(*(v / 255 for v in c))[1] for c in cols]

    def rate(dx, dy, where=None):
        t = c = 0
        for x, y in cells:
            if on(x + dx, y + dy) and (where is None or where(x, y)):
                t += 1
                c += px[x, y][:3] != px[x + dx, y + dy][:3]
        return c / t if t else 0.0

    edge = lambda x, y: any(not on(x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))  # noqa: E731
    edges = [(x, y) for x, y in cells if edge(x, y)]
    orphans = sum(1 for x, y in cells
                  if not any(on(x + dx, y + dy) and px[x + dx, y + dy][:3] == px[x, y][:3]
                             for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy))
    f = {
        "colors": len(set(cols)),
        "change_h": rate(1, 0),
        "change_v": rate(0, 1),
        "change_v_edge": rate(0, 1, edge),
        "change_v_inner": rate(0, 1, lambda x, y: not edge(x, y)),
        "orphans": orphans / n,
        "edge_lum": sum(_lum(px[x, y]) for x, y in edges) / len(edges),
        "lum_mean": sum(lums) / n,
        "dark": sum(1 for v in lums if v < 60) / n,
        "mid": sum(1 for v in lums if 60 <= v < 140) / n,
        "light": sum(1 for v in lums if 140 <= v < 200) / n,
        "bright": sum(1 for v in lums if v >= 200) / n,
        "sat_mean": sum(sats) / n,
        "fill": n / (W * H),
        "aspect": H / W,
    }
    return f


def fit(out_path, sheets):
    rows = []
    for s in sheets:
        for fr in split_sheet(s):
            rows.append(features(fr))
    keys = list(rows[0])
    stats = {}
    for k in keys:
        vs = sorted(r[k] for r in rows)
        m = sum(vs) / len(vs)
        sd = math.sqrt(sum((v - m) ** 2 for v in vs) / len(vs))
        stats[k] = {"mean": round(m, 4), "sd": round(sd, 4), "p10": round(vs[len(vs) // 10], 4),
                    "p90": round(vs[len(vs) * 9 // 10], 4)}
    data = {"frames": len(rows), "sheets": len(sheets), "features": stats}
    Path(out_path).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(sheets)} 枚のシートから {len(rows)} コマを学んだ → {out_path}")


def score_sprite(stats, path):
    _, rows, width, palette = sprite.load(path)
    f = features(sprite.to_image(rows, width, palette))
    z = {}
    for k, s in stats["features"].items():
        z[k] = (f[k] - s["mean"]) / (s["sd"] or 1e-6)
    return f, z


def score(stats_path, paths):
    stats = json.loads(Path(stats_path).read_text(encoding="utf-8"))
    total = {}
    for p in paths:
        f, z = score_sprite(stats, p)
        worst = sorted(z.items(), key=lambda kv: -abs(kv[1]))[:3]
        dist = math.sqrt(sum(v * v for v in z.values()) / len(z))
        print(f"{p}: 外れ {dist:.2f}  " + "  ".join(
            f"{k} {f[k]:.3f}（手本 {stats['features'][k]['mean']:.3f}, z {v:+.1f}）" for k, v in worst))
        for k, v in z.items():
            total.setdefault(k, []).append(v)
    print("\n全体で外れの大きい特徴（z の平均）:")
    for k, vs in sorted(total.items(), key=lambda kv: -abs(sum(kv[1]) / len(kv[1]))):
        print(f"  {k:15s} z {sum(vs) / len(vs):+.2f}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "fit":
        fit(sys.argv[2], sys.argv[3:])
    elif cmd == "score":
        score(sys.argv[2], sys.argv[3:])
    else:
        sys.exit(__doc__)
