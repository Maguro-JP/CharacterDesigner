"""見せる頁（画集・紹介サイト）を、絵を埋め込んだ1つの HTML にする。

templates/showcase/*.html の中の {{img:名前}} を library/book/名前.jpg の data URI に、{{link:名前}} を引数で渡した URL に置き換える。
絵を別のファイルで出さないのは、頁を1つのファイルのまま渡せるようにするため。

  python3 tools/showcase.py book OUT.html
  python3 tools/showcase.py site OUT.html --link book=https://...
"""
import argparse
import base64
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(name: str, out: str, links: dict[str, str]) -> dict:
    html = (ROOT / "templates" / "showcase" / f"{name}.html").read_text(encoding="utf-8")
    used = []

    def img(m):
        p = ROOT / "library" / "book" / f"{m.group(1)}.jpg"
        used.append(p.name)
        return "data:image/jpeg;base64," + base64.b64encode(p.read_bytes()).decode()

    html = re.sub(r"\{\{img:([a-z0-9-]+)\}\}", img, html)
    missing = sorted(set(re.findall(r"\{\{link:([a-z0-9-]+)\}\}", html)) - set(links))
    if missing:
        raise SystemExit(f"リンクが渡されていない: {', '.join(missing)}")
    html = re.sub(r"\{\{link:([a-z0-9-]+)\}\}", lambda m: links[m.group(1)], html)
    Path(out).write_text(html, encoding="utf-8")
    return {"out": out, "images": len(used), "bytes": len(html.encode())}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", choices=["book", "site"])
    ap.add_argument("out")
    ap.add_argument("--link", action="append", default=[], help="名前=URL")
    a = ap.parse_args()
    print(build(a.name, a.out, dict(x.split("=", 1) for x in a.link)))
