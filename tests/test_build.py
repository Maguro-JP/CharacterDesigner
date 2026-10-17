"""tools/build.py の試験。

見た目の良し悪しは画像で判定する（library/progress/）。ここで固定するのは、
壊れたら気付きにくい所: 書き出しの再現性、細い部品が縮小で消えないこと、
孤立ドットの掃除、頭と体の実測。
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build  # noqa: E402

MATS = {"metal": {"outline": "#101010", "ramp": ["#404040", "#808080", "#c0c0c0"]},
        "skin": {"outline": "#301010", "ramp": ["#a06050", "#f0c0a0"]}}


def spec(parts, canvas=(12, 12), **kw):
    s = {"name": "t", "style": "diorama", "canvas": list(canvas), "materials": MATS, "parts": parts}
    s.update(kw)
    return s


class BuildTest(unittest.TestCase):
    def test_feet_are_not_cut_by_canvas_bottom(self):
        # 輪郭は形の外側に付けるので、靴が画面の最下行を越えると底の輪郭が切れ、足が平らな帯に見える。
        # 体の高さも短く数えられ、頭身の検査がそれで通ってしまう。最下行に来てよいのは暗い底の輪郭だけ
        for f in sorted(ROOT.glob("characters/*/sprite*.json")):
            with self.subTest(sprite=str(f.relative_to(ROOT))):
                d = json.loads(f.read_text(encoding="utf-8"))
                bottom = {d["palette"][ch] for ch in d["rows"][-1] if ch != "."}
                luma = lambda c: sum(int(c[i:i + 2], 16) for i in (1, 3, 5)) / 3  # noqa: E731
                self.assertEqual({c for c in bottom if luma(c) > 48}, set())

    def test_touchup_colors_survive_in_every_frame(self):
        # 目や眼鏡の光は全コマに残る。最初のコマだけ見ていて、右向きの呼吸で光が消えたのを見逃した
        for pp in sorted(ROOT.glob("characters/*/parts.json")):
            spec = build.load_spec(pp)
            want = {t["c"] for t in spec.get("touchups", []) if t["c"] and t["c"].startswith("#")}
            for f in sorted(pp.parent.glob("sprite*.json")):
                with self.subTest(sprite=str(f.relative_to(ROOT))):
                    d = json.loads(f.read_text(encoding="utf-8"))
                    cols = {d["palette"][ch] for row in d["rows"] for ch in row if ch != "."}
                    self.assertEqual(want - cols, set())

    def test_body_parts_match_generator(self):
        # characters/body-*/parts.json は tools/body.py の書き出し。手で直した食い違いを残さない
        sys.path.insert(0, str(ROOT / "tools"))
        import body
        for kind in body.TYPES:
            with self.subTest(kind=kind):
                path = ROOT / "characters" / f"body-{kind}" / "parts.json"
                r = subprocess.run([sys.executable, "tools/fmt.py", "--check", str(path)], cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stdout)
                committed = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(json.loads(json.dumps(body.spec_for(kind))), committed)

    def test_limb_tapers_from_first_joint_to_last(self):
        # 関節ごとの太さで描く手足。上（太腿）が下（足首）より太い
        from PIL import Image, ImageDraw
        im = Image.new("L", (20 * build.SS, 20 * build.SS), 0)
        build.draw_shape(ImageDraw.Draw(im), {"type": "limb", "points": [[10, 3], [10, 10], [10, 17]], "radii": [3, 2, 1]})
        width = lambda y: sum(1 for x in range(im.width) if im.getpixel((x, y * build.SS)) > 0)  # noqa: E731
        self.assertGreater(width(4), width(10))
        self.assertGreater(width(10), width(16))

    def test_flatten_crown_lowers_narrow_top(self):
        # 3ドット幅のこぶは1段下がり、広い頭頂や杖の先のような形はそのまま
        a = "#101010"
        nub = [[None] * 9 for _ in range(4)]
        for x in (3, 4, 5):
            nub[0][x] = a
        for y in (1, 2, 3):
            for x in range(1, 8):
                nub[y][x] = "#806040"
        self.assertEqual(build.flatten_crown(nub), 3)
        self.assertTrue(all(c is None for c in nub[0]))
        self.assertEqual(nub[1][4], a)
        wide = [[a] * 6 + [None] * 3, ["#806040"] * 9, ["#806040"] * 9]
        self.assertEqual(build.flatten_crown(wide), 0)

    def test_committed_sprites_are_reproducible(self):
        # sprite.json は parts.json から書き出したもの。手で直すと次の書き出しで消えるので、一致を見る
        for parts in ROOT.glob("characters/*/parts.json"):
            with self.subTest(parts=parts.parent.name):
                sp = build.load_spec(parts)
                for name, got in build.build_frames(sp).items():
                    want = json.loads(build.sprite_path(parts, name).read_text(encoding="utf-8"))
                    self.assertEqual(got, want, name or "基本")

    def test_committed_restyled_sprites_are_reproducible(self):
        # 別の作風の書き出し（<キャラ>/<作風>/sprite.json）も parts.json から同じものが出る
        for out in ROOT.glob("characters/*/*/sprite.json"):
            with self.subTest(sprite=str(out.relative_to(ROOT))):
                sp = build.restyle(build.load_spec(out.parent.parent / "parts.json"), out.parent.name)
                self.assertEqual(build.build(sp)[0], json.loads(out.read_text(encoding="utf-8")))

    def test_restyled_sprites_pass_their_style_check(self):
        for out in ROOT.glob("characters/*/*/sprite.json"):
            with self.subTest(sprite=str(out.relative_to(ROOT))):
                r = subprocess.run([sys.executable, "tools/check.py", str(out), f"styles/{out.parent.name}.json"],
                                   cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stdout)

    def test_thin_part_keeps_its_inside(self):
        # 2ドット幅の剣: 輪郭を外に足すので、中身の色が残る
        sp = spec([{"name": "blade", "material": "metal",
                    "shapes": [{"type": "rect", "at": [5, 2, 7, 10]}]}])
        out, _ = build.build(sp)
        pal = out["palette"]
        inside = {pal[c] for row in out["rows"][2:10] for c in row[5:7]}
        self.assertTrue(inside <= set(MATS["metal"]["ramp"]), inside)
        self.assertEqual({pal[r[4]] for r in out["rows"][2:10]}, {"#101010"})

    def test_outline_tint_varies_but_stays_dark(self):
        # outline_tint: 外の輪郭を内側の暗い2段へ寄せる。輪郭の色が縁に沿って変わるが、
        # 内側の2段目より明るくはならない（明るい段まで寄せるとシルエットが緩んだ）
        part = {"name": "blade", "material": "metal", "shapes": [{"type": "rect", "at": [3, 2, 9, 10]}]}
        plain, _ = build.build(spec([dict(part)]))
        tinted, _ = build.build(spec([dict(part)], texture={"outline_tint": 0.5}))
        edge = lambda o: {o["palette"][r[2]] for r in o["rows"][2:10]}  # noqa: E731
        luma = lambda c: sum(int(c[i:i + 2], 16) for i in (1, 3, 5)) / 3  # noqa: E731
        self.assertEqual(edge(plain), {"#101010"})
        self.assertNotEqual(edge(tinted), {"#101010"})
        self.assertTrue(all(luma(c) <= luma(MATS["metal"]["ramp"][1]) for c in edge(tinted)), edge(tinted))

    def test_band_of_follows_the_bottom_of_its_part(self):
        # 裾の縁取りは元の部品の下端の帯。元の部品が無ければ何も描かない
        cloth = {"name": "coat", "material": "metal", "shapes": [{"type": "rect", "at": [3, 2, 9, 8]}]}
        hem = {"name": "hem", "material": "skin", "shapes": [], "band_of": {"part": "coat", "width": 1.0}}
        out, _ = build.build(spec([cloth, hem]))
        pal = out["palette"]
        skin = set(MATS["skin"]["ramp"])
        rows_with_skin = [y for y, r in enumerate(out["rows"]) if any(c != "." and pal[c] in skin for c in r)]
        self.assertEqual(rows_with_skin, [7])
        alone, _ = build.build(spec([hem, {"name": "x", "material": "metal", "shapes": [{"type": "rect", "at": [3, 2, 9, 8]}]}]))
        self.assertFalse(any(c != "." and alone["palette"][c] in skin for r in alone["rows"] for c in r))

    def test_learned_stats_cover_every_feature(self):
        # 手本から学んだ数字と、自分のスプライトの特徴は同じ項目で数える。片方だけ足すと採点が黙って欠ける
        import learn
        stats = json.loads((ROOT / "styles" / "diorama.learned.json").read_text(encoding="utf-8"))
        f, z = learn.score_sprite(stats, ROOT / "characters" / "warrior" / "sprite.json")
        self.assertEqual(set(f), set(stats["features"]))
        self.assertGreater(stats["frames"], 100)

    def test_engine_light_is_matched_to_parts_levels(self):
        # Blender の光は明るく上が 1.0 に張り付く。部品から描くときの3点（下位10%・中央・上位10%）に写す
        sys.path.insert(0, str(ROOT / "tools" / "engine"))
        import topixel
        lum = [i / 99 * 0.6 + 0.4 for i in range(100)]  # 0.4〜1.0 に寄った明るさ
        top = [0] * 100
        out = sorted(topixel.match_levels(top, lum))
        self.assertAlmostEqual(out[10], topixel.TARGET[0], places=2)
        self.assertAlmostEqual(out[50], topixel.TARGET[1], places=2)
        self.assertAlmostEqual(out[90], topixel.TARGET[2], places=2)

    def test_finish_turns_a_hi_res_grid_into_a_sprite(self):
        # 部品の形を描かずに、(部品番号, 明るさ) の格子だけからドット絵にできる（Blender の絵を通す道）
        sp = spec([{"name": "body", "material": "metal", "shapes": []}], canvas=(6, 6))
        W, H = 6 * build.SS, 6 * build.SS
        top = [0 if build.SS <= x < 5 * build.SS and build.SS <= y < 5 * build.SS else -1
               for y in range(H) for x in range(W)]
        light = [0.6] * (W * H)
        out, _ = build.finish(sp, top, light, (W, H))
        # 4x4 の中身 16 と、上下左右に付く輪郭 16（角には付かない）
        self.assertEqual(sum(c != "." for r in out["rows"] for c in r), 32)

    def test_generated_picture_becomes_a_sprite_without_background(self):
        # 生成した絵（無地の背景、本人と小さな写り込み）から、本人だけのドット絵を作る
        import tempfile
        from PIL import Image, ImageDraw
        sys.path.insert(0, str(ROOT / "tools" / "gen"))
        import design
        im = Image.new("RGB", (100, 200), (250, 250, 250))
        d = ImageDraw.Draw(im)
        d.rectangle([30, 20, 70, 190], fill=(40, 60, 160))   # 本人
        d.rectangle([2, 2, 12, 22], fill=(160, 60, 40))      # 隅の小さな写り込み
        with tempfile.TemporaryDirectory() as t:
            src, out = f"{t}/a.png", f"{t}/a.sprite.json"
            im.save(src)
            design.pixel(src, out, 34, 16)
            sp = json.loads(Path(out).read_text(encoding="utf-8"))
        cols = {sp["palette"][c] for r in sp["rows"] for c in r if c != "."}
        self.assertEqual(len(sp["rows"]), 36)  # 34 ドットの本人と上下の輪郭
        self.assertFalse(any(build.hex_to_rgb(c)[0] > 120 and build.hex_to_rgb(c)[2] < 80 for c in cols), cols)

    def test_cast_sheet_lists_drawn_pictures_per_character(self):
        # 設定集の一覧図: 描いた人だけが1人1行で並び、全員の指示文の後ろに共通の世界観が付く
        import tempfile
        from PIL import Image
        sys.path.insert(0, str(ROOT / "tools" / "gen"))
        import design
        cast = {"common": "dark fantasy", "n": 2,
                "characters": [{"id": "a", "name": "剣士", "role": "前衛", "prompt": "swordsman"},
                               {"id": "b", "name": "未描画", "prompt": "mage"}]}
        with tempfile.TemporaryDirectory() as t:
            Path(f"{t}/c.json").write_text(json.dumps(cast, ensure_ascii=False), encoding="utf-8")
            for s in (7, 8):
                Image.new("RGB", (64, 96), (200, 0, 0)).save(f"{t}/a-{s}.png")
            design.sheet(f"{t}/c.json", t, f"{t}/s.png", thumb=64)
            im = Image.open(f"{t}/s.png")
            self.assertEqual(im.size, (220 + 2 * 64, 96))  # 1行（未描画の人は出ない）、絵は2枚
            self.assertEqual(design.load_cast(f"{t}/c.json")["characters"][0]["full_prompt"],
                             "swordsman, dark fantasy")

    def test_creatures_are_drawn_in_both_styles_without_human_prefix(self):
        # モンスターは人の立ち姿の決まり文句を使わず、SDXL 系で描く。人は性別の指定が頭に付く
        sys.path.insert(0, str(ROOT / "tools" / "gen"))
        import design
        cast = {"n": 2, "characters": [{"id": "m", "kind": "creature", "prompt": "a turtle", "full_prompt": "a turtle"},
                                       {"id": "h", "gender": "male", "prompt": "a knight", "full_prompt": "a knight"}]}
        shots = {c["id"]: [(p.name, st) for p, _, st in s] for c, s in design.cast_paths(cast, "/x")}
        self.assertEqual(shots["m"], [("m-xl-7.png", "xl"), ("m-xl-8.png", "xl")])
        self.assertEqual(shots["h"], [("h-7.png", "anime"), ("h-8.png", "anime")])
        for st in ("anime", "xl"):
            text, neg = design.full_texts(cast["characters"][0], st)
            self.assertNotIn("standing", text)
            self.assertIn("1girl", neg)
        self.assertTrue(design.full_texts(cast["characters"][1])[0].startswith(design.PREFIX + "1boy"))
        # 利用者が要らないと決めた絵（rejected）は数に入れず、次の seed で描き足す
        cast["characters"][0]["rejected"] = {"m-xl-7.png": "くちばしが2つ"}
        shots = [p.name for c, s in design.cast_paths(cast, "/x") for p, _, _ in s if c["id"] == "m"]
        self.assertEqual(shots, ["m-xl-8.png", "m-xl-9.png"])

    def test_blob_keeps_the_face_but_forbids_limbs(self):
        # 塊の生き物は物の文で形を取るが、顔は打ち消さない。作風は blob_common だけを付ける
        import tempfile
        sys.path.insert(0, str(ROOT / "tools" / "gen"))
        import design
        with tempfile.TemporaryDirectory() as t:
            Path(f"{t}/c.json").write_text(json.dumps({
                "creature_common": "creature words", "blob_common": "flat colors",
                "characters": [{"id": "s", "kind": "blob", "prompt": "a jelly blob", "negative": "beak"}]}))
            c = design.load_cast(f"{t}/c.json")["characters"][0]
        self.assertEqual(c["full_prompt"], "a jelly blob, flat colors")
        text, neg = design.full_texts(c, "xl")
        self.assertTrue(text.endswith(design.XL_BLOB_SUFFIX))
        self.assertNotIn("creature design", text)
        for word in ("arms", "legs", "wings", "tail", "beak"):
            self.assertIn(word, neg)
        for word in ("eyes", "face", "mouth"):
            self.assertNotIn(word, neg)
        shots = [(p.name, st) for _, s in design.cast_paths({"characters": [c]}, "/x") for p, _, st in s]
        self.assertEqual(shots, [("s-xl-7.png", "xl"), ("s-xl-8.png", "xl")])

    def test_derived_stage_uses_the_chosen_base_picture(self):
        # 系統の派生は、ベースの決定稿（chosen）の絵を手本にする。決定稿が無ければ手本なし
        import tempfile
        from PIL import Image
        sys.path.insert(0, str(ROOT / "tools" / "gen"))
        import design
        cast = {"characters": [{"id": "b", "kind": "creature"}, {"id": "s", "kind": "creature", "from": "b"}]}
        with tempfile.TemporaryDirectory() as t:
            Image.new("RGB", (8, 8), (10, 200, 10)).save(f"{t}/b-xl-9.png")
            self.assertIsNone(design.base_image(cast, cast["characters"][1], t))
            cast["characters"][0]["chosen"] = 9
            self.assertEqual(design.base_image(cast, cast["characters"][1], t).getpixel((0, 0)), (10, 200, 10))
            self.assertIsNone(design.base_image(cast, cast["characters"][0], t))

    def test_mode_downscale_keeps_flat_colors_and_gradient_background_is_cut(self):
        # 灰色のグラデーションの背景は抜け、区画でいちばん多い色で縮めると中間色が生まれない
        import tempfile
        from PIL import Image, ImageDraw
        sys.path.insert(0, str(ROOT / "tools" / "gen"))
        import design
        im = Image.new("RGB", (120, 200))
        for y in range(200):
            ImageDraw.Draw(im).line([(0, y), (119, y)], fill=(150 + y // 4, 150 + y // 4, 150 + y // 4))
        d = ImageDraw.Draw(im)
        d.rectangle([30, 20, 89, 189], fill=(20, 20, 20))
        d.rectangle([32, 22, 59, 187], fill=(220, 60, 40))
        d.rectangle([60, 22, 87, 187], fill=(40, 90, 220))
        with tempfile.TemporaryDirectory() as t:
            im.save(f"{t}/a.png")
            design.pixel(f"{t}/a.png", f"{t}/a.json", 20, 8, mode=True)
            sp = json.loads(Path(f"{t}/a.json").read_text(encoding="utf-8"))
        cols = {sp["palette"][c] for r in sp["rows"] for c in r if c != "."}
        self.assertEqual(len(sp["rows"]), 22)  # 背景が残ると高さが絵の上下まで伸びる
        self.assertLessEqual(len(cols), 5)  # 赤・青・縁・外側の輪郭。混ざった中間色が無い

    def test_gender_and_age_change_the_prompt(self):
        # 男女・中性的・年齢の指定が指示文の頭に入る。子どもに「adult man」を付けない
        sys.path.insert(0, str(ROOT / "tools" / "gen"))
        import design
        t = lambda **kw: design.full_texts({"prompt": "knight", "full_prompt": "knight", **kw})  # noqa: E731
        self.assertIn("adult man", t(gender="male")[0])
        self.assertIn("androgynous", t(gender="androgynous")[0])
        self.assertIn("breasts", t(gender="androgynous")[1])
        child, neg = t(gender="male", age="child")
        self.assertIn("child", child)
        self.assertNotIn("adult man", child)
        self.assertIn("elderly", t(gender="female", age="elder")[0])
        # 中年と老人は SDXL 系で、言葉で書く（女性の老人は祖母の言葉で強める）
        elder = {"id": "e", "gender": "female", "age": "elder", "prompt": "knight", "full_prompt": "knight"}
        self.assertEqual([st for c, s in design.cast_paths({"n": 1, "characters": [elder]}, "/x") for _, _, st in s], ["xl"])
        text = design.full_texts(elder, "xl")[0]
        self.assertTrue(text.startswith("elderly woman knight"))
        self.assertIn("grandmother", text)
        self.assertNotIn("1girl", text)

    def test_traits_are_put_before_the_description(self):
        # 描き分けの部品は人物の説明の前に入り、打ち消しも足される。知らない部品は止める
        sys.path.insert(0, str(ROOT / "tools" / "gen"))
        import design
        c = {"id": "x", "gender": "male", "prompt": "knight", "full_prompt": "knight",
             "traits": ["horns:ram", "fat:high"]}
        text, neg = design.full_texts(c)
        self.assertLess(text.index("curled ram horns"), text.index("knight"))
        self.assertIn("slim", neg)
        with self.assertRaises(SystemExit):
            design.full_texts({**c, "traits": ["horns:none"]})

    def test_patterns_expand_to_traits_and_words(self):
        # 名前付きのパターンは、部品と足す言葉に展開される。知らない名前は止める
        sys.path.insert(0, str(ROOT / "tools" / "gen"))
        import design
        saved = dict(design.PATTERNS)
        try:
            design.PATTERNS["test-blue"] = {"traits": ["skin:blue"], "prompt": "glossy skin", "negative": "blue clothes"}
            c = {"id": "x", "gender": "male", "prompt": "knight", "full_prompt": "knight", "patterns": ["test-blue"]}
            text, neg = design.full_texts(c)
            self.assertIn("blue skin", text)
            self.assertIn("glossy skin", text)
            self.assertIn("blue clothes", neg)
            with self.assertRaises(SystemExit):
                design.full_texts({**c, "patterns": ["no-such"]})
        finally:
            design.PATTERNS.clear()
            design.PATTERNS.update(saved)

    def test_body_framing_uses_plain_wear(self):
        # 素体は簡素な無地の肌着で描き、外套や鎧や背景の物を打ち消す
        sys.path.insert(0, str(ROOT / "tools" / "gen"))
        import design
        c = {"id": "x", "gender": "female", "framing": "body", "prompt": "elf", "full_prompt": "elf"}
        for st in ("anime", "xl"):
            text, neg = design.full_texts(c, st)
            self.assertIn("plain grey sports top", text)
            self.assertIn("cape", neg)

    def test_recolor_changes_only_the_skin_region(self):
        # 肌の色の置き換え: 範囲の外は1画素も変わらず、肌は目標の色相に寄り、暗い線は残る
        import colorsys
        import tempfile
        from PIL import Image, ImageDraw
        sys.path.insert(0, str(ROOT / "tools" / "gen"))
        import edit
        im = Image.new("RGB", (60, 60), (200, 200, 200))
        d = ImageDraw.Draw(im)
        d.rectangle([10, 10, 29, 49], fill=(230, 180, 150))   # 肌
        d.rectangle([18, 20, 20, 22], fill=(20, 20, 20))      # 目の線
        d.rectangle([30, 10, 49, 49], fill=(60, 60, 160))     # 服
        lab = Image.new("L", (60, 60), 0)
        ImageDraw.Draw(lab).rectangle([10, 10, 29, 49], fill=11)  # 顔
        ImageDraw.Draw(lab).rectangle([30, 10, 49, 49], fill=4)   # 上の服
        with tempfile.TemporaryDirectory() as t:
            im.save(f"{t}/a.png")
            lab.save(f"{t}/a.png.parts.png")
            n = edit.recolor(f"{t}/a.png", f"{t}/b.png", "skin", "#4a7ad0")
            out = Image.open(f"{t}/b.png").convert("RGB")
        self.assertEqual(n, 0)
        self.assertEqual(out.getpixel((40, 30)), (60, 60, 160))
        self.assertEqual(out.getpixel((19, 21)), (20, 20, 20))
        h = colorsys.rgb_to_hsv(*(c / 255 for c in out.getpixel((12, 40))))[0]
        self.assertAlmostEqual(h, colorsys.rgb_to_hsv(0x4a / 255, 0x7a / 255, 0xd0 / 255)[0], delta=0.02)

    def test_orphan_is_replaced_but_protected_is_kept(self):
        a, b = "#808080", "#ffffff"
        grid = [[a] * 3 for _ in range(3)]
        grid[1][1] = b
        self.assertEqual(build.clean_orphans([r[:] for r in grid], protect={(1, 1)}), 0)
        g = [r[:] for r in grid]
        self.assertEqual(build.clean_orphans(g), 1)
        self.assertEqual(g[1][1], a)

    def test_measure_counts_head_and_body_with_outline(self):
        sp = spec([
            {"name": "body", "material": "metal", "shapes": [{"type": "rect", "at": [3, 5, 8, 11]}]},
            {"name": "head", "material": "skin", "head": True, "shapes": [{"type": "rect", "at": [4, 1, 7, 5]}]},
            {"name": "sword", "material": "metal", "prop": True, "shapes": [{"type": "rect", "at": [9, 2, 10, 11]}]},
        ])
        out, _ = build.build(sp)
        # 頭は 4 行 + 上の輪郭 1 行（下は胴に接していて輪郭が付かない）
        self.assertEqual(out["head_height"], 5)
        # 体の芯は胴と頭（輪郭込み）。剣は数えない
        self.assertEqual(out["body_box"], [2, 0, 9, 12])

    def test_touchup_uses_material_color(self):
        sp = spec([{"name": "b", "material": "skin", "shapes": [{"type": "rect", "at": [2, 2, 8, 8]}]}],
                  touchups=[{"at": [[4, 4]], "c": "skin:outline"}])
        out, _ = build.build(sp)
        self.assertEqual(out["palette"][out["rows"][4][4]], "#301010")

    def test_merge_spec_remove_override_add(self):
        base = spec([{"name": "a", "material": "metal", "shapes": []},
                     {"name": "b", "material": "metal", "shapes": []}])
        child = {"name": "c", "remove": ["a"], "override": {"b": {"material": "skin"}},
                 "add": [{"name": "x", "before": "b", "material": "skin", "shapes": []},
                         {"name": "y", "material": "skin", "shapes": []}],
                 "materials": {"skin": {"outline": "#000001", "ramp": ["#111111"]}}}
        out = build.merge_spec(base, child)
        self.assertEqual([p["name"] for p in out["parts"]], ["x", "b", "y"])
        self.assertEqual(out["parts"][1]["material"], "skin")
        self.assertEqual(out["materials"]["skin"]["outline"], "#000001")
        self.assertEqual(out["materials"]["metal"], MATS["metal"])
        self.assertEqual(out["name"], "c")
        # 元は変わらない
        self.assertEqual([p["name"] for p in base["parts"]], ["a", "b"])
        with self.assertRaises(ValueError):
            build.merge_spec(base, {"remove": ["zzz"]})

    def test_pixline_has_no_gaps(self):
        # 斜めの細い剣: どの行にも中身のドットがあり、途切れない
        sp = spec([{"name": "blade", "material": "metal",
                    "shapes": [{"type": "pixline", "points": [[8, 1], [5, 10]]}]}])
        out, _ = build.build(sp)
        pal, ramp = out["palette"], set(MATS["metal"]["ramp"])
        for y in range(1, 11):
            self.assertTrue(any(pal.get(c) in ramp for c in out["rows"][y]), f"行 {y} が途切れた")

    def test_breathe_moves_only_tagged_parts(self):
        sp = spec([{"name": "leg", "material": "metal", "shapes": [{"type": "rect", "at": [3, 7, 6, 11]}]},
                   {"name": "head", "material": "skin", "breathe": 1, "shapes": [{"type": "rect", "at": [3, 1, 6, 4]}]}],
                  touchups=[{"at": [[4, 2]], "c": "#000000"}], frames=[{"name": "idle-2", "dy": 1}])
        f = build.build_frames(sp)
        base, moved = f[""], f["idle-2"]
        self.assertEqual(base["rows"][7:], moved["rows"][7:])  # 脚は動かない
        self.assertEqual(base["rows"][0:5], moved["rows"][1:6])  # 頭は1ドット下がる（輪郭ごと）
        self.assertEqual(moved["palette"][moved["rows"][3][4]], "#000000")  # 目も一緒に動く

    def test_move_shifts_named_parts_and_bobs_the_rest(self):
        sp = spec([{"name": "leg", "material": "metal", "shapes": [{"type": "capsule", "points": [[4, 6], [4, 10]], "r": 1}]},
                   {"name": "body", "material": "skin", "shapes": [{"type": "rect", "at": [3, 2, 6, 5]}]}])
        f = build.frame_spec(sp, {"move": {"leg": {"points": [[0, 0], [-2, 0]]}, "gone": {"offset": [1, 0]}},
                                  "body_dy": -1})
        self.assertEqual(f["parts"][0]["shapes"][0]["points"], [[4, 6], [2, 10]])
        self.assertEqual(f["parts"][0]["offset"], [0, 0])
        self.assertEqual(f["parts"][1]["offset"], [0, -1])
        self.assertEqual(sp["parts"][0]["shapes"][0]["points"], [[4, 6], [4, 10]])  # 元は変わらない

    def test_pinhole_is_filled_with_darkest_neighbor(self):
        a, b = "#808080", "#202020"
        g = [[a, a, a], [b, None, a], [a, a, a]]
        self.assertEqual(build.fill_pinholes(g), 1)
        self.assertEqual(g[1][1], b)
        edge = [[None, a], [a, a]]  # 外周の透明は形の外なので埋めない
        self.assertEqual(build.fill_pinholes(edge), 0)

    def test_mirror_flips_shape_but_keeps_light(self):
        # 左右対称な円: 反転しても光は左上なので、描き上がりは元と同じになる（絵を反転すると左右が逆になる）
        sp = spec([{"name": "ball", "material": "metal", "shapes": [{"type": "ellipse", "at": [6, 6, 4, 4]}]}],
                  frames=[{"name": "right", "mirror": True}])
        f = build.build_frames(sp)
        self.assertEqual(f[""]["rows"], f["right"]["rows"])
        flipped = [r[::-1] for r in f[""]["rows"]]
        self.assertNotEqual(f[""]["rows"], flipped)
        # 左に寄った形は右に寄る
        sp2 = spec([{"name": "bar", "material": "metal", "shapes": [{"type": "rect", "at": [1, 2, 3, 10]}]}],
                   touchups=[{"at": [[1, 2]], "c": "#000000"}], frames=[{"name": "right", "mirror": True}])
        r = build.build_frames(sp2)["right"]
        self.assertTrue({r["palette"][c] for c in r["rows"][5][9:11]} <= set(MATS["metal"]["ramp"]))
        self.assertEqual(r["rows"][5][:8], "." * 8)
        self.assertEqual(r["palette"][r["rows"][2][10]], "#000000")

    def test_mirror_frames_reverse_sideways_moves(self):
        leg = {"name": "leg", "material": "metal", "shapes": [{"type": "rect", "at": [5, 2, 7, 10]}]}
        sp = spec([leg], frames=[{"name": "walk-1", "move": {"leg": {"offset": [-2, 0]}}}], mirror_frames=True)
        f = build.build_frames(sp)
        self.assertEqual(set(f), {"", "walk-1", "right-walk-1"})
        row = lambda o: o["rows"][5]  # noqa: E731
        lx0, lx1 = row(f["walk-1"]).index(row(f["walk-1"]).strip(".")[0]), len(row(f["walk-1"]).rstrip(".")) - 1
        rx0 = row(f["right-walk-1"]).index(row(f["right-walk-1"]).strip(".")[0])
        # 左向きで左へ 2 動いた脚（輪郭込み 2〜5）は、右向きでは折り返した位置（6〜9）に来る
        self.assertEqual((lx0, lx1), (2, 5))
        self.assertEqual(rx0, 12 - 1 - lx1)

    def test_reduce_colors_merges_rarest_into_nearest(self):
        g = [["#000000", "#000000", "#ffffff"], ["#ffffff", "#f0f0f0", None]]
        self.assertEqual(build.reduce_colors(g, 2), 1)
        self.assertEqual(g[1][1], "#ffffff")
        self.assertEqual(build.reduce_colors(g, 2), 0)

    def test_frame_override_changes_only_that_frame(self):
        sw = {"name": "sword", "material": "metal", "shapes": [{"type": "rect", "at": [2, 8, 4, 11]}]}
        sp = spec([sw], frames=[{"name": "walk-1", "override": {"sword": {"shapes": [{"type": "rect", "at": [2, 1, 4, 4]}]}}}])
        f = build.frame_spec(sp, sp["frames"][0])
        self.assertEqual(f["parts"][0]["shapes"][0]["at"], [2, 1, 4, 4])
        self.assertEqual(sp["parts"][0]["shapes"][0]["at"], [2, 8, 4, 11])

    def test_transforms_scale_about_origin(self):
        sp = spec([{"name": "body", "material": "metal", "shapes": [{"type": "rect", "at": [4, 2, 8, 12]}]},
                   {"name": "head", "material": "skin", "shapes": [{"type": "ellipse", "at": [6, 2, 2, 2]}]}],
                  touchups=[{"at": [[6, 2]], "c": "#000000"}],
                  transforms=[{"parts": "*", "scale": [0.5, 0.5], "origin": [6, 12], "touchups": True}])
        out = build.apply_transforms(sp)
        self.assertEqual(out["parts"][0]["shapes"][0]["at"], [5.0, 7.0, 7.0, 12.0])
        self.assertEqual(out["parts"][1]["shapes"][0]["at"], [6.0, 7.0, 1.0, 1.0])
        self.assertEqual(out["touchups"][0]["at"], [[6, 7]])
        self.assertEqual(sp["parts"][0]["shapes"][0]["at"], [4, 2, 8, 12])  # 元は変わらない

    def test_touchups_are_written_as_intended(self):
        sp = spec([{"name": "b", "material": "skin", "shapes": [{"type": "rect", "at": [2, 2, 8, 8]}]}],
                  touchups=[{"at": [[4, 4], [40, 40]], "c": "#000000"}])
        self.assertEqual(build.build(sp)[0]["intended"], [[4, 4]])  # 絵の外の座標は書かない

    def test_strands_add_bands(self):
        # 房の縞: 同じ形でも、流れに直交する向きに明暗の段が増える
        base = {"name": "hair", "material": "metal", "shapes": [{"type": "rect", "at": [1, 1, 11, 11]}]}
        flat, _ = build.build(spec([base]))
        banded, _ = build.build(spec([dict(base, strands={"angle": 0, "period": 2.0, "amp": 0.3})]))
        row = lambda o: [o["palette"][c] for c in o["rows"][6][2:10]]  # noqa: E731
        changes = lambda r: sum(a != b for a, b in zip(r, r[1:]))  # noqa: E731
        self.assertGreater(changes(row(banded)), changes(row(flat)))

    def test_parts_files_are_formatted(self):
        # parts.json は tools/fmt.py の形にそろえる。手で書いた崩れを差分に混ぜないため
        files = [str(p) for p in ROOT.glob("characters/*/parts.json")]
        r = subprocess.run([sys.executable, "tools/fmt.py", "--check", *files], cwd=ROOT,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + "\n→ python3 tools/fmt.py characters/*/parts.json で直る")

    def test_warrior_v4_passes_style_check(self):
        r = subprocess.run([sys.executable, "tools/check.py", "characters/warrior/sprite.json",
                            "styles/diorama.json"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)


if __name__ == "__main__":
    unittest.main()
