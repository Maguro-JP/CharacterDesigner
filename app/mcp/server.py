"""Claude から手元のアプリを使うための MCP サーバー（docs/app/PLAN.md の M5）。

中身は持たず、手元のアプリのサーバー（app/server、既定 http://127.0.0.1:8000）を呼ぶだけにする。
描く処理を二重に持たないため（モデルの読み込みも1か所で済む）。先に `sh app/start.sh` でアプリを起動しておく。

起動（Claude Desktop / Claude Code から stdio で呼ぶ）:
  PYTHONPATH=.cache/app/lib python3 -m app.mcp.server
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

API = os.environ.get("CD_API", "http://127.0.0.1:8000").rstrip("/")

mcp = MCPServer(
    name="characterdesigner",
    instructions=(
        "手元のキャラクターデザインのアプリを使う。迷ったら最初に guide を呼ぶ（道具の一覧と、目的ごとの使う順番を返す）。\n"
        "描く: studio_draw（日本語か描く言葉で頼む。検品して直す）→ studio_job で進み → studio_image で絵。"
        "早く1枚ほしいときは free_draw → job → free_image。どちらも ref（参考画像）と mood（空気感）を渡せる。\n"
        "参考画像: ref_search → ref_save → 返った id を studio_draw / free_draw の ref に渡す。\n"
        "描いた絵の手直し（どれも仕事の id と絵のファイル名を渡し、手直しした絵を返す。元の絵は変えない）: "
        "ink（ラフ線を1本にまとめる）、material（一部を切り出して透明感・金属感などの質感を掛ける）、atmosphere（絵全体に空気感）。\n"
        "亜人の設定資料: describe → save_case → draw → job → sheet。三面図: turnaround → turnaround_job → turnaround_image。\n"
        "描く内容の制限: 最初から規制しない。描きたくないものは filters_set で利用者のフィルターに入れる。"
        "子どもを性的に描くことだけは外せない固定の制限で、断られたら理由が返る。\n"
        "時間: 描く依頼は1枚 約3〜5分（CPU）。最初の1件はモデルの読み込みに 約10分。手直しの道具は数秒。"
    ),
)


def _call(method: str, path: str, body: dict | None = None) -> bytes:
    req = urllib.request.Request(API + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        # アプリは理由を detail に日本語で返す。そのまま Claude に渡す
        detail = json.loads(e.read() or b"{}").get("detail", e.reason)
        raise ToolError(f"アプリが断った（{e.code}）: {detail}") from None
    except urllib.error.URLError as e:
        raise ToolError(f"アプリに繋がらない（{API}）。先に sh app/start.sh で起動する: {e.reason}") from None


def _json(method: str, path: str, body: dict | None = None):
    return json.loads(_call(method, path, body))


@mcp.tool()
def list_cases() -> dict:
    """描ける種（亜人の設定）の一覧。名前と表示名、部品を返す。"""
    return {name: {"ja": c.get("ja"), "parts": c.get("parts"), "kind": c.get("kind")} for name, c in _json("GET", "/api/cases").items()}


@mcp.tool()
def describe(text: str) -> dict:
    """日本語の頼みごと（例: 白い狐の巫女）を種の設定に組む。保存はしない。使わなかった言葉と注意も返す。"""
    return _json("POST", "/api/describe", {"text": text})


@mcp.tool()
def save_case(name: str, case: dict) -> dict:
    """種の設定を保存する（describe で組んだ case をそのまま渡せる）。name は英小文字・数字・- _。"""
    return _json("PUT", f"/api/cases/{name}", case)


@mcp.tool()
def draw(case: str, tries: int = 3) -> dict:
    """種を描く依頼を出す。すぐ仕事の id を返す。描き終わるまでは job で見る。"""
    j = _json("POST", "/api/jobs", {"case": case, "tries": tries})
    return {"id": j["id"], "state": j["state"]}


@mcp.tool()
def job(id: str) -> dict:
    """仕事の進み具合と、回ごとの検品で落ちた部品を返す。state が done で passed が true なら sheet で絵を受け取れる。"""
    j = _json("GET", f"/api/jobs/{id}")
    lost = [{"try": r["try"] + 1, "lost": [f"{x['view']} {x['part']}" for x in r.get("result") or [] if not x["ok"]]}
            for r in j["results"] if r.get("result") is not None]
    return {"state": j["state"], "try": None if j["try_index"] is None else j["try_index"] + 1, "tries": j["tries"],
            "passed": j["passed"], "error": j["error"], "checks": lost}


@mcp.tool()
def sheet(id: str) -> Image:
    """検品を通った設定資料（4方向の1枚）を画像で返す。"""
    return Image(data=_call("GET", f"/api/jobs/{id}/files/sheet.png"), format="png")


@mcp.tool()
def studio_draw(text: str = "", prompt: str = "", size: str = "portrait", tries: int = 3, ref: str = "", ref_scale: float = 0.5,
                mood: str = "") -> dict:
    """スタジオに頼む。日本語の頼みごと（text）か、英語の描く言葉（prompt）のどちらかを渡す。
    7つの役割（安全・読み手・演出・描き手・検品・意地の悪い目・整理）が順に回し、検品で落ちたら直して描き直す。
    size は portrait・landscape・square。ref は ref_save で手元に置いた参考画像の id で、画風と色の手本にする（強さ ref_scale、0〜1）。
    mood は空気感（atmosphere_list の id）。描く言葉に空気感の言葉を足す（prompt が空なら足さない）。
    すぐ仕事の id を返す。進みは studio_job、絵は studio_image で受け取る。"""
    words = _mood_words(mood)
    if words and prompt:
        prompt = f"{prompt}, {words}"
    elif words:
        text = f"{text}（空気感: {words}）"
    body = {"text": text, "prompt": prompt, "size": size, "tries": tries}
    if ref:
        body.update(ref=ref, ref_scale=ref_scale)
    j = _json("POST", "/api/studio/jobs", body)
    return {"id": j["id"], "state": j["state"]}


@mcp.tool()
def studio_job(id: str) -> dict:
    """スタジオの仕事の進みと決着。events は役割ごとの出来事（誰が・何を）。passed が true なら studio_image で絵を受け取れる。"""
    j = _json("GET", f"/api/jobs/{id}")
    oc = j.get("outcome") or {}
    return {"state": j["state"], "passed": j["passed"], "error": j["error"],
            "events": [f"{e['role']}: {e['msg']}" for e in j.get("events") or []],
            "prompt": oc.get("prompt"), "reason": oc.get("reason"), "critique": oc.get("critique"), "files": oc.get("files")}


@mcp.tool()
def studio_image(id: str, file: str = "") -> Image:
    """スタジオの仕事の絵を返す。file を省くと検品を通った絵（無ければ最後に描いた絵）。"""
    j = _json("GET", f"/api/jobs/{id}")
    oc = j.get("outcome") or {}
    name = file or oc.get("passed") or (oc.get("files") or [None])[-1]
    if not name:
        raise ToolError("まだ絵が無い。studio_job で state が done になるまで待つ")
    return Image(data=_call("GET", f"/api/jobs/{id}/files/{name}"), format="png")


@mcp.tool()
def turnaround(character: str, count: int = 1, seed: int = 0) -> dict:
    """設定資料集のキャラクターの三面図（正面・横・後ろ）を描く。人形の下絵を3方向から写し、向きごとに count 枚描く。
    CPU で1枚 数分かかる。すぐ仕事の id を返す。進みは turnaround_job、絵は turnaround_image で受け取る。検品はしない"""
    j = _json("POST", f"/api/bible/{character}/turnaround", {"count": count, "seed": seed})
    return {"id": j["id"], "state": j["state"]}


@mcp.tool()
def turnaround_job(id: str) -> dict:
    """三面図の仕事の進み。files は描けた絵の名前（front-0.png・side-0.png・back-0.png のように向きが頭に付く）"""
    j = _json("GET", f"/api/jobs/{id}")
    return {"state": j["state"], "error": j["error"], "files": j.get("files") or []}


@mcp.tool()
def turnaround_image(id: str, file: str) -> Image:
    """三面図の仕事の絵を1枚返す。file は turnaround_job の files の名前"""
    return Image(data=_call("GET", f"/api/jobs/{id}/files/{file}"), format="png")


@mcp.tool()
def proposals() -> dict:
    """待機中にスタジオが拾った提案（描き直し・見本の無い種など）。描くかは do_proposal で決める。"""
    return _json("GET", "/api/proposals")


@mcp.tool()
def do_proposal(id: str) -> dict:
    """提案を承認して描く。仕事の id を返す。"""
    j = _json("POST", f"/api/proposals/{id}/do")
    return {"id": j["id"], "kind": j.get("kind"), "state": j["state"]}


@mcp.tool()
def ref_search(query: str, n: int = 12, commercial: bool = False) -> dict:
    """参考画像を探す（CC ライセンスと public domain の画像、Openverse）。英語の言葉が多く当たる。
    返す各件に作者・ライセンス・元のページがある。使う条件はそれで確かめる。commercial=True で営利で使えるものだけ。
    描くときに使うなら、選んだ1件をそのまま ref_save に渡す。"""
    from urllib.parse import urlencode
    return _json("GET", "/api/refs/search?" + urlencode({"q": query, "n": n, "commercial": str(commercial).lower()}))


@mcp.tool()
def ref_save(item: dict) -> dict:
    """ref_search の結果の1件を手元に置く（.cache/app/refs。リポジトリには入れない）。返す id を studio_draw の ref に渡す。"""
    return _json("POST", "/api/refs", item)


@mcp.tool()
def ref_list() -> dict:
    """手元に置いた参考画像の一覧（id・作者・ライセンス・元のページ）。"""
    return _json("GET", "/api/refs")


# ---------- 案内 ----------

GUIDE = {
    "描く（検品して直す）": ["studio_draw(text|prompt, size, tries, ref, ref_scale, mood)", "studio_job(id)", "studio_image(id, file)"],
    "描く（早く1枚）": ["free_describe(text) で日本語を描く言葉に直す（任意）", "free_draw(prompt, negative, size, count, seed, ref, ref_scale, mood, hires, long)。既定で 1.5 倍に描き直してから 4K（長い辺 4096）に拡大する",
                   "job(id)", "free_image(id, index)"],
    "参考画像を手本にする": ["ref_search(query, n, commercial)", "ref_save(item)", "ref_list()", "→ 描く道具の ref に id を渡す"],
    "空気感（光の筋・霞など）": ["atmosphere_list() で空気感と、描く言葉に足す言葉を見る", "描く道具の mood に渡す（描く言葉に足す）",
                         "atmosphere(job_id, file, mood, strength) で描いた絵に後から掛ける"],
    "描いた絵の手直し": ["ink(job_id, file, width, merge) ラフ線の清書", "material(job_id, file, kind, strength, select, colors, tol, region) 切り出して質感",
                   "atmosphere(job_id, file, mood, strength)"],
    "亜人の設定資料": ["list_cases()", "describe(text)", "save_case(name, case)", "draw(case, tries)", "job(id)", "sheet(id)"],
    "三面図（設定資料集のキャラクター）": ["turnaround(character, count, seed)", "turnaround_job(id)", "turnaround_image(id, file)"],
    "提案（待機中にスタジオが拾ったもの）": ["proposals()", "do_proposal(id)"],
    "描く内容のフィルター": ["filters_get()", "filters_set(filters)"],
    "作画監督の数字の検品と学習（最も重要）": ["measure(id, file, hair) で顔の形・影の順序・髪を測る。outliers を絵で確かめる",
                                 "feedback(id, verdict, reason, file, by) で判定と指摘を手本に足す（利用者の指摘は by=user）",
                                 "learn() で基準を学び直す（利用者の基準に書く。共通の基準は変えない）",
                                 "unmeasured に出た指摘は、まだ数字にしていない崩れ。新しい検品を作る候補"],
}
DETAILS = {
    "size": "portrait（縦長 832x1216）・landscape（横長）・square（正方形）",
    "mood": "holy（神々しい光）・dust（ほこりっぽい）・komorebi（木漏れ日）・underground（地下）・space（宇宙）・haze（霞）。docs/knowledge/atmosphere.md",
    "material の kind": "slime（透明感）・metal（金属感）・heavy（重厚感）・gem（宝石感）・inorganic（無機質感）・dirt（汚れ）",
    "material の select": "person（人物全体）・color（colors の色に近い所。人物の中だけ）・region（部位: skin・hair・clothes・upper・lower・shoes）",
    "ref_scale": "参考画像を効かせる強さ 0〜1（既定 0.5）。上げると背景まで手本に寄る",
    "制限": "最初から規制しない。利用者のフィルター（filters_set）で止める。子どもを性的に描くことだけは外せない。docs/filters.md",
}


@mcp.tool()
def guide() -> dict:
    """このアプリの道具の一覧と、目的ごとの使う順番、引数の値の意味を返す。何ができるか分からないときに最初に呼ぶ。"""
    return {"workflows": GUIDE, "values": DETAILS}


# ---------- 自由に描く ----------

def _mood_words(mood: str) -> str:
    if not mood:
        return ""
    moods = {m["id"]: m["prompt"] for m in _json("GET", "/api/atmosphere")["moods"]}
    if mood not in moods:
        raise ToolError(f"空気感「{mood}」は無い（{', '.join(moods)}）")
    return moods[mood]


@mcp.tool()
def free_describe(text: str) -> dict:
    """日本語の頼みごとを、描く言葉（英語のタグ）に直す。返った prompt を見て直してから free_draw に渡す。"""
    return _json("POST", "/api/free/describe", {"text": text})


@mcp.tool()
def free_draw(prompt: str, negative: str = "", size: str = "portrait", count: int = 1, seed: int = 0,
              ref: str = "", ref_scale: float = 0.5, mood: str = "", hires: float = 1.5, long: int = 4096) -> dict:
    """描く言葉（英語のタグ、カンマ区切り）で早く描く（検品と描き直しはしない）。count は 1〜4 枚。
    ref は ref_save した参考画像の id、mood は空気感（atmosphere_list の id。描く言葉に足す）。hires は描いたあとに引き伸ばして描き直す倍率（既定 1.5 で 1248x1824、1 枚 約6分増える。1 で切る）。long は最後に AI で拡大する長い辺の画素数（既定 4096、0 で切る。約5分増える）。仕事の id を返す。"""
    words = _mood_words(mood)
    body = {"prompt": ", ".join(x for x in (prompt, words) if x), "negative": negative, "size": size, "count": count, "seed": seed, "hires": hires, "long": long}
    if ref:
        body.update(ref=ref, ref_scale=ref_scale)
    j = _json("POST", "/api/free/jobs", body)
    return {"id": j["id"], "state": j["state"], "prompt": body["prompt"]}


@mcp.tool()
def free_image(id: str, index: int = 0) -> Image:
    """free_draw の仕事の絵を返す。index は何枚目か（0 から）。"""
    j = _json("GET", f"/api/jobs/{id}")
    files = [r["file"] for r in j.get("results", []) if r.get("file")] or j.get("files", [])
    if index >= len(files):
        raise ToolError("まだその絵が無い。job で state が done になるまで待つ")
    return Image(data=_call("GET", f"/api/jobs/{id}/files/{files[index]}"), format="png")


# ---------- 作画監督の数字の検品と学習 ----------

@mcp.tool()
def measure(id: str, file: str = "try-0.png", hair: str = "") -> dict:
    """描いた絵（仕事の id とファイル）の当たり前を数字で測る。顔の形（正面に戻すと歪む量 face.rms）、影の順序
    （光に背を向けた面が明るい部位 light.inverted_regions）、髪の白飛びと指定の色（hair、--hair に #rrggbb）。
    outliers が基準から外れた所。外れは絵で確かめてから判定に使う。外れが無くても良い絵とは限らない。"""
    return _json("POST", "/api/measure", {"png": _job_png(id, file), "hair": hair})


@mcp.tool()
def feedback(id: str, verdict: str, reason: str = "", file: str = "try-0.png", by: str = "user", hair: str = "") -> dict:
    """描いた絵への判定（verdict は pass か reject）と理由を、作画監督の学習の手本に足す。利用者の指摘は by="user"
    （作画監督の判定の 3 倍の重み）。返り値の missed は、理由に関わる数字が外れを出していなかった見逃し、
    unmeasured は、どの数字にも結びつかない指摘（次に作る検品の候補）。足したら learn で基準を学び直す。"""
    return _json("POST", "/api/feedback", {"png": _job_png(id, file), "verdict": verdict, "reason": reason, "by": by, "hair": hair})


@mcp.tool()
def learn(dry: bool = False) -> dict:
    """溜まった判定から作画監督の基準を学び直し、利用者の基準（config/norms.user.json）に書く。共通の基準は変えない。
    分けきれない基準と手本の足りない基準は動かさない（kept に理由）。dry=True なら書かずに結果だけ返す。"""
    return _json("POST", f"/api/learn?dry={'true' if dry else 'false'}")


# ---------- 描いた絵の手直し ----------

def _job_png(job_id: str, file: str) -> str:
    import base64
    return "data:image/png;base64," + base64.b64encode(_call("GET", f"/api/jobs/{job_id}/files/{file}")).decode()


def _png_bytes(data_url: str) -> bytes:
    import base64
    return base64.b64decode(data_url.split(",", 1)[1])


@mcp.tool()
def ink(job_id: str, file: str, width: float = 3.0, merge: float = 3.0) -> Image:
    """絵の線を清書する。重ねて描いたラフ線を1本の線にまとめ、透明な地に黒い線の絵で返す。
    width は線の太さ、merge は何画素まで近い線をまとめるか。"""
    return Image(data=_png_bytes(_json("POST", "/api/paint/ink", {"png": _job_png(job_id, file), "width": width, "merge": merge})["png"]), format="png")


@mcp.tool()
def material(job_id: str, file: str, kind: str, strength: float = 0.6, select: str = "person",
             colors: str = "", tol: float = 80.0, region: str = "skin") -> Image:
    """絵の一部を切り出して質感を掛け、元の絵に戻して返す（元の絵は変えない）。
    kind: slime（透明感）・metal・heavy・gem・inorganic・dirt。select: person・color（colors に #rrggbb をカンマ区切り）・region（skin・hair・clothes など）。
    スライムの体なら select="color"、colors に体の色（光の所と陰の所など複数）、kind="slime"。"""
    import base64
    import io

    from PIL import Image as PILImage
    src = _job_png(job_id, file)
    cut = _json("POST", "/api/paint/cut", {"png": src, "mode": select, "colors": colors, "tol": tol, "region": region, "person_only": True})
    if not cut["pixels"]:
        raise ToolError("選べた所が無い（colors か tol か select を変える）")
    mat = _json("POST", "/api/paint/material", {"png": cut["layer"], "kind": kind, "strength": strength})
    rest = PILImage.open(io.BytesIO(_png_bytes(cut["rest"]))).convert("RGBA")
    top = PILImage.open(io.BytesIO(_png_bytes(mat["png"]))).convert("RGBA")
    base = PILImage.new("RGBA", rest.size, (255, 255, 255, 255))
    base.alpha_composite(rest)
    base.alpha_composite(top)
    buf = io.BytesIO()
    base.convert("RGB").save(buf, "PNG")
    return Image(data=buf.getvalue(), format="png")


@mcp.tool()
def atmosphere_list() -> dict:
    """空気感の一覧（id と、描く言葉に足す言葉）。id は free_draw / studio_draw の mood と atmosphere に渡す。"""
    return _json("GET", "/api/atmosphere")


@mcp.tool()
def atmosphere(job_id: str, file: str, mood: str, strength: float = 0.7) -> Image:
    """描いた絵の全体に空気感（光の筋・霞・粒・光の斑点など）を掛けて返す（元の絵は変えない）。mood は atmosphere_list の id。"""
    j = _json("POST", "/api/paint/atmosphere", {"png": _job_png(job_id, file), "mood": mood, "strength": strength})
    return Image(data=_png_bytes(j["png"]), format="png")


# ---------- フィルター ----------

@mcp.tool()
def filters_get() -> dict:
    """利用者のフィルター（描きたくないものを止める。既定は全部切ってある）と、外せない固定の制限の説明。"""
    return _json("GET", "/api/filters")


@mcp.tool()
def filters_set(filters: list) -> dict:
    """利用者のフィルターを保存する。各要素は {name, enabled, words（どの言語でもよい止める言葉の一覧）, negative}。
    渡したものがそのまま全部になる（消したいものは外して渡す）。先に filters_get で今の中身を取ってから直す。"""
    return _json("PUT", "/api/filters", {"filters": filters})


if __name__ == "__main__":
    mcp.run()
