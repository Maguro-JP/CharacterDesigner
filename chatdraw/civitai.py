"""Civitai（civitai.com）の模型と LoRA を探して取る。画面（Qt）を持たないので、そのまま試験できる。

使う道は Civitai の公開の API（https://github.com/civitai/civitai/wiki/REST-API-Reference）だけ:
- 探す: GET /api/v1/models?query=&types=Checkpoint|LORA&nsfw=false
- 取る: 版の downloadUrl。キーの要る模型は ?token=<キー> を付ける（キーは利用者がアプリの設定に入れた物だけを使う）
取った物の置き場は共有の模型の置き場（C:\\LLM）: 模型は manual、LoRA は lora。置いた物は起動を待たずに一覧に出る
（models.manual_images と ownstyle.loras は呼ぶたびに置き場を数える）。

取らない物:
- .safetensors 以外（.ckpt や .pt は中で任意のコードを動かせるため）
- Civitai の検査（pickle と virus）を通っていないファイル
見本の絵は、Civitai が全年齢向けとした物（nsfwLevel 1）だけを出す。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

API = "https://civitai.com/api/v1"
AGENT = "CharacterDesigner"   # 既定の Python の名乗りは Civitai の手前（Cloudflare）で 403 になった
KINDS = {"模型": "Checkpoint", "LoRA": "LORA"}
# Civitai の baseModel の名前と、このアプリの世代（models.FAMILIES の鍵）
BASES = {"SDXL 1.0": "sdxl", "Pony": "sdxl", "Illustrious": "sdxl", "NoobAI": "sdxl", "SD 1.5": "sd15", "Flux.1 D": "flux1",
         "Flux.1 S": "flux1"}
THUMB = 320   # 見本の絵の幅（Civitai の画像の道の width= で縮めてもらう）


@dataclass
class Item:
    id: int
    name: str
    kind: str                 # "Checkpoint" か "LORA"
    base: str                 # Civitai の baseModel（SDXL 1.0、Illustrious など）
    version_id: int
    version: str
    file: str                 # 取る .safetensors の名前
    size_mb: float
    url: str                  # 取る道
    images: list = field(default_factory=list)   # 見本の絵（全年齢向けの物だけ）
    words: list = field(default_factory=list)    # LoRA を効かせる言葉（trainedWords）
    creator: str = ""
    downloads: int = 0
    commercial: str = ""      # 商用の可否（Civitai の allowCommercialUse）
    safe: bool = True         # Civitai の検査を通った .safetensors か
    note: str = ""            # 取れない訳

    @property
    def family(self) -> str:
        return BASES.get(self.base, "unknown")

    def page(self) -> str:
        return f"https://civitai.com/models/{self.id}?modelVersionId={self.version_id}"


def _get(url: str, timeout: float = 30.0, opener=urllib.request.urlopen) -> bytes:
    with opener(urllib.request.Request(url, headers={"User-Agent": AGENT}), timeout=timeout) as r:
        return r.read()


def thumb_url(url: str, width: int = THUMB) -> str:
    """Civitai の画像の道を、幅 width の縮めた物の道にする（元の大きさ数 MB を取らない）"""
    if "/orig" in url:
        return url.replace("/orig", f"/width={width}")
    parts = url.rsplit("/", 1)
    return f"{parts[0]}/width={width}/{parts[1]}" if len(parts) == 2 else url


def parse(data: dict) -> list[Item]:
    """API の返りを Item の一覧にする。版は先頭（新しい物）だけを使う"""
    out = []
    for m in data.get("items", []):
        vs = m.get("modelVersions") or []
        if not vs:
            continue
        v = vs[0]
        files = [f for f in v.get("files", []) if str(f.get("name", "")).endswith(".safetensors")]
        f = next((x for x in files if x.get("primary")), files[0] if files else None)
        imgs = [thumb_url(i["url"]) for i in v.get("images", []) if i.get("type", "image") == "image"
                and int(i.get("nsfwLevel") or 99) <= 1 and i.get("url")]
        com = m.get("allowCommercialUse")
        com = "、".join(com) if isinstance(com, list) else str(com or "")
        it = Item(int(m["id"]), str(m.get("name", "")), str(m.get("type", "")), str(v.get("baseModel", "")), int(v.get("id", 0)),
                  str(v.get("name", "")), f["name"] if f else "", round(float(f.get("sizeKB", 0)) / 1024, 1) if f else 0.0,
                  str(f.get("downloadUrl", "")) if f else "", imgs[:4], list(v.get("trainedWords") or []),
                  str((m.get("creator") or {}).get("username", "")), int((m.get("stats") or {}).get("downloadCount", 0) or 0),
                  "商用不可" if not com or com == "None" else "商用可（" + com + "）")
        if f is None:
            it.safe, it.note = False, ".safetensors のファイルが無いので取りません"
        elif f.get("pickleScanResult") not in (None, "Success") or f.get("virusScanResult") not in (None, "Success"):
            it.safe, it.note = False, "Civitai の検査を通っていないので取りません"
        out.append(it)
    return out


def search(query: str, kind: str = "LORA", limit: int = 20, opener=urllib.request.urlopen) -> list[Item]:
    """Civitai を探す。全年齢向けの物だけ（nsfw=false）を、取られた数の多い順に返す"""
    q = {"limit": limit, "types": kind, "nsfw": "false", "sort": "Most Downloaded"}
    if query.strip():
        q["query"] = query.strip()
    return parse(json.loads(_get(f"{API}/models?{urllib.parse.urlencode(q)}", opener=opener)))


def dest_for(item: Item) -> Path:
    from chatdraw.models import manual_dir
    from chatdraw.ownstyle import lora_dir
    return (lora_dir() if item.kind == "LORA" else manual_dir()) / Path(item.file).name


def fetch(item: Item, key: str = "", progress=lambda got, total: None, note=lambda s: None, opener=None) -> Path:
    """item を置き場に取り、横に見本の絵と言葉の .civitai.json を置く。返すのは置いた道"""
    from chatdraw.fetchfile import fetch_resumable
    if not item.safe:
        raise ValueError(item.note)
    dest = dest_for(item)
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = item.url + (("&" if "?" in item.url else "?") + "token=" + urllib.parse.quote(key) if key else "")

    def open_(req, timeout=60.0):
        req.add_header("User-Agent", AGENT)
        try:
            return (opener or urllib.request.urlopen)(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise PermissionError("この模型は Civitai の API キーが要ります。設定の「Civitai の API キー」に入れてください") from e
            raise
    fetch_resumable(url, dest, 0, progress=progress, opener=open_, note=note)
    with open(dest, "rb") as f:   # .safetensors の頭（長さ 8 バイト + JSON）を確かめる。HTML のエラーの頁を模型として置かない
        head = f.read(9)
    if len(head) < 9 or head[8:9] != b"{":
        dest.unlink(missing_ok=True)
        raise ValueError("取れた物が .safetensors ではありませんでした（API キーが要るか、配り元の頁が返りました）")
    meta = dict(source="civitai", id=item.id, version_id=item.version_id, name=item.name, base=item.base, kind=item.kind,
                words=item.words, images=item.images, creator=item.creator, commercial=item.commercial, page=item.page())
    dest.with_suffix(".civitai.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return dest

