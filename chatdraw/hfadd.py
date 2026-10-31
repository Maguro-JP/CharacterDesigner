"""Hugging Face の名前（持ち主/名前）で絵の模型を足す。

目録に無い模型も使えるように、名前から取れるか・読める形か・どの世代かを、重みを取る前に確かめる。
重み（数 GB）は取らず、置き場の一覧（API）と model_index.json、1 つのファイルなら頭の数 KB だけを読む。
読めない物を目録に入れると、取ったあとで初めて落ちる（数 GB と数十分の無駄）ので、ここで理由を出して止める。
"""
from __future__ import annotations

import json
import re
import struct
import urllib.error
import urllib.request
from fnmatch import fnmatch

from chatdraw.models import FILES, NEW, family_from_class, family_from_keys

API = "https://huggingface.co/api/models/{repo}?blobs=true"
RAW = "https://huggingface.co/{repo}/resolve/main/{file}"
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
STEPS = {"sdxl": (24, 5.0), "sd15": (28, 7.0), "flux1": (28, 3.5), "flux2": (4, 1.0), "zimage": (9, 0.0)}


class AddError(Exception):
    """足せない理由（利用者にそのまま見せる日本語）"""


def _get(url: str, start: int | None = None, end: int | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "CharacterDesigner"})
    if start is not None:
        req.add_header("Range", f"bytes={start}-{end}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def _fetch(get, url: str, *args) -> bytes:
    try:
        return get(url, *args)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise AddError("見つからないか、ログインや利用の同意が要る模型です。公開されていて同意の要らない模型を選んでください")
        if e.code == 404:
            raise AddError("その名前の模型が見つかりません。「持ち主/名前」の形で、綴りを確かめてください")
        raise AddError(f"Hugging Face から返事がありませんでした（{e.code}）。少し待ってからもう一度試してください")
    except (urllib.error.URLError, OSError) as e:
        raise AddError(f"Hugging Face につながりませんでした。ネットワークを確かめてください（{e}）")


def _format(names: set[str]) -> str:
    """diffusers の置き場の、取る分の形（models.FILES の名前）"""
    if any(n.startswith("transformer/") for n in names):
        return "dit"
    if any(re.match(r"unet/.*(?<!\.fp16)\.safetensors$", n) for n in names):
        return "full"
    if any(n.startswith("unet/") and n.endswith(".fp16.safetensors") for n in names):
        return "half"
    if any(n.startswith("unet/") and n.endswith(".bin") for n in names):
        return "bin"
    return ""


def _size(sizes: dict[str, int], fmt: str) -> float:
    pat = FILES[fmt]
    keep = [n for n in sizes if any(fnmatch(n, p) for p in pat.get("allow_patterns", ["*"]))
            and not any(fnmatch(n, p) for p in pat.get("ignore_patterns", []))]
    return round(sum(sizes[n] for n in keep) / 1e9, 1)


def probe(repo: str, get=_get) -> dict:
    """名前を確かめ、目録の 1 行（catalog.json と同じ形）を返す。足せない物は AddError"""
    repo = repo.strip().strip("/")
    for head in ("https://huggingface.co/", "huggingface.co/"):
        if repo.startswith(head):
            repo = "/".join(repo[len(head):].split("/")[:2])
    if not NAME.match(repo):
        raise AddError("「持ち主/名前」の形で書いてください（例: cagliostrolab/animagine-xl-4.0）")
    info = json.loads(_fetch(get, API.format(repo=repo)))
    if info.get("gated") or info.get("private"):
        raise AddError("ログインや利用の同意が要る模型です。この画面からは取れません")
    sizes = {s["rfilename"]: int(s.get("size") or 0) for s in info.get("siblings", [])}
    lic = ((info.get("cardData") or {}).get("license_name") or (info.get("cardData") or {}).get("license") or "")
    base = dict(repo=repo, name=repo.split("/")[1], good="自分で足した模型", en="", score=0, prefix="", negative="",
                commercial=f"札を確かめる（{lic}）" if lic else "札を確かめる", note="Hugging Face の名前で足した。まだ確かめていない")
    if "model_index.json" in sizes:
        index = json.loads(_fetch(get, RAW.format(repo=repo, file="model_index.json")))
        fam = family_from_class(index.get("_class_name", ""))
        fmt = "dit" if fam in NEW else _format(set(sizes))
        if fam == "unknown" or not fmt:
            raise AddError(f"この形（{index.get('_class_name') or '不明'}）はアプリで読めません。SDXL・SD1.5・FLUX などの模型を選んでください")
        steps, guidance = STEPS.get(fam, (28, 4.0))
        return dict(base, family=fam, format=fmt, gb=_size(sizes, fmt), steps=steps, guidance=guidance)
    singles = sorted(n for n in sizes if "/" not in n and n.endswith(".safetensors"))
    if len(singles) != 1:
        raise AddError("diffusers の形（model_index.json）か、.safetensors が 1 つだけの模型を選んでください"
                       + ("（ファイルが複数あり、どれを使うか決められません）" if singles else ""))
    file = singles[0]
    url = RAW.format(repo=repo, file=file)
    n = struct.unpack("<Q", _fetch(get, url, 0, 7)[:8])[0]
    if not 0 < n < 100_000_000:
        raise AddError(".safetensors の頭を読めませんでした")
    keys = list(json.loads(_fetch(get, url, 8, 8 + n - 1)[:n]).keys())
    fam = family_from_keys(keys)
    if fam == "unknown":
        raise AddError("形を見分けられませんでした。SDXL・SD1.5・FLUX.1 の .safetensors を選んでください")
    steps, guidance = STEPS.get(fam, (24, 5.0))
    return dict(base, family=fam, format="single", file=file, gb=round(sizes[file] / 1e9, 1), steps=steps, guidance=guidance)
