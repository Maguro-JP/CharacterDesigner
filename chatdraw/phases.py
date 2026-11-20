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
- 同じ物を 2 度描かない。選んだサムネイルはそのままアタリにし、手・足・顔の崩れで下描きへ戻ったときは絵全体を描き重ね直さず、
  前の下描きの崩れた枠の中だけを、直しを重ねるたびに強くして直す（FIXES）
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
THUMB_SCALE = 1.0     # サムネイルの大きさ（描く大きさの割合）。同じ種・同じ大きさならアタリが同じ構図になるので縮めない
THUMB_STEPS = 1.0     # サムネイルの描く工程の数の割合。選んだサムネイルをそのままアタリにする（半分の工程で描いてから同じ種でアタリを
                      # 描き直すと、同じ構図を 2 度描いて 214 秒かかり、描き直した絵は別の色になった。0.25 ではぼやけた絵になった）
LINE_STRENGTH = 0.6   # 下描き: アタリの線に沿う強さ（T2I-Adapter の効き。0.8 では霞みと枠が出た）
REFINE = 0.45         # 下描き: アタリの絵に描き重ねる強さ（色と明るさを残す）
REPAINT = 0.35        # 服・髪・持ち物: 描かれていない物を足すときの描き直しの強さ（形は残す）
FIX = 0.55            # 顔・手・足の直し: 崩れた枠の中だけを描き直す強さ（1 回目）
FIXES = (0.55, 0.7, 0.85, 0.95)   # 直しを重ねるたびに強くする。同じ強さで戻って直すと崩れた指の形をなぞり、下描きから最後まで同じ崩れが残った
SHINE = 0.35          # 目の光の直し: 目の囲みの中だけを描き直す強さ
COLORS_MOST = 14      # 下塗り: 人物の 2% 以上を占める色がこれより多ければ、色が散っている（私の推測）
BACKS = 3             # 戻って直すのは全体でこの回数まで
REVISIT = 2           # 同じ工程に戻るのはこの回数まで
# 検品で欠陥が見つかったのに工程側が戻り先を返さなかった場合の既定経路。
# index は 0 始まり。検品不能（readable=False）は原因不明なので自動で描き直さず停止する。
BACK_TARGETS = (None, 1, 1, 2, 3, 5, 4, 5, 7, 8, 4, 3)
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
         confirm=None, pause_key: str | None = None, pause_job: dict | None = None, on_event=None, on_snapshot=None) -> dict:
    """12 の工程で 1 枚を描く。返り値は {"image": 最後の絵, "phases": 工程ごとの最後の記録, "history": 全部の記録,
    "left": 残った崩れ, "checked": 全工程の検品完了, "complete": 全工程完了, "blocked": 停止理由, "backs": 戻った回数}。
    検品不能または未解決の崩れが残り、戻り先も無い場合は次工程へ進まず未完成で止める。戻る回数にも上限がある。
    confirm(i, 名前, 絵, 記録) は "go"・"redo"・("words", 足す言葉の訳) を返す。
    pause_key があれば、メモリの見張り・メモリ不足・時間切れで工程が打ち切られたとき、その工程に入ったときの状態を
    chatdraw/pausekeep.py に残して Paused で返す。同じ鍵で呼び直すと、その工程から続ける（前は始めから描き直した）"""
    from PIL import Image
    from chatdraw.engine import Stopped, emphasize
    from chatdraw import handcheck, phasetools as pt
    from chatdraw.events import emit_event
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
    memo = {"thumbs": {}, "fix_n": 0, "draft": None, "refix": False}   # 描いた絵を使い回す（同じ種・同じ言葉の絵は 2 度描かない）

    def keep_tone(img, ref, where, mask=None):
        """描き重ねた絵を、前の工程の絵の色と明るさに合わせる（霞み・枠・色褪せを次の工程へ持ち越さない）"""
        if img is None or ref is None:
            return img
        try:
            out, rec = pt.guard(img, ref, mask)
        except Exception as e:   # noqa: BLE001  色・明るさの保全を検証できない候補は採用しない
            say(f"{where}: 色と明るさを検証できなかったため、修正前の絵に戻します（{type(e).__name__}: {e}）")
            return ref
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
        k = memo["fix_n"]
        memo["fix_n"] += 1
        strength = FIXES[min(k, len(FIXES) - 1)]
        message = f"崩れた所を {len(regions)} か所、囲みの中だけ描き直しています（強さ {strength}）"
        say("修正中: " + message)
        emit_event(on_event, "correction", message, phase="顔・手・足の下描き", regions=len(regions), strength=strength)
        # 修正前の画像を先に表示する。修正処理中に画面が止まって見えないようにする。
        snapshot = on_snapshot or on_preview
        if snapshot is not None:
            try:
                snapshot(img)
            except Exception:
                pass
        tell(words)
        words_used.append(words)
        tried = painter.redraw(words, s + 13 * k, img, _mask(img.size, regions), strength=strength,
                               **({"on_preview": on_preview} if on_preview is not None else {}))
        # 修正後の実画像を直ちに表示し、その同じ画像を再検品する。
        if snapshot is not None:
            try:
                snapshot(tried)
            except Exception:
                pass
        say("修正結果を再検品しています（手・足・顔）")
        emit_event(on_event, "reinspection", "修正結果を再検品しています（手・足・顔）", phase="顔・手・足の下描き")
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

    def atari(s, words):
        got = memo["thumbs"].get((st["prompt"], s))
        if got is not None:   # 同じ種・同じ大きさ・同じ工程の数で描いたサムネイルがあれば、それがそのままアタリ（描き直さない）
            say(f"サムネイル（種 {s}）をそのままアタリにします")
            return got
        s0 = steps(1.0)
        try:
            tell(st["prompt"])
            words.append(st["prompt"])
            # 選んだサムネイルの種で、同じ大きさのまま工程の数を戻して描く（構図は同じになる）。ぼやけたサムネイルに描き重ねると、
            # ぼやけと霞みが最後の工程まで残った（phase-bench、Animagine XL 4.0）
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
        s = st.get("seed_pick", st["seed"]) + (v * 1000 if v else 0)
        img = atari(s, words)
        found, nums, pts, bal, ok = atari_flaws(img)
        fixed, after = False, []
        if found:   # アタリの崩れは枠では直せないので、種を変えたアタリを 1 回だけ描き、崩れの少ない方を使う
            stop()
            say("アタリの崩れを直すため、種を変えたアタリを 1 回だけ描いています")
            st["thumb"] = None   # 種を変えたら、サムネイルに縛らずに描く
            nxt = [x for x in st.get("seed_next") or [] if (st["prompt"], x) in memo["thumbs"]]
            again = atari(nxt[0] if nxt and not v else s + 1, words)   # 次に良かったサムネイルがあれば、描かずに使う
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
        prev = memo["draft"]
        refix = memo["refix"] and prev is not None and prev[0] == st["prompt"] and can_fix
        memo["refix"] = False
        if refix:
            # 手・足・顔の崩れで戻ったときは、絵全体を描き重ね直さない。前の下描きを土台に、崩れた枠の中だけを強くして直す
            # （描き重ね直すたびに絵全体が変わって色が褪せ、崩れた指は同じ形のまま残った）
            img = prev[1]
            say("前の下描きを土台に、崩れた手・足・顔の枠の中だけを直し直します")
        elif can_refine:   # 描き重ね（絵から絵）を先にする。線に沿って白紙から描き直すと、霞み・枠・色褪せと服の変わりが出た
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
        point_check = checks.points(img)
        pts = dict(point_check.get("points") or {}) if point_check.get("readable") else {}
        tilt = pt.eye_tilt(pts)
        found = list(res.get("bad", [])) + ([f"左右の目の高さがずれている（{tilt}）"] if tilt is not None and tilt > pt.EYE_TILT else [])
        extra = []
        if tilt is not None and tilt > pt.EYE_TILT and pt.face_box(pts):
            extra = [(pt.face_box(pts), "face")]
        img, res2, fixed = fix_regions(img, res, s + 77, words, extra)
        point_check2 = checks.points(img) if fixed else point_check
        pts2 = dict(point_check2.get("points") or {}) if point_check2.get("readable") else {}
        tilt2 = pt.eye_tilt(pts2)
        after = list(res2.get("bad", [])) + ([f"左右の目の高さがずれている（{tilt2}）"] if tilt2 is not None and tilt2 > pt.EYE_TILT else [])
        st["points"] = pts2
        memo["draft"] = (st["prompt"], img)
        return {"image": img, "found": found, "fixed": fixed, "after": after, "words": words, "note": note,
                "numbers": {"eye_tilt": tilt2, "bad": len(res2.get("bad", []))},
                "readable": bool(res.get("readable")) and bool(point_check.get("readable")) and (not fixed or bool(point_check2.get("readable"))),
                "back": 4}

    def p_wear(v):
        img, words, note = st["image"], [], ""
        req = checks.request(img, st["prompt"])
        found = _missing(req) + _extra(req)
        fixed, after = False, []
        recheck_readable = True
        missing = list(req.get("missing", [])) if req.get("readable") else []
        nums = {"missing": len(missing), "extra": len(_extra(req))}
        # 利用者が工程確認で言葉を追加した場合、検品が一旦合格でもその指示を描画へ反映する。
        added_words = st["prompt"] != prompt
        if (missing or added_words) and (can_fix or can_refine):
            stop()
            words2 = emphasize(st["prompt"], missing) if missing else st["prompt"]
            message = f"描かれていない物（{'、'.join(missing)}）を、服・髪・持ち物の範囲だけに描き足しています"
            say("修正中: " + message)
            emit_event(on_event, "correction", message, phase="服・髪・持ち物", missing=list(missing))
            snapshot = on_snapshot or on_preview
            if snapshot is not None:
                try:
                    snapshot(img)
                except Exception:
                    pass
            tell(words2)
            words.append(words2)
            pts = st.get("points") or {}
            protect = [b for b in [pt.face_box(pts)] if b]
            if can_fix:
                mask, by_parts = pt.wear_mask(img, protect)
                nums["by_parts"] = by_parts
                tried = keep_tone(painter.redraw(words2, st["seed"] + 131 + v * 1000, img, mask, strength=REPAINT,
                                                     **({"on_preview": on_preview} if on_preview is not None else {})),
                                      img, "服・髪・持ち物", mask)
            else:
                tried = keep_tone(painter.refine(words2, st["seed"] + 131 + v * 1000, img, strength=REPAINT, **pv), img, "服・髪・持ち物")
            if snapshot is not None:
                try:
                    snapshot(tried)
                except Exception:
                    pass
            say("描き足しの結果を再検品しています")
            emit_event(on_event, "reinspection", "描き足しの結果を再検品しています", phase="服・髪・持ち物")
            req2 = checks.request(tried, st["prompt"])
            fixed = True
            if req2.get("readable") and len(_missing(req2) + _extra(req2)) <= len(found):
                after = _missing(req2) + _extra(req2)
                img = tried
            elif req2.get("readable"):
                after = found
                say("描き足しで崩れが増えたので、前の絵を次の工程に渡します")
            else:
                after = found
                recheck_readable = False
                note = "描き足し後の検品ができなかったため、修正前の絵に戻します"
        elif missing:
            note = "この模型は描き直しができないので、描かれていない物を直さずに次へ進みました"
        if added_words and not (can_fix or can_refine):
            found.append("追加指示を反映できません（この模型は描き直し不可）")
            note = "追加指示を描画へ反映できないため、未完成として扱います"
        return {"image": img, "found": found, "fixed": fixed, "after": after, "words": words, "note": note, "numbers": nums,
                "readable": bool(req.get("readable")) and recheck_readable, "back": 5 if (after if fixed else found) else None}

    def p_lines(v):
        img = st["image"]
        before = pt.lines(img)
        found = [f"外の輪郭が途切れている（{before['gap']}）"] if before.get("readable") and before["gap"] > pt.LINE_GAP_MOST else []
        say("線の強弱を付けています（外の輪郭を濃く、内側の線はそのまま）")
        out, hit = pt.weight_lines(img)
        after_m = pt.lines(out)
        after = [f"外の輪郭が途切れている（{after_m['gap']}）"] if after_m.get("readable") and after_m["gap"] > pt.LINE_GAP_MOST else []
        return {"image": out, "found": found, "fixed": True, "after": after, "readable": bool(before.get("readable")) and bool(after_m.get("readable")),
                "numbers": {"before": before, "after": after_m, "pixels": hit}, "back": 4 if after else None}

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
        return {"image": img, "found": found, "numbers": nums, "readable": True, "back": 5 if found else None}

    def p_light(v):
        lit = pt.light(st["image"])
        st["light"] = lit
        flat = lit.get("readable") and abs(lit["dx"]) < 2 and abs(lit["dy"]) < 2
        if lit.get("readable"):
            say(f"光源を{lit['side']}{'上' if lit['dy'] < 0 else '下'}に決めました")
        return {"image": st["image"], "found": ["光の向きが決まらない（明るさが平たい）"] if flat else [], "numbers": lit,
                "readable": bool(lit.get("readable")), "back": 5 if flat else None}

    def p_shadow(v):
        img, lit = st["image"], st.get("light") or {}
        sh = pt.shadows(img, lit)

        def flaws(s):
            out = []
            if s.get("readable") and s["shade_minus_lit"] > 0:
                out.append(f"影が光より明るい（{s['shade_minus_lit']}）")
            # 暗い画素の左右比率は線画・髪・服の色にも左右されるため合否に使わない。
            # 影側が光側より明るいか、方向の比較だけを品質判定に使う。
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
        return {"image": out, "found": found, "fixed": bool(hit), "after": flaws(sh2), "readable": bool(sh.get("readable")) and bool(sh2.get("readable")),
                "numbers": {"before": sh, "after": sh2, "pixels": hit}, "back": 5 if flaws(sh2) else None}

    def p_shine(v):
        img, words, note = st["image"], [], ""
        pts = points(img)   # 目の光は直近の画像から検出した座標だけで検品する。
        cl = pt.catchlights(img, pts)
        found = [f"目の光が無い（{x}）" for x in cl.get("eye_max", []) if x < pt.CATCHLIGHT]
        fixed, after = False, []
        if found and can_fix:
            say("目の囲みの中だけを、1 回だけ描き直しています（目の光）")
            tell(st["prompt"])
            words.append(st["prompt"])
            tried = painter.redraw(st["prompt"], st["seed"] + 251 + v * 1000, img,
                                   _mask(img.size, [(b, "eye") for b in cl["boxes"]]), strength=SHINE)
            pts2 = points(tried)  # 描き直し後の座標を取り直し、古い目の位置で合格にしない
            cl2 = pt.catchlights(tried, pts2)
            after = [f"目の光が無い（{x}）" for x in cl2.get("eye_max", []) if x < pt.CATCHLIGHT]
            fixed = True
            if len(after) <= len(found):
                img, cl = tried, cl2
            else:
                after = found
        elif found:
            note = "この模型は囲みの中だけを直せないので、目の光を足さずに次へ進みました"
        return {"image": img, "found": found, "fixed": fixed, "after": after, "words": words, "note": note,
                "numbers": {"eye_max": cl.get("eye_max")},
                "readable": bool(cl.get("readable")) and (not fixed or bool(cl2.get("readable"))),
                "back": 4 if (after if fixed else found) else None}

    def p_finish(v):
        img, words = st["image"], []
        res = checks.hands(img, st["prompt"])
        body = checks.body(img, st["prompt"])
        pts = points(img)

        def views(im, landmarks):
            sv = pt.shrink_view(im)
            face = pt.face_box(landmarks)
            fv = pt.flip_view(im, face) if face else {"readable": False}
            out = []
            if sv.get("readable") and sv["contrast"] < pt.SHRINK_CONTRAST:
                out.append(f"縮めると主役が目立たない（{sv['contrast']}）")
            if fv.get("readable") and fv["asym"] > pt.FLIP_MOST:
                out.append(f"反転すると顔が片側に歪んで見える（{fv['asym']}）")
            return out, {"shrink": sv.get("contrast"), "asym": fv.get("asym")}, bool(sv.get("readable")) and bool(fv.get("readable"))

        body_bad = list(body.get("bad", [])) if body.get("readable") else []
        v1, nums, view_readable = views(img, pts)
        found = list(res.get("bad", [])) + body_bad + v1
        img, _res_after_fix, fixed = fix_regions(img, res, st["seed"] + 191 + v * 1000, words)

        # 修正後は採用した最終画像そのものを、手・体・ランドマーク・縮小・反転で再検品する。
        pts_final = points(img) if fixed else pts
        res_final = checks.hands(img, st["prompt"]) if fixed else res
        body_final = checks.body(img, st["prompt"]) if fixed else body
        v2, nums2, final_view_readable = views(img, pts_final) if fixed else (v1, nums, view_readable)
        body_bad_final = list(body_final.get("bad", [])) if body_final.get("readable") else []
        after = list(res_final.get("bad", [])) + body_bad_final + v2
        hands_left = bool(res_final.get("bad"))
        body_left = bool(body_bad_final)
        return {"image": img, "found": found, "fixed": fixed, "after": after, "words": words, "numbers": nums2,
                "readable": bool(res.get("readable")) and bool(body.get("readable")) and bool(res_final.get("readable")) and bool(body_final.get("readable")) and bool(pts_final) and final_view_readable,
                "back": (4 if hands_left and after else 3 if body_left else None)}

    run = [p_purpose, p_thumbs, p_atari, p_body, p_draft, p_wear, p_lines, p_base, p_light, p_shadow, p_shine, p_finish]
    assert len(run) == n
    final: dict[int, dict] = {}
    history: list[dict] = []
    visits, entry = [0] * n, {}
    backs, i = 0, 0
    blocked = None
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
        emit_event(on_event, "phase_started", PHASES[i][1], phase=name, index=i + 1, total=n, checks=PHASES[i][2])
        tones.clear()   # 色合わせの記録はこの回の分だけを残す（前は戻るたびに前の回の分が重なった）
        t0 = time.time()
        try:
            emit_event(on_event, "drawing", f"工程 {i + 1}/{n}「{name}」を処理しています", phase=name, index=i + 1, total=n)
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
               "words": list(got.get("words", [])), "numbers": got.get("numbers", {}), "readable": bool(got.get("readable", False)),
               "seconds": round(time.time() - t0, 2), "mem_mb": mem, "visit": visits[i],
               "tone": pt.tone(st["image"]) if st.get("image") is not None else None,
               "tone_guard": [t for t in tones if t.get("phase") == name]}
        if got.get("note"):
            row["note"] = got["note"]
        final[i] = row
        history.append(row)
        inspection_message = "崩れは見つかりませんでした" if not left else "残った崩れ " + "、".join(left[:4])
        say(f"工程 {i + 1}/{n}「{name}」の検品: " + inspection_message)
        emit_event(on_event, "inspection", inspection_message, phase=name, index=i + 1, total=n,
                   readable=row["readable"], found=found, fixed=fixed, after=after)
        if not left and row["readable"]:
            emit_event(on_event, "phase_completed", f"工程 {i + 1}/{n}「{name}」が完了しました", phase=name, index=i + 1, total=n)
        if confirm is not None:
            ans = confirm(i, name, shown, row)
            kind = ans[0] if isinstance(ans, (tuple, list)) else ans
            if kind in (REDO, WORDS):
                target_hint = 5 if kind == WORDS and isinstance(ans, (tuple, list)) and len(ans) > 1 and str(ans[1]).strip() and i >= 5 else i
                if backs >= BACKS or visits[target_hint] >= REVISIT:
                    blocked = {"phase": name, "index": i, "reason": "再試行上限に達しました", "left": list(left), "requested": kind}
                    say(f"工程 {i + 1}/{n}「{name}」は再試行上限（全体 {BACKS} 回・同一工程 {REVISIT} 回）に達したため停止しました。未完成として保存します")
                    break
                backs += 1
                added = False
                if kind == WORDS and isinstance(ans, (tuple, list)) and len(ans) > 1 and str(ans[1]).strip():
                    add = str(ans[1]).strip()
                    entry[i]["prompt"] = f"{entry[i]['prompt']}, {add}"   # 足した言葉は描画工程にも反映する
                    say(f"言葉を足しました: {add}")
                    added = True
                target = 5 if added and i >= 5 else i   # 服・髪・持ち物を描く工程より後で足した言葉は、そこまで戻して実際に描く
                if target != i:
                    entry[target] = dict(entry[target] or entry[i])
                    entry[target]["prompt"] = entry[i]["prompt"]
                st.clear()
                st.update(entry[target])
                visits[target] += 1
                if target != i:
                    say(f"追加した言葉を反映するため、工程 {target + 1}/{n}「{PHASES[target][0]}」へ戻ります")
                else:
                    say(f"工程 {i + 1}/{n}「{name}」を描き直します")
                i = target
                continue
        back = got.get("back")
        # 検品不能は欠陥の場所が分からないため、工程側が返した戻り先も使わず即時停止する。
        # readable=False の工程を推測で再描画しても、検品できない状態は解消したと証明できない。
        if not row["readable"]:
            back = None
        # 欠陥が残っているのに工程が戻り先を指定しない場合、品質工程の既定経路へ差し戻す。
        if left and back is None and row["readable"]:
            back = BACK_TARGETS[i]
            if back is not None:
                say(f"「{name}」の欠陥に戻り先指定が無いため、既定経路で工程 {back + 1}「{PHASES[back][0]}」へ差し戻します")
        needs_retry = bool(left) or not row["readable"]
        if needs_retry and back is not None and backs < BACKS and visits[back] < REVISIT:
            backs += 1
            visits[back] += 1
            memo["refix"] = back == 4 and bool(got.get("hands_left", True))
            say(f"「{name}」の未解決項目を工程 {back + 1}「{PHASES[back][0]}」へ戻して直します（{backs}/{BACKS} 回目）")
            st.clear()
            st.update(entry[back])
            i = back
            continue
        if needs_retry:
            reason = "検品できませんでした" if not row["readable"] else "未解決の崩れが残っています"
            blocked = {"phase": name, "index": i, "reason": reason, "left": list(left)}
            emit_event(on_event, "blocked", f"工程 {i + 1}/{n}「{name}」で停止: {reason}", phase=name, index=i + 1, total=n, unresolved=list(left))
            say(f"工程 {i + 1}/{n}「{name}」で停止しました（{reason}）。未完成として保存します")
            break
        i += 1
    pausekeep.clear(pause_key)   # 完了または未完成で停止したら、残した途中は要らない
    rows = [final[k] for k in range(n) if final.get(k) is not None]
    complete = i >= n
    if complete and rows:
        last = rows[-1]
        left = last["after"] if last["fixed"] else last["found"]
    checked = complete and bool(rows) and all(r["readable"] for r in rows)
    if not (complete and checked and not left):
        emit_event(on_event, "blocked", "未完了の工程があります",
                   index=len(rows), total=n, checked=checked, unresolved=list(left), complete=complete)
    (keep / "phases.json").write_text(json.dumps({"phases": rows, "history": history, "left": left, "checked": checked,
                                                  "complete": complete, "blocked": blocked, "backs": backs},
                                                 ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return {"image": st["image"], "phases": rows, "history": history, "left": left, "checked": checked,
            "complete": complete, "blocked": blocked, "backs": backs}
