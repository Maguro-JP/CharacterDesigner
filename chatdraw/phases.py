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
- 工程ごとに描いてよい所だけを囲みにして渡す（顔・手・足の直しは handcheck の枠、服と髪は部位分けの所で顔と手は除く、目の光は目の囲み）。
  囲みの外は変えない
- 模型で描かなくてもできる事（線の強弱、影の 2 段目、縮めて見る・反転して見る、光源の向き）は chatdraw/phasetools.py で処理する
- 模型に渡す言葉は、頼みを訳した言葉だけ（直しにも five fingers などを足さない）。利用者が工程の確かめで足した言葉は、その訳を足す。
  渡した言葉は「模型に渡す言葉:」の知らせにし、アプリは進み具合の欄の詳細（ツールチップ）にだけ置く
- 工程の始めには必ず「工程 i/n「名前」」の知らせを出す。アプリの進みの帯はこれで全体の進みを出す
- 前の工程の絵に描き重ねたら、前の絵の色と明るさに合わせる（phasetools.guard）。合わせても霞み・枠・色褪せが残れば前の絵を使う。
  下描きは線に沿って白紙から描き直す形より、描き重ね（Painter.refine）を先にする（線に沿う形では霞み・枠・服の変わりが出た）
- 確かめ（confirm）を渡すと、工程が終わるたびに呼び、「進める」「この工程を描き直す」「言葉を足して描き直す」を受ける
- 止める旗が立ったら、その工程の区切りで止まる
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
THUMB_SCALE = 0.5     # サムネイルの大きさ（描く大きさの割合）
THUMB_STEPS = 0.25    # サムネイルの描く工程の数の割合
ROUGH_STEPS = 0.5     # アタリの描く工程の数の割合
ATARI = 0.6           # アタリ: 選んだサムネイルを広げて描き重ねる強さ（構図と色を残す。0.75 では色が流れた）
LINE_STRENGTH = 0.6   # 下描き: アタリの線に沿う強さ（T2I-Adapter の効き。0.8 では霞みと枠が出た）
REFINE = 0.45         # 下描き: アタリの絵に描き重ねる強さ（色と明るさを残す）
REPAINT = 0.35        # 服・髪・持ち物: 描かれていない物を足すときの描き直しの強さ（形は残す）
FIX = 0.55            # 顔・手・足の直し: 崩れた枠の中だけを描き直す強さ
SHINE = 0.35          # 目の光の直し: 目の囲みの中だけを描き直す強さ
COLORS_MOST = 14      # 下塗り: 人物の 2% 以上を占める色がこれより多ければ、色が散っている（私の推測）
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
         confirm=None) -> dict:
    """12 の工程で 1 枚を描く。返り値は {"image": 最後の絵, "phases": 工程ごとの最後の記録, "history": 全部の記録,
    "left": 残った崩れ, "checked": 検品できたか, "backs": 戻った回数}。どの工程も必ず終わり、戻る回数にも上限がある。
    confirm(i, 名前, 絵, 記録) は "go"・"redo"・("words", 足す言葉の訳) を返す"""
    from PIL import Image
    from chatdraw.engine import Stopped, emphasize
    from chatdraw import handcheck, phasetools as pt
    keep.mkdir(parents=True, exist_ok=True)
    pv = {"on_preview": on_preview} if on_preview is not None else {}   # 描いている途中の絵を窓に渡す
    can_line, can_fix = abilities(painter)
    can_refine = hasattr(painter, "refine")
    checks = _Safe(checks)
    w, h = (size or (832, 1216))
    n = len(PHASES)
    st = {"image": None, "prompt": prompt, "thumb": None, "points": {}, "light": {}, "height": 0, "seed": seed}

    def tell(words):
        say(f"{WORDS_NOTE}{words}")

    tones = []

    def keep_tone(img, ref, where, mask=None):
        """描き重ねた絵を、前の工程の絵の色と明るさに合わせる（霞み・枠・色褪せを次の工程へ持ち越さない）"""
        if img is None or ref is None:
            return img
        try:
            out, rec = pt.guard(img, ref, mask)
        except Exception as e:   # noqa: BLE001  測れなかったら描いた絵のまま進める
            say(f"{where}: 色と明るさを合わせられませんでした（{e}）")
            return img
        rec["where"] = where
        tones.append(rec)
        if rec["raw_flaws"]:
            say(f"{where}: 描き重ねで " + "、".join(rec["raw_flaws"]) + (" ので、前の絵を使います" if rec["kept_ref"] else " のを、色合わせで直しました"))
        return out

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
        say(f"崩れた所を 1 回だけ直しています（{len(regions)} か所、囲みの中だけ）")
        tell(words)
        words_used.append(words)
        tried = painter.redraw(words, s, img, _mask(img.size, regions), strength=FIX)
        again = checks.hands(tried, st["prompt"])
        if again.get("readable") and len(again.get("bad", [])) <= len(res.get("bad", [])):
            return tried, again, True
        say("直しで崩れが減らなかったので、直す前の絵を次の工程に渡します")
        return img, res, True

    # ここから工程。どれも {"image", "found", "fixed", "after", "words", "numbers", "readable", "note", "back", "show"} を返す
    def p_purpose(v):
        tags = [t.strip() for t in st["prompt"].split(",") if t.strip()]
        found = [] if tags else ["頼みが空です"]
        return {"image": None, "found": found, "numbers": {"words": len(tags), "main": tags[0] if tags else ""}, "readable": True}

    def p_thumbs(v):
        tw, th = max(256, int(w * THUMB_SCALE) // 8 * 8), max(256, int(h * THUMB_SCALE) // 8 * 8)
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
                req = checks.request(img, st["prompt"])
                wt = pt.thumb_weight(img)
                flaws = _people(req) + _missing(req) + (["画面の重さが片寄っている"] if wt["weight_x"] > pt.WEIGHT_MOST else [])
                rows.append({"seed": s, **wt, "flaws": len(flaws)})
                score = (len(flaws), wt["weight_x"])
                if best is None or score < best[0]:
                    best = (score, img, s, flaws, req)
                del img
                gc.collect()
        finally:
            unsteps(s0)
        _score, img, s, flaws, req = best
        st["thumb"], st["seed_pick"] = img, s
        say(f"サムネイル {THUMBS} 枚のうち、種 {s} の構図を選びました（崩れ {len(flaws)}）")
        return {"image": img.resize((w, h)), "found": flaws, "numbers": {"thumbs": rows, "picked": s}, "words": words,
                "readable": bool(req.get("readable"))}

    def atari(s, words):
        s0 = steps(ROUGH_STEPS)
        try:
            tell(st["prompt"])
            words.append(st["prompt"])
            if st.get("thumb") is not None and can_refine:
                base = st["thumb"].resize((w, h))
                return keep_tone(painter.refine(st["prompt"], s, base, strength=ATARI, on_step=on_step, **pv), base, "アタリ")
            return painter.paint(st["prompt"], s, on_step=on_step, size=(w, h), **pv)
        finally:
            unsteps(s0)

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
        words = []
        s = st.get("seed_pick", st["seed"]) + v * 1000
        img = atari(s, words)
        found, nums, pts, bal, ok = atari_flaws(img)
        fixed, after = False, []
        if found:   # アタリの崩れは枠では直せないので、種を変えたアタリを 1 回だけ描き、崩れの少ない方を使う
            stop()
            say("アタリの崩れを直すため、種を変えたアタリを 1 回だけ描いています")
            st["thumb"] = None   # 種を変えたら、サムネイルに縛らずに描く
            again = atari(s + 1, words)
            after, nums2, pts2, bal2, ok2 = atari_flaws(again)
            fixed = True
            if len(after) < len(found):
                img, nums, pts, bal, ok = again, nums2, pts2, bal2, ok2
            else:
                after = found
        st["points"], st["height"] = pts, bal.get("height", 0)
        left = after if fixed else found
        people = [f for f in left if f.startswith("人数")]
        return {"image": img, "found": found, "fixed": fixed, "after": after, "words": words, "numbers": nums, "readable": ok,
                "back": 1 if people else None}

    def p_body(v):
        img = st["image"]
        pz, bd = checks.pose(img), checks.body(img, st["prompt"])
        found = (list(pz.get("bad", [])) if pz.get("readable") else []) + (list(bd.get("bad", [])) if bd.get("readable") else [])
        note = "" if pz.get("readable") else pz.get("reason", "骨組みを読めませんでした")
        return {"image": img, "show": pz.get("map"), "found": found, "numbers": {"points": pz.get("points")}, "note": note,
                "readable": bool(pz.get("readable")) and bool(bd.get("readable")), "back": 2}

    def p_draft(v):
        img, words, note = st["image"], [], ""
        s = st["seed"] + v * 1000
        base = img
        if can_refine:   # 描き重ね（絵から絵）を先にする。線に沿って白紙から描き直すと、霞み・枠・色褪せと服の変わりが出た
            say("アタリの絵に描き重ねて、顔・手・足を描き込んでいます")
            tell(st["prompt"])
            words.append(st["prompt"])
            img = keep_tone(painter.refine(st["prompt"], s, img, strength=REFINE, on_step=on_step, **pv), base, "下描き")
        elif can_line:
            say("アタリの線に沿って、顔・手・足を描き込んでいます")
            tell(st["prompt"])
            words.append(st["prompt"])
            img = keep_tone(painter.paint(st["prompt"], s, on_step=on_step, base=img, strength=LINE_STRENGTH, size=(w, h), **pv), base, "下描き")
        else:
            note = "この模型は描き重ねられないので、アタリの絵のまま顔・手・足を検品しました"
        res = checks.hands(img, st["prompt"])
        pts = points(img)
        tilt = pt.eye_tilt(pts)
        found = list(res.get("bad", [])) + ([f"左右の目の高さがずれている（{tilt}）"] if tilt is not None and tilt > pt.EYE_TILT else [])
        extra = []
        if tilt is not None and tilt > pt.EYE_TILT and pt.face_box(pts):
            extra = [(pt.face_box(pts), "face")]
        img, res2, fixed = fix_regions(img, res, s + 77, words, extra)
        pts2 = points(img) if fixed else pts
        tilt2 = pt.eye_tilt(pts2)
        after = list(res2.get("bad", [])) + ([f"左右の目の高さがずれている（{tilt2}）"] if tilt2 is not None and tilt2 > pt.EYE_TILT else [])
        st["points"] = pts2
        return {"image": img, "found": found, "fixed": fixed, "after": after, "words": words, "note": note,
                "numbers": {"eye_tilt": tilt2, "bad": len(res2.get("bad", []))}, "readable": bool(res.get("readable")), "back": 4}

    def p_wear(v):
        img, words, note = st["image"], [], ""
        req = checks.request(img, st["prompt"])
        found = _missing(req) + _extra(req)
        fixed, after = False, []
        missing = list(req.get("missing", [])) if req.get("readable") else []
        nums = {"missing": len(missing), "extra": len(_extra(req))}
        if missing and (can_fix or can_refine):
            stop()
            words2 = emphasize(st["prompt"], missing)
            say(f"描かれていない物（{'、'.join(missing)}）を、服・髪・持ち物の所だけに 1 回描き足しています")
            tell(words2)
            words.append(words2)
            pts = st.get("points") or {}
            protect = [b for b in [pt.face_box(pts)] if b]
            if can_fix:
                mask, by_parts = pt.wear_mask(img, protect)
                nums["by_parts"] = by_parts
                tried = keep_tone(painter.redraw(words2, st["seed"] + 131 + v * 1000, img, mask, strength=REPAINT), img, "服・髪・持ち物", mask)
            else:
                tried = keep_tone(painter.refine(words2, st["seed"] + 131 + v * 1000, img, strength=REPAINT, **pv), img, "服・髪・持ち物")
            req2 = checks.request(tried, st["prompt"])
            after = _missing(req2) + _extra(req2)
            fixed = True
            if len(after) <= len(found):
                img = tried
            else:
                after = found
                say("描き足しで崩れが増えたので、前の絵を次の工程に渡します")
        elif missing:
            note = "この模型は描き直しができないので、描かれていない物を直さずに次へ進みました"
        return {"image": img, "found": found, "fixed": fixed, "after": after, "words": words, "note": note, "numbers": nums,
                "readable": bool(req.get("readable"))}

    def p_lines(v):
        img = st["image"]
        before = pt.lines(img)
        found = [f"外の輪郭が途切れている（{before['gap']}）"] if before.get("readable") and before["gap"] > pt.LINE_GAP_MOST else []
        say("線の強弱を付けています（外の輪郭を濃く、内側の線はそのまま）")
        out, hit = pt.weight_lines(img)
        after_m = pt.lines(out)
        after = [f"外の輪郭が途切れている（{after_m['gap']}）"] if after_m.get("readable") and after_m["gap"] > pt.LINE_GAP_MOST else []
        return {"image": out, "found": found, "fixed": True, "after": after, "readable": bool(before.get("readable")),
                "numbers": {"before": before, "after": after_m, "pixels": hit}}

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
        say("影の 2 段目を、光源と反対の側の暗い所だけに置いています")
        out, hit = pt.shade_second(img, lit, keep_m)
        sh2 = pt.shadows(out, lit)
        return {"image": out, "found": found, "fixed": bool(hit), "after": flaws(sh2), "readable": bool(sh.get("readable")),
                "numbers": {"before": sh, "after": sh2, "pixels": hit}}

    def p_shine(v):
        img, words, note = st["image"], [], ""
        pts = st.get("points") or {}
        cl = pt.catchlights(img, pts)
        found = [f"目の光が無い（{x}）" for x in cl.get("eye_max", []) if x < pt.CATCHLIGHT]
        fixed, after = False, []
        if found and can_fix:
            say("目の囲みの中だけを、1 回だけ描き直しています（目の光）")
            tell(st["prompt"])
            words.append(st["prompt"])
            tried = painter.redraw(st["prompt"], st["seed"] + 251 + v * 1000, img,
                                   _mask(img.size, [(b, "eye") for b in cl["boxes"]]), strength=SHINE)
            cl2 = pt.catchlights(tried, pts)
            after = [f"目の光が無い（{x}）" for x in cl2.get("eye_max", []) if x < pt.CATCHLIGHT]
            fixed = True
            if len(after) <= len(found):
                img, cl = tried, cl2
            else:
                after = found
        elif found:
            note = "この模型は囲みの中だけを直せないので、目の光を足さずに次へ進みました"
        return {"image": img, "found": found, "fixed": fixed, "after": after, "words": words, "note": note,
                "numbers": {"eye_max": cl.get("eye_max")}, "readable": bool(cl.get("readable"))}

    def p_finish(v):
        img, words = st["image"], []
        res = checks.hands(img, st["prompt"])
        body = checks.body(img, st["prompt"])
        pts = points(img) or st.get("points") or {}

        def views(im):
            sv, fv = pt.shrink_view(im), pt.flip_view(im, pt.face_box(pts))
            out = []
            if sv.get("readable") and sv["contrast"] < pt.SHRINK_CONTRAST:
                out.append(f"縮めると主役が目立たない（{sv['contrast']}）")
            if fv.get("readable") and fv["asym"] > pt.FLIP_MOST:
                out.append(f"反転すると顔が片側に歪んで見える（{fv['asym']}）")
            return out, {"shrink": sv.get("contrast"), "asym": fv.get("asym")}
        body_bad = list(body.get("bad", [])) if body.get("readable") else []
        v1, nums = views(img)
        found = list(res.get("bad", [])) + body_bad + v1
        img, res2, fixed = fix_regions(img, res, st["seed"] + 191 + v * 1000, words)
        v2, nums2 = views(img) if fixed else (v1, nums)
        after = list(res2.get("bad", [])) + body_bad + v2
        left = after if fixed else found
        hands_left = bool(res2.get("bad"))
        return {"image": img, "found": found, "fixed": fixed, "after": after, "words": words, "numbers": nums2,
                "readable": bool(res.get("readable")) and bool(body.get("readable")), "back": 4 if hands_left and left else None}

    run = [p_purpose, p_thumbs, p_atari, p_body, p_draft, p_wear, p_lines, p_base, p_light, p_shadow, p_shine, p_finish]
    assert len(run) == n
    final: dict[int, dict] = {}
    history: list[dict] = []
    visits, entry = [0] * n, {}
    backs, i = 0, 0
    while i < n:
        stop()
        name = PHASES[i][0]
        entry.setdefault(i, None)
        entry[i] = dict(st)   # 戻るときは、この工程に入ったときの土台から描き直す
        say(f"工程 {i + 1}/{n}「{name}」: {PHASES[i][1]}（見る物: {PHASES[i][2]}）")
        t0 = time.time()
        got = run[i](visits[i])
        if got.get("image") is not None:
            st["image"] = got["image"]
        found, fixed = list(got.get("found", [])), bool(got.get("fixed"))
        after = list(got.get("after", [])) if fixed else []
        left = after if fixed else found
        shown = got.get("show") or got.get("image")
        path = None
        if shown is not None:
            path = keep / f"{i + 1:02d}-{name}.png"   # 順の分かる名前（タイムラプスがこの順につなぐ）
            shown.save(path)
            if on_preview is not None:   # 工程ごとの絵をすぐキャンバスに出す（描いている所を見せる）
                try:
                    on_preview(shown)
                except Exception:   # noqa: BLE001  見せるだけ。描く流れは止めない
                    pass
        mem = release()
        for t in tones:
            t.setdefault("phase", name)
        row = {"phase": name, "decides": PHASES[i][1], "checks": PHASES[i][2], "numbers_of": PHASES[i][3],
               "image": str(path) if path else None, "found": found, "fixed": fixed, "after": after,
               "words": list(got.get("words", [])), "numbers": got.get("numbers", {}), "readable": bool(got.get("readable", True)),
               "seconds": round(time.time() - t0, 2), "mem_mb": mem, "visit": visits[i],
               "tone": pt.tone(st["image"]) if st.get("image") is not None else None,
               "tone_guard": [t for t in tones if t.get("phase") == name]}
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
    rows = [final[k] for k in range(n)]
    last = rows[-1]
    left = last["after"] if last["fixed"] else last["found"]
    checked = all(r["readable"] for r in rows)
    (keep / "phases.json").write_text(json.dumps({"phases": rows, "history": history, "left": left, "checked": checked, "backs": backs},
                                                 ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return {"image": st["image"], "phases": rows, "history": history, "left": left, "checked": checked, "backs": backs}
