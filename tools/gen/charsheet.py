"""キャラクターデザインの資料（設定画）に載せるものの決まりと、1 冊の資料への書き出し。

資料は 8 つの区分で作る。区分ごとに、設定資料集（bible/characters/<id>.json）の文字の欄と、絵の役割（images のキー）を決める。
全部そろうまで、キャラデザモードは終わらない（bible.design_status がここを見る）。

  1. 基本情報     名前・年齢・身長と頭身・役割・性格・背景設定
  2. 全身の四面図  正面・背面・左・右（左右は持ち物や髪の結び方が違うので、片方を裏返して作らない）
  3. ポーズ       立ち・歩き・役どころの動作・持ち物を使う、の 3 種以上
  4. 胸から上     表情差分 8 種以上、髪型差分 2 種以上
  5. 詳細         目の拡大、髪の拡大
  6. 服・装飾・武装 部位ごとの拡大（1 つ以上）と、持ち物ごとの拡大
  7. 色見本       色の名前・色の値・使う部位
  8. 補足         描くときの決まり、描いてはいけないもの

  python3 tools/gen/charsheet.py status <id>        足りないものを区分ごとに出す
  python3 tools/gen/charsheet.py render <id> <出力.html>   資料を書き出す（無い所は「未作成」）
"""
from __future__ import annotations

import base64
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bible  # noqa: E402

# 区分: (キー, 見出し, 文字の欄, 絵の役割の決まり)。絵の役割の決まりは (接頭辞, 最少の枚数, 説明)
SECTIONS = [
    ("profile", "基本情報", ["name", "age", "height", "role", "personality", "backstory"], []),
    ("views", "全身の四面図", [], [("view-front", 1, "正面"), ("view-back", 1, "背面"), ("view-left", 1, "左"), ("view-right", 1, "右")]),
    ("poses", "ポーズ", [], [("pose-", 3, "立ち・歩き・役どころの動作・持ち物を使う")]),
    ("bust", "胸から上（表情・髪型）", ["expressions"], [("expr-", 8, "表情差分"), ("hairstyle-", 2, "髪型差分")]),
    ("details", "目と髪の詳細", ["eyes"], [("detail-eyes", 1, "目の拡大"), ("detail-hair", 1, "髪の拡大")]),
    ("outfit", "服・装飾・武装", ["outfit_parts"], [("detail-outfit-", 1, "服の部位の拡大"), ("detail-item-", 0, "持ち物の拡大（持ち物の数だけ）")]),
    ("colors", "色見本", ["colors"], []),
    ("notes", "補足", ["rules", "negative"], []),
]
# 文字の欄の見出し
FIELD_JA = {"name": "名前", "age": "年齢", "height": "身長・頭身", "role": "役割", "personality": "性格", "backstory": "背景設定",
            "expressions": "表情の一覧", "eyes": "目の設計", "outfit_parts": "服の部位", "colors": "色", "rules": "描くときの決まり",
            "negative": "描いてはいけないもの"}


def _roles(c: dict, prefix: str) -> list[str]:
    return sorted(k for k in c.get("images", {}) if k == prefix or (prefix.endswith("-") and k.startswith(prefix)))


def status(ident: str) -> dict:
    """区分ごとに、そろっていない文字の欄と絵を返す。missing が全部空なら資料は完成"""
    c = bible.load("characters", ident)
    out = {}
    for key, title, fields, roles in SECTIONS:
        miss = [FIELD_JA.get(f, f) for f in fields if not c.get(f)]
        for prefix, least, what in roles:
            need = len(c.get("items", [])) if prefix == "detail-item-" else least
            have = len(_roles(c, prefix))
            if have < need:
                miss.append(f"{what}の絵（{prefix}…、{have}/{need}）")
        out[key] = {"title": title, "missing": miss}
    return {"id": ident, "ready": not any(v["missing"] for v in out.values()), "sections": out}


