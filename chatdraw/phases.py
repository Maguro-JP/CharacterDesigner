"""人の描き方の工程に分けて描く（精度優先）。工程の調べは docs/knowledge/drawing-phases.md。

人は 1 回で描き上げない。目的を決め、小さなサムネイルを何枚か比べて構図を選び、丸と棒のアタリで重心と等身を決め、
体の形・顔と手と足・服と髪と持ち物を順に描き、線を清書し、部位ごとに下塗りし、光源を決めて影を 2 段に置き、
光と艶を足し、最後に縮めて見る・反転して見るで崩れを探す。工程ごとに見る物が決まっていて、崩れを見つけたら、
その崩れが決まった工程まで戻って直す。次の工程は、前の工程で決めた物を土台にして壊さずに足す。

設計の決まり:
- 工程は 12（PHASES）。どの工程も「描くか処理する → 見る物を数字で測る → 崩れがあれば 1 回だけ直す」で短く終わる。
  工程の終わりごとに gc を掛けてメモリを返す（1 工程に詰め込むと重くて進まず、まとめるとメモリが溢れて落ちた）
- 崩れが直しで消えなければ、崩れが決まった工程（back）まで戻る。戻るのは全体で BACKS 回、同じ工程へは REVISIT 回まで。
  検品が通るまで無限に回す形にしない（0.5.20 でそうしたら終わらなくなった）
- 模型で絵を描くのはサムネイルの工程だけ。工程 2 から先は、選んだサムネイル（同じ頼み・同じ種の AI モードの絵と同じ）を土台にし、
  構図・人物・服を変えない（前は下描きで絵全体に描き重ね、アタリで種を変えて描き直し、工程ごとに絵が丸ごと変わった）
- 形の崩れ（手・足・顔、左右の目の高さ）は線画の清書の工程で、崩れた枠の中だけを直す（LINES）。塗りの工程（下塗り〜仕上げ）では
  形を変えない。仕上げで形の崩れが残れば線画の清書へ戻る。直しを重ねるたびに強くする（FIXES）
- 縮めて見る・反転して見る・光源の向き・線の途切れ・影の向きは chatdraw/phasetools.py で測るだけにし、模型の絵には線の強弱・影の 2 段目・
  色合わせを掛けない（掛けた絵は線画の清書から仕上げまで全部崩れた。0.5.36）
- 模型に渡す言葉は、頼みを訳した言葉だけ（直しにも five fingers などを足さない）。利用者が工程の確かめで足した言葉は、その訳を足す。
  渡した言葉は「模型に渡す言葉:」の知らせにし、アプリは進み具合の欄の詳細（ツールチップ）にだけ置く
- 工程の始めには必ず「工程 i/n「名前」」の知らせを出す。アプリの進みの帯はこれで全体の進みを出す
- 確かめ（confirm）を渡すと、工程が終わるたびに呼び、「進める」「この工程を描き直す」「言葉を足して描き直す」を受ける
- 止める旗が立ったら、その工程の区切りで止まる
- 工程の絵（窓に出す絵、NN-名前.png、確かめに出す絵）は、模型の絵をそのまま見せず、人が描いている途中の見た目にする
  （白紙 → サムネイル → ラフ → 線画 → 下塗り → 影 → 光 → 仕上げ。chatdraw/humanpaint.py）。アタリ（体の点）は裏の処理で、出さない。
  描き終えたら、仕上げのゴミ（孤立した点、色の継ぎ目）を塗りだけで直し、最後の絵から人の工程の絵（背景・ディテールを含む）と
  筆が動くタイムラプスを作る
- 最後の絵が、サムネイルの絵（AI モードの絵）より検品の崩れが多ければ、サムネイルの絵を使う（精度優先で AI モードより悪くしない）
"""
from __future__ import annotations

import gc
import json
import sys
import time
from pathlib import Path