CSS = """
:root { --paper:#fbfaf7; --ink:#141313; --sub:#5d5853; --rule:#d9d4cd; --accent:#d23a26; --todo:#9a9087;
  --display:"Dela Gothic One","Hiragino Sans","Yu Gothic",sans-serif; --body:"Zen Kaku Gothic New","Hiragino Sans","Yu Gothic",sans-serif;
  --mono:"JetBrains Mono",ui-monospace,Menlo,monospace; color-scheme: light; }
html,body { background:var(--paper); color:var(--ink); margin:0; }
body { font-family:var(--body); font-size:14px; line-height:1.75; padding:32px 16px; }
.sheet { max-width:1200px; margin:0 auto; display:grid; gap:32px; }
header { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:end; gap:12px; border-bottom:3px solid var(--ink); padding-bottom:10px; }
h1 { font-family:var(--display); font-weight:400; font-size:clamp(28px,5vw,48px); margin:0; }
h2 { font-family:var(--display); font-weight:400; font-size:20px; margin:0 0 12px; display:flex; gap:10px; align-items:baseline; }
h2 small { font-family:var(--mono); font-size:12px; color:var(--accent); }
.id { font-family:var(--mono); color:var(--sub); }
section { border-top:1px solid var(--rule); padding-top:16px; }
dl { display:grid; grid-template-columns:max-content 1fr; gap:4px 16px; margin:0; }
dt { color:var(--sub); } dd { margin:0; }
.imgs { display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:14px; }
.imgs.wide { grid-template-columns:repeat(auto-fill,minmax(160px,1fr)); }
figure { margin:0; } figure img { width:100%; height:auto; display:block; background:#fff; border:1px solid var(--rule); }
figcaption { font-size:12px; color:var(--sub); margin-top:4px; }
.todo { color:var(--todo); border:1px dashed var(--rule); padding:10px 12px; font-size:13px; }
.sw { display:flex; gap:10px; align-items:center; } .sw i { width:44px; height:44px; border:1px solid var(--rule); display:block; flex:none; }
.sw code { font-family:var(--mono); font-size:12px; }
.swatches { display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:10px; }
code { font-family:var(--mono); font-size:12px; }
"""


def _img(rel: str) -> str:
    p = bible.ROOT / rel
    kind = "png" if p.suffix == ".png" else "jpeg"
    return f"data:image/{kind};base64," + base64.b64encode(p.read_bytes()).decode()


def render(ident: str, out: str) -> dict:
    """資料を 1 つの HTML に書き出す（絵は埋め込む）。文字は絵に焼き込まない（手元の日本語の書体が中国語用で、字形が崩れる）"""
    c = bible.load("characters", ident)
    st = status(ident)
    e = html.escape

    def val(v):
        if isinstance(v, list):
            return "<br>".join(e(json.dumps(x, ensure_ascii=False) if isinstance(x, dict) else str(x)) for x in v)
        if isinstance(v, dict):
            return "<br>".join(f"{e(str(k))}: {e(json.dumps(x, ensure_ascii=False) if isinstance(x, (dict, list)) else str(x))}" for k, x in v.items())
        return e(str(v))

    def figs(prefix, cls=""):
        roles = _roles(c, prefix)
        if not roles:
            return ""
        return f'<div class="imgs {cls}">' + "".join(
            f'<figure><img src="{_img(c["images"][r])}" alt="{e(c["name"])}の{e(r)}"><figcaption>{e(r)}</figcaption></figure>'
            for r in roles) + "</div>"

    parts = []
    for key, title, fields, roles in SECTIONS:
        miss = st["sections"][key]["missing"]
        body = ""
        if key == "colors" and c.get("colors"):
            cols = c["colors"]
            items = cols.items() if isinstance(cols, dict) else enumerate(cols)
            body += '<div class="swatches">' + "".join(
                f'<div class="sw"><i style="background:{e(str(v if isinstance(v, str) else v.get("hex", "")))}"></i>'
                f'<span>{e(str(k))}<br><code>{e(str(v if isinstance(v, str) else v.get("hex", "")))}</code></span></div>'
                for k, v in items) + "</div>"
        else:
            rows = [(FIELD_JA.get(f, f), c[f]) for f in fields if c.get(f)]
            if rows:
                body += "<dl>" + "".join(f"<dt>{e(k)}</dt><dd>{val(v)}</dd>" for k, v in rows) + "</dl>"
        for prefix, _, _ in roles:
            body += figs(prefix, "wide" if prefix in ("expr-", "hairstyle-") else "")
        if key == "outfit" and c.get("items"):
            body += "<dl>" + "".join(f'<dt>{e(i["name"])}</dt><dd>{e(i.get("desc", ""))}'
                                     + (f'<br>持ち方: {e(i["hold"])}' if i.get("hold") else "")
                                     + (f'<br>大きさ: {e(i["size"])}' if i.get("size") else "") + "</dd>" for i in c["items"]) + "</dl>"
        if miss:
            body += '<div class="todo">未作成: ' + "、".join(e(m) for m in miss) + "</div>"
        done = "完成" if not miss else f"未作成 {len(miss)}"
        parts.append(f'<section><h2>{e(title)}<small>{done}</small></h2>{body}</section>')
    page = (f'<title>{e(c["name"])} 設定資料</title>'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Dela+Gothic+One&family=Zen+Kaku+Gothic+New:wght@400;700&family=JetBrains+Mono&display=swap">'
            f'<style>{CSS}</style><div class="sheet"><header><h1>{e(c["name"])}</h1><span class="id">{e(c["id"])}</span></header>'
            + "".join(parts) + "</div>")
    Path(out).write_text(page, encoding="utf-8")
    return {"out": out, "ready": st["ready"], "missing": sum(len(v["missing"]) for v in st["sections"].values()),
            "bytes": len(page.encode())}


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "status":
        r = status(sys.argv[2])
    elif len(sys.argv) >= 4 and sys.argv[1] == "render":
        r = render(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
    print(json.dumps(r, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