# 工程の名前、決める物、見る物、判定の数字
PHASES = [
    ("目的", "何を一番見せるか（主役）", "頼み", "頼みの言葉の数、主役の言葉"),
    ("サムネイル", "構図（小さなラフを何枚か比べて選ぶ）", "白と黒の塊、画面の重さ", "人数、描かれていない物、重さの片寄り（weight_x）"),
    ("アタリ", "頭の大きさ、等身、重心", "立てるか、等身", "重心のずれ（balance）、等身（heads）、人数"),
    ("体の形", "骨格、関節の向き、左右の長さ", "腕と脚の長さ", "骨の長さの比、余分な腕・脚・頭"),
    ("顔・手・足の下描き", "顔の中心、目の高さ、指", "左右の目、指の数", "目の傾き（eye_tilt）、手・指・足・顔の崩れの数"),
    ("服・髪・持ち物", "体に乗る服と髪、持ち物", "頼んだ物があるか", "描かれていない物、頼んでいない物"),
    ("線画の清書", "線の強弱", "輪郭の途切れ、線のメリハリ", "外の輪郭の途切れ（gap）、線の明るさの差（contrast）"),
    ("下塗り", "部位ごとの色", "色の塊、色の数", "色の数（colors）"),
    ("光源", "光の向き 1 つ", "光の来る側", "左右・上下の明るさの差（dx, dy）"),
    ("影 2 段", "影 1 段目・2 段目", "影の向きのそろい、影が光より明るくないか", "影の側の暗い画素の割合（shade_share）、影と光の明るさの差"),
    ("光・艶・目のハイライト", "目の光、髪の艶", "目の中の光", "両目の一番明るい画素（eye_max）"),
    ("仕上げ", "全体の崩れ", "縮めて見る、反転して見る", "手・足・顔・体の崩れの数、縮めた明るさの差、顔の反転の差（asym）"),
]
NAMES = [p[0] for p in PHASES]
THUMBS = 2            # サムネイルの枚数
THUMB_SCALE = 1.0     # サムネイルの大きさ（描く大きさの割合）。同じ種・同じ大きさならアタリが同じ構図になるので縮めない
THUMB_STEPS = 1.0     # サムネイルの描く工程の数の割合。選んだサムネイルをそのままアタリにする（半分の工程で描いてから同じ種でアタリを
                      # 描き直すと、同じ構図を 2 度描いて 214 秒かかり、描き直した絵は別の色になった。0.25 ではぼやけた絵になった）
FIX = 0.55            # 顔・手・足の直し: 崩れた枠の中だけを描き直す強さ（1 回目）
FIXES = (0.55, 0.7, 0.85, 0.95)   # 直しを重ねるたびに強くする。同じ強さで戻って直すと崩れた指の形をなぞり、下描きから最後まで同じ崩れが残った
COLORS_MOST = 14      # 下塗り: 人物の 2% 以上を占める色がこれより多ければ、色が散っている（私の推測）
LINES = 6             # 線画の清書の工程の番号（0 から）。形の崩れはここへ戻って直す
BACKS = 3             # 戻って直すのは全体でこの回数まで
REVISIT = 2           # 同じ工程に戻るのはこの回数まで
WORDS_NOTE = "模型に渡す言葉: "   # この頭の知らせは会話に出さず、進み具合の欄の詳細にだけ置く（chatdraw/activity.py）
GO, REDO, WORDS = "go", "redo", "words"   # 工程の確かめの答え


class Checks:
    """工程ごとの検品。試験はこの組を偽物に差し替える"""

    @staticmethod
    def request(image, prompt):
        from chatdraw import requestcheck
        return requestcheck.check(image, prompt)

    @staticmethod
    def body(image, prompt, tags=None):
        from chatdraw import sanity
        return sanity.check(image, prompt, tags=tags)

    @staticmethod
    def points(image):
        """体の 17 点（VitPose）。同じ絵は 1 回だけ推論する（twostage._vitpose が置いておく）"""
        from chatdraw import twostage
        return {"readable": True, "points": twostage.keypoints(image)}

    @staticmethod
    def pose(image):
        """骨組みを読み、骨の比を測る。map は骨組みを重ねた絵（工程の絵に残す）"""
        try:
            from chatdraw import sanity, twostage
            kp = twostage.keypoints(image)
            skel, _n = twostage.pose_map(image)
        except Exception as e:   # noqa: BLE001  骨組みの部品が無い。見ていない物を通ったことにしない
            return {"readable": False, "bad": [], "reason": f"骨組みを読めません（{e}）"}
        bad = []
        if len(kp) < 10:
            bad.append(f"骨組みが読めない（体の点 {len(kp)}/17）")
        for chain in sanity.ARM_CHAINS + sanity.LEG_CHAINS:
            r = sanity.bone_ratio(kp, chain)
            if r is not None and (r > sanity.BONE_MOST or r < 1 / sanity.BONE_MOST):
                bad.append(f"骨の長さの比が外れている（{chain[1]} {r}）")
        from PIL import Image
        over = Image.blend(image.convert("RGB"), skel.convert("RGB").resize(image.size), 0.45)
        return {"readable": True, "bad": bad, "map": over, "points": len(kp)}

    @staticmethod
    def hands(image, prompt):
        from chatdraw import handcheck
        return handcheck.check(image, asked=prompt)


class _Safe:
    """検品の 1 つが例外を出したら（部品が無い・試験の偽物に無い検品も）、その検品を「読めなかった」にして次へ進む"""

    def __init__(self, inner):
        self.inner = inner

    def __getattr__(self, name):
        fn = getattr(self.inner, name, None)

        def call(*a, **k):
            if fn is None:
                return {"readable": False, "bad": [], "reason": f"検品 {name} がありません"}
            try:
                return fn(*a, **k)
            except Exception as e:   # noqa: BLE001  見ていない物を通ったことにしない（readable を False にする）
                if type(e).__name__ == "Stopped":
                    raise
                return {"readable": False, "bad": [], "reason": f"検品できませんでした（{type(e).__name__}: {e}）"}
        return call


def abilities(painter) -> tuple[bool, bool]:
    """(線に沿って描けるか, 枠の中だけ直せるか)。偽の模型は abilities を持てる"""
    own = getattr(painter, "abilities", None)
    if own is not None:
        return tuple(own)
    from chatdraw.models import family, image_model
    f = family(image_model(getattr(painter, "model", "")).family)
    return bool(f.sketch), bool(f.inpaint)


def release() -> float:
    """工程の区切りでメモリを返し、今の常駐の大きさ（MB）を返す"""
    gc.collect()
    torch = sys.modules.get("torch")
    if torch is not None:
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:   # noqa: BLE001
            pass
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return round(int(line.split()[1]) / 1024, 1)
    except OSError:
        pass
    try:
        import resource
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    except Exception:   # noqa: BLE001
        return 0.0


def _mask(size, regions):
    from PIL import Image, ImageDraw
    mask = Image.new("L", size, 0)
    d = ImageDraw.Draw(mask)
    for (x0, y0, x1, y1), _kind in regions:
        cx, cy, rr = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0) * 0.6
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=255)
    return mask


def _people(req: dict) -> list[str]:
    if not req.get("readable"):
        return []
    return [f"人数が違う: {p}" for p in req.get("people", [])] + list(req.get("body", []))


def _missing(req: dict) -> list[str]:
    return [f"描かれていない: {m}" for m in req.get("missing", [])] if req.get("readable") else []


def _extra(req: dict) -> list[str]:
    return [f"頼んでいない: {e}" for e in req.get("extra", [])] if req.get("readable") else []


def draw(painter, prompt: str, seed: int, size, keep: Path, say=lambda m: None, on_step=None, checks=Checks, on_preview=None,
         confirm=None, pause_key: str | None = None, pause_job: dict | None = None) -> dict:
    """12 の工程で 1 枚を描く。返り値は {"image": 最後の絵, "phases": 工程ごとの最後の記録, "history": 全部の記録,
    "left": 残った崩れ, "checked": 検品できたか, "backs": 戻った回数}。どの工程も必ず終わり、戻る回数にも上限がある。
    confirm(i, 名前, 絵, 記録) は "go"・"redo"・("words", 足す言葉の訳) を返す。
    pause_key があれば、メモリの見張り・メモリ不足・時間切れで工程が打ち切られたとき、その工程に入ったときの状態を
    chatdraw/pausekeep.py に残して Paused で返す。同じ鍵で呼び直すと、その工程から続ける（前は始めから描き直した）"""
    from PIL import Image
    from chatdraw.engine import Stopped
    from chatdraw import handcheck, phasetools as pt, humanpaint as hp
    keep.mkdir(parents=True, exist_ok=True)
    # 模型の拡散の途中の絵は窓に渡さない。模型は 1 回で色も影も背景も付いた絵を出すので、渡すとサムネイルの時点で完成の絵が見えた。
    # 窓には工程の終わりごとに、人が描いている途中に見える絵（chatdraw/humanpaint.py）だけを渡す
    pv = {}
    _can_line, can_fix = abilities(painter)
    checks = _Safe(checks)
    w, h = (size or (832, 1216))
    n = len(PHASES)
    st = {"image": None, "prompt": prompt, "thumb": None, "points": {}, "light": {}, "height": 0, "seed": seed}

    def parts_of(img):
        try:
            return pt.parts(img)
        except Exception:   # noqa: BLE001
            return None

    def tell(words):
        say(f"{WORDS_NOTE}{words}")

    memo = {"thumbs": {}, "fix_n": 0, "draft": None, "refix": False}   # 描いた絵を使い回す（同じ種・同じ言葉の絵は 2 度描かない）

    def stop():
        if getattr(painter, "stop", False) is True:
            raise Stopped("止めました")

    def steps(ratio):
        """painter.steps を一時的に割合で減らす（戻すのは呼んだ側）"""
        s0 = getattr(painter, "steps", None)
        if isinstance(s0, int):
            painter.steps = max(4, int(s0 * ratio))
        return s0

    def unsteps(s0):
        if isinstance(s0, int):
            painter.steps = s0

    def points(img):
        got = checks.points(img)
        return dict(got.get("points") or {}) if got.get("readable") else {}

    def fix_regions(img, res, s, words_used, extra=()):
        """手・足・顔の崩れた枠の中だけを 1 回描き直す。崩れが増えたら直す前の絵を返す"""
        regions = list(handcheck.bad_regions(res)) + list(extra)
        if not regions or not can_fix:
            return img, res, False
        words = st["prompt"]
        k = memo["fix_n"]
        memo["fix_n"] += 1
        strength = FIXES[min(k, len(FIXES) - 1)]
        say(f"崩れた所を 1 回だけ直しています（{len(regions)} か所、囲みの中だけ、強さ {strength}）")
        tell(words)
        words_used.append(words)
        tried = painter.redraw(words, s + 13 * k, img, _mask(img.size, regions), strength=strength)
        again = checks.hands(tried, st["prompt"])
        if again.get("readable") and len(again.get("bad", [])) <= len(res.get("bad", [])):
            return tried, again, True
        say("直しで崩れが減らなかったので、直す前の絵を次の工程に渡します")
        return img, res, True

    # ここから工程。どれも {"image", "found", "fixed", "after", "words", "numbers", "readable", "note", "back", "show"} を返す
    def p_purpose(v):
        # 絵の模型はこの工程で読む。読むのをサムネイルの最初の 1 枚に任せると、何分も「サムネイル」の工程で止まって見えた
        if hasattr(painter, "load") and not getattr(painter, "loaded", lambda: True)():
            say("絵の模型を読んでいます（目的の工程の準備）")
            try:
                painter.load((w, h))
            except Exception as e:   # noqa: BLE001  読めなければ、サムネイルで描くときに読み直す（その時の失敗はそこで出る）
                say(f"絵の模型を先に読めませんでした（{type(e).__name__}）。描くときに読みます")
        tags = [t.strip() for t in st["prompt"].split(",") if t.strip()]
        found = [] if tags else ["頼みが空です"]
        return {"image": None, "found": found, "numbers": {"words": len(tags), "main": tags[0] if tags else ""}, "readable": True}

    def p_thumbs(v):
        tw, th = (w, h) if THUMB_SCALE >= 1 else (max(256, int(w * THUMB_SCALE) // 8 * 8), max(256, int(h * THUMB_SCALE) // 8 * 8))
        s0 = steps(THUMB_STEPS)
        best, rows, words = None, [], []
        try:
            for k in range(THUMBS):
                stop()
                s = st["seed"] + v * 1000 + k
                say(f"サムネイル {k + 1}/{THUMBS} を描いています（{tw}x{th}）")
                tell(st["prompt"])
                words.append(st["prompt"])
                img = painter.paint(st["prompt"], s, on_step=on_step, size=(tw, th), **pv)
                if THUMB_SCALE >= 1 and THUMB_STEPS >= 1:
                    memo["thumbs"][(st["prompt"], s)] = img
                req = checks.request(img, st["prompt"])
                wt = pt.thumb_weight(img)
                flaws = _people(req) + _missing(req) + (["画面の重さが片寄っている"] if wt["weight_x"] > pt.WEIGHT_MOST else [])
                rows.append({"seed": s, **wt, "flaws": len(flaws)})
                score = (len(flaws), wt["weight_x"])
                if best is None or score < best[0]:
                    best = (score, img, s, flaws, req)
                rows[-1]["score"] = list(score)
                del img
                gc.collect()
        finally:
            unsteps(s0)
        _score, img, s, flaws, req = best
        st["thumb"], st["seed_pick"] = img, s
        st["seed_next"] = [r["seed"] for r in sorted(rows, key=lambda r: tuple(r["score"])) if r["seed"] != s]
        say(f"サムネイル {THUMBS} 枚のうち、種 {s} の構図を選びました（崩れ {len(flaws)}）")
        return {"image": img.resize((w, h)), "found": flaws, "numbers": {"thumbs": rows, "picked": s}, "words": words,
                "readable": bool(req.get("readable"))}

    def atari_flaws(img):
        req = checks.request(img, st["prompt"])
        pts = points(img)
        bal = pt.balance(img)
        hd = pt.heads(pts, bal.get("height", 0)) if bal.get("readable") else None
        flaws = _people(req)
        if bal.get("readable") and bal["balance"] > pt.BALANCE_MOST:
            flaws.append(f"重心が足の上に無い（{bal['balance']}）")
        if hd is not None and not (pt.HEADS[0] <= hd <= pt.HEADS[1]):
            flaws.append(f"等身が外れている（{hd}）")
        nums = {"balance": bal.get("balance"), "heads": hd, "points": len(pts)}
        return flaws, nums, pts, bal, bool(req.get("readable")) and bool(bal.get("readable"))

    def p_atari(v):
        """アタリは裏の処理。選んだサムネイルの絵の体の点（頭・肩・腰・関節）を読み、重心と等身を測るだけで、絵は描き直さない
        （前は崩れがあると種を変えたアタリを描き、工程 3 で絵が丸ごと別の絵に変わった）。腕は部位分けの腕の形から推し直す
        （VitPose は振っている手を読み違え、腕を下に垂らした点を返した）"""
        img = st["image"]
        found, nums, pts, bal, ok = atari_flaws(img)
        pts = hp.arm_points(pts, hp.clean_parts(img, parts_of(img)))
        st["points"], st["height"] = pts, bal.get("height", 0)
        people = [f for f in found if f.startswith("人数")]
        return {"image": img, "found": found, "numbers": nums, "readable": ok, "back": 1 if people else None}

    def p_body(v):
        img = st["image"]
        pz, bd = checks.pose(img), checks.body(img, st["prompt"])
        found = (list(pz.get("bad", [])) if pz.get("readable") else []) + (list(bd.get("bad", [])) if bd.get("readable") else [])
        note = "" if pz.get("readable") else pz.get("reason", "骨組みを読めませんでした")
        return {"image": img, "show": pz.get("map"), "found": found, "numbers": {"points": pz.get("points")}, "note": note,
                "readable": bool(pz.get("readable")) and bool(bd.get("readable")), "back": 2}

    def p_draft(v):
        """顔・手・足の下描き。崩れを測るだけで、直しは線画の清書の工程でまとめてする（人も線画の段階で形の間違いを直す）。
        前はここで絵全体に描き重ね（refine）、工程ごとに絵が変わった"""
        img = st["image"]
        res = checks.hands(img, st["prompt"])
        tilt = pt.eye_tilt(st.get("points") or {})
        found = list(res.get("bad", [])) + ([f"左右の目の高さがずれている（{tilt}）"] if tilt is not None and tilt > pt.EYE_TILT else [])
        return {"image": img, "found": found, "numbers": {"eye_tilt": tilt, "bad": len(res.get("bad", []))},
                "readable": bool(res.get("readable"))}

    def p_wear(v):
        """服・髪・持ち物。頼んだ物が描かれているかを測るだけで、服や髪を描き直さない（描き直すと服が変わった）"""
        img = st["image"]
        req = checks.request(img, st["prompt"])
        found = _missing(req) + _extra(req)
        return {"image": img, "found": found, "numbers": {"missing": len(_missing(req)), "extra": len(_extra(req))},
                "readable": bool(req.get("readable"))}

    def p_lines(v):
        """線画の清書。形の崩れ（手・足・顔、左右の目の高さ）はこの工程で直す。直すのは崩れた枠の中だけで、崩れが減ったときだけ使う。
        線の強弱は模型の絵に掛けない（掛けた絵は線がにじんで崩れた）。測るだけにし、窓には線画だけを見せる"""
        img, words = st["image"], []
        before = pt.lines(img)
        res = checks.hands(img, st["prompt"])
        pts = st.get("points") or {}
        tilt = pt.eye_tilt(pts)
        tilt_bad = tilt is not None and tilt > pt.EYE_TILT
        gap = [f"外の輪郭が途切れている（{before['gap']}）"] if before.get("readable") and before["gap"] > pt.LINE_GAP_MOST else []
        found = list(res.get("bad", [])) + ([f"左右の目の高さがずれている（{tilt}）"] if tilt_bad else []) + gap
        extra = [(pt.face_box(pts), "face")] if tilt_bad and pt.face_box(pts) else []
        img, res2, fixed = fix_regions(img, res, st["seed"] + 77 + v * 1000, words, extra)
        pts2 = points(img) if fixed else pts
        tilt2 = pt.eye_tilt(pts2) if fixed else tilt
        if fixed and pts2:
            st["points"] = hp.arm_points(pts2, hp.clean_parts(img, parts_of(img)))
        after = list(res2.get("bad", [])) + ([f"左右の目の高さがずれている（{tilt2}）"] if tilt2 is not None and tilt2 > pt.EYE_TILT else []) + gap
        return {"image": img, "found": found, "fixed": fixed, "after": after, "words": words,
                "readable": bool(before.get("readable")) and bool(res.get("readable")),
                "numbers": {"before": before, "eye_tilt": tilt2, "bad": len(res2.get("bad", []))}}

    def p_base(v):
        import numpy as np
        img = st["image"]
        m = pt.silhouette(img)
        if m.sum() < 50:
            return {"image": img, "found": [], "readable": False, "numbers": {}}
        q = img.convert("RGB").quantize(colors=32, method=Image.MEDIANCUT)
        a = np.asarray(q)[m]
        counts = np.bincount(a.ravel(), minlength=32) / max(a.size, 1)
        colors = int((counts >= 0.02).sum())
        p = pt.parts(img)
        nums = {"colors": colors, "parts": None if p is None else int(len(set(np.unique(p).tolist()) - {0}))}
        found = [f"色が散っている（{colors} 色）"] if colors > COLORS_MOST else []
        return {"image": img, "found": found, "numbers": nums, "readable": True}

    def p_light(v):
        lit = pt.light(st["image"])
        st["light"] = lit
        flat = lit.get("readable") and abs(lit["dx"]) < 2 and abs(lit["dy"]) < 2
        if lit.get("readable"):
            say(f"光源を{lit['side']}{'上' if lit['dy'] < 0 else '下'}に決めました")
        return {"image": st["image"], "found": ["光の向きが決まらない（明るさが平たい）"] if flat else [], "numbers": lit,
                "readable": bool(lit.get("readable"))}

    def p_shadow(v):
        img, lit = st["image"], st.get("light") or {}
        sh = pt.shadows(img, lit)

        def flaws(s):
            out = []
            if s.get("readable") and s["shade_minus_lit"] > 0:
                out.append(f"影が光より明るい（{s['shade_minus_lit']}）")
            if s.get("readable") and s["shade_share"] < 0.5:
                out.append(f"影の向きがそろっていない（{s['shade_share']}）")
            return out
        found = flaws(sh)
        pts = st.get("points") or {}
        keep_m = None
        fb = pt.face_box(pts)
        if fb:
            import numpy as np
            keep_m = np.zeros((img.height, img.width), bool)
            x0, y0, x1, y1 = (int(max(0, c)) for c in fb)
            keep_m[y0:y1, x0:x1] = True   # 顔に濃い影を足さない
        # 模型の絵に影の 2 段目を重ねない（重ねた絵は汚れた影になって崩れた）。測るだけにする
        del keep_m
        return {"image": img, "found": found, "readable": bool(sh.get("readable")), "numbers": {"before": sh}}

    def p_shine(v):
        """光・艶・目のハイライト。目の光を測るだけで、目を描き直さない（塗りの工程で形を変えない）"""
        img = st["image"]
        cl = pt.catchlights(img, st.get("points") or {})
        found = [f"目の光が無い（{x}）" for x in cl.get("eye_max", []) if x < pt.CATCHLIGHT]
        return {"image": img, "found": found, "numbers": {"eye_max": cl.get("eye_max")}, "readable": bool(cl.get("readable"))}

    def p_finish(v):
        """仕上げ。縮めて見る・反転して見るで全体の崩れを探す。形の崩れはここでは直さず、線画の清書の工程へ戻って直す
        （塗りの工程では塗りだけを直し、形は変えない）"""
        img = st["image"]
        res = checks.hands(img, st["prompt"])
        body = checks.body(img, st["prompt"])
        pts = st.get("points") or {}
        sv, fv = pt.shrink_view(img), pt.flip_view(img, pt.face_box(pts))
        views = []
        if sv.get("readable") and sv["contrast"] < pt.SHRINK_CONTRAST:
            views.append(f"縮めると主役が目立たない（{sv['contrast']}）")
        if fv.get("readable") and fv["asym"] > pt.FLIP_MOST:
            views.append(f"反転すると顔が片側に歪んで見える（{fv['asym']}）")
        body_bad = list(body.get("bad", [])) if body.get("readable") else []
        found = list(res.get("bad", [])) + body_bad + views
        hands_left = bool(res.get("bad"))
        return {"image": img, "found": found, "numbers": {"shrink": sv.get("contrast"), "asym": fv.get("asym")},
                "readable": bool(res.get("readable")) and bool(body.get("readable")), "back": LINES if hands_left and can_fix else None}

    def finish_human(img, left):
        """仕上げのゴミ（孤立した点、色の継ぎ目）を直し、人の工程の絵とタイムラプスを作る。工程の絵も最後の絵から作り直す
        （途中の模型の絵から作ると、工程ごとに顔や服が少しずつ違い、つないだときに別の絵に見えた）。直せなかった継ぎ目は left に足す"""
        if img is None:
            return {"image": img}
        try:
            parts = parts_of(img)
            cleaned, rep = hp.clean(img, parts)
            if rep["specks"]:
                say(f"仕上げ: 孤立した点を {rep['specks']} 画素、周りの色で埋めました")
            seams = rep["seams"]
            if seams:   # 色の継ぎ目は塗りだけで直す（形は変えない）。継ぎ目より下の色を、上の色に寄せる
                say("仕上げ: 色の継ぎ目（" + "、".join(x["part"] for x in seams) + "）を、塗りだけで直しています")
                tried = hp.fix_seams(cleaned, parts, seams)
                again = hp.seams(tried, parts)
                if len(again) < len(seams):
                    cleaned, seams = tried, again
            if not rep["seams_readable"]:
                say("仕上げ: 部位分けが無いので、色の継ぎ目は測れていません")
            left += [f"色の継ぎ目が残っている（{x['part']}）" for x in seams]
            pts_final = points(cleaned) or st.get("points") or {}   # アタリは最後の絵の体の点に合わせる
            got = hp.build(cleaned, keep, parts_of(cleaned), pts_final)
            got["clean"] = dict(rep, seams_left=seams)
            for k in range(n):   # 工程の絵を、最後の絵から作り直す
                row = final.get(k)
                if row and row.get("image"):
                    hp.for_phase(k, got["image"], parts_of(got["image"]), pts_final).save(row["image"])
            say(f"人の工程の絵 {len(got['stages'])} 枚とタイムラプス（{got['frames']} 枚）を作りました")
            frames = got.pop("frame_list", [])
            if on_preview is not None and frames:   # 最後の絵で作り直した描く過程を、キャンバスで白紙から通して見せる
                size = got["image"].size
                for f in frames[::max(1, len(frames) // 60)]:
                    try:
                        on_preview(f.resize(size, Image.BILINEAR))
                    except Exception:   # noqa: BLE001  見せるだけ
                        break
                on_preview(got["image"])
            return got
        except Exception as e:   # noqa: BLE001  作れなくても、描いた絵は渡す。作れなかったことは残った崩れに書く
            if type(e).__name__ == "Stopped":
                raise
            left.append(f"人の工程の絵を作れませんでした（{type(e).__name__}: {e}）")
            return {"image": img}

    run = [p_purpose, p_thumbs, p_atari, p_body, p_draft, p_wear, p_lines, p_base, p_light, p_shadow, p_shine, p_finish]
    assert len(run) == n
    final: dict[int, dict] = {}
    history: list[dict] = []
    visits, entry = [0] * n, {}
    backs, i = 0, 0
    from chatdraw import pausekeep
    saved = pausekeep.state(pause_key) if pause_key else None
    if saved:   # 一時停止した工程から続ける。描き終えた工程の絵と記録はそのまま使う
        i, backs, visits, final, history, entry = saved["i"], saved["backs"], saved["visits"], saved["final"], saved["history"], saved["entry"]
        st.clear()
        st.update(entry[i])
        say(f"一時停止した工程 {i + 1}/{n}「{PHASES[i][0]}」から続けます")
    while i < n:
        stop()
        name = PHASES[i][0]
        entry.setdefault(i, None)
        if not (saved and saved["i"] == i and entry.get(i)):
            entry[i] = dict(st)   # 戻るときは、この工程に入ったときの土台から描き直す
        saved = None
        say(f"工程 {i + 1}/{n}「{name}」: {PHASES[i][1]}（見る物: {PHASES[i][2]}）")
        t0 = time.time()
        try:
            got = run[i](visits[i])
        except Exception as e:   # noqa: BLE001  止めて捨てずに、この工程に入ったときの状態を残す
            if not pause_key or isinstance(e, Stopped) or not pausekeep.is_pause(e):
                raise
            pausekeep.save(pause_key, "phases", f"工程 {i + 1}/{n}「{name}」で一時停止", pause_job,
                           {"i": i, "backs": backs, "visits": visits, "final": final, "history": history, "entry": entry})
            raise pausekeep.Paused(f"工程 {i + 1}/{n}「{name}」で一時停止しました（{type(e).__name__}）。"
                                   "途中まで保存したので、「再開」でこの工程から続けます", pause_key) from e
        if got.get("image") is not None:
            st["image"] = got["image"]
        found, fixed = list(got.get("found", [])), bool(got.get("fixed"))
        after = list(got.get("after", [])) if fixed else []
        left = after if fixed else found
        shown = hp.blank((w, h)) if i == 0 else None   # 描き始めは白い紙
        if st.get("image") is not None:
            try:
                shown = hp.for_phase(i, st["image"], parts_of(st["image"]), st.get("points") or None)
            except Exception as e:   # noqa: BLE001  見せる絵を作れなくても、描く流れは止めない
                say(f"工程の絵を作れませんでした（{type(e).__name__}: {e}）")
        path = None
        if shown is not None:
            path = keep / f"{i + 1:02d}-{name}.png"   # 順の分かる名前（タイムラプスがこの順につなぐ）
            shown.save(path)
            if on_preview is not None:   # 前の工程の絵の上に、この工程を描き重ねていく様子をキャンバスに出す
                try:
                    for f in (hp.transition(memo["shown"], shown) if memo.get("shown") is not None else [shown]):
                        on_preview(f)
                    memo["shown"] = shown
                except Exception:   # noqa: BLE001  見せるだけ。描く流れは止めない
                    pass
        mem = release()
        row = {"phase": name, "decides": PHASES[i][1], "checks": PHASES[i][2], "numbers_of": PHASES[i][3],
               "image": str(path) if path else None, "found": found, "fixed": fixed, "after": after,
               "words": list(got.get("words", [])), "numbers": got.get("numbers", {}), "readable": bool(got.get("readable", True)),
               "seconds": round(time.time() - t0, 2), "mem_mb": mem, "visit": visits[i],
               "tone": pt.tone(st["image"]) if st.get("image") is not None else None}
        if got.get("note"):
            row["note"] = got["note"]
        final[i] = row
        history.append(row)
        say(f"工程 {i + 1}/{n}「{name}」の検品: " + ("崩れは見つかりませんでした" if not left else "残った崩れ " + "、".join(left[:4])))
        if confirm is not None:
            ans = confirm(i, name, shown, row)
            kind = ans[0] if isinstance(ans, (tuple, list)) else ans
            if kind in (REDO, WORDS):
                if kind == WORDS and isinstance(ans, (tuple, list)) and len(ans) > 1 and str(ans[1]).strip():
                    add = str(ans[1]).strip()
                    entry[i]["prompt"] = f"{entry[i]['prompt']}, {add}"   # 足した言葉はこの先の工程にも効かせる
                    say(f"言葉を足しました: {add}")
                st.clear()
                st.update(entry[i])
                visits[i] += 1
                say(f"工程 {i + 1}/{n}「{name}」を描き直します")
                continue
        back = got.get("back")
        if left and back is not None and backs < BACKS and visits[back] < REVISIT:
            backs += 1
            visits[back] += 1
            say(f"「{name}」の崩れは工程 {back + 1}「{PHASES[back][0]}」で決まるので、そこへ戻って直します（{backs}/{BACKS} 回目）")
            st.clear()
            st.update(entry[back])
            i = back
            continue
        i += 1
    pausekeep.clear(pause_key)   # 描き終えたら、残した途中は要らない
    rows = [final[k] for k in range(n)]
    last = rows[-1]
    left = list(last["after"] if last["fixed"] else last["found"])
    ai = memo["thumbs"].get((st["prompt"], st["seed"]))
    if ai is not None and st.get("image") is not None and ai.size == st["image"].size and ai.tobytes() != st["image"].tobytes():
        # 精度優先の絵が、同じ頼み・同じ種の AI モードの絵（最初のサムネイル）より崩れが多ければ、AI モードの絵を使う
        def bad(im):
            r, b = checks.hands(im, st["prompt"]), checks.body(im, st["prompt"])
            return len(r.get("bad", [])) + (len(b.get("bad", [])) if b.get("readable") else 0)
        if bad(st["image"]) > bad(ai):
            say("仕上げ: AI モードの絵より崩れが多かったので、AI モードの絵を土台に使います")
            st["image"] = ai
            left = list(checks.hands(ai, st["prompt"]).get("bad", []))
    human = finish_human(st["image"], left)
    st["image"] = human["image"]
    checked = all(r["readable"] for r in rows)
    (keep / "phases.json").write_text(json.dumps({"phases": rows, "history": history, "left": left, "checked": checked, "backs": backs,
                                                  "stages": human.get("stages", []), "timelapse": human.get("timelapse"),
                                                  "clean": human.get("clean", {})},
                                                 ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return {"image": st["image"], "phases": rows, "history": history, "left": left, "checked": checked, "backs": backs,
            "stages": human.get("stages", []), "timelapse": human.get("timelapse"), "clean": human.get("clean", {})}
