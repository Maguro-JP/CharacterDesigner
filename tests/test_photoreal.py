"""写真級の描き直し（tools/gen/photoreal.py）の、模型を読まない部分の試験。"""
import json
import tempfile
import unittest
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "gen"))
import photoreal  # noqa: E402


def _pair(tmp_path):
    tmp_path = Path(tmp_path)
    a = np.full((120, 80, 3), 200, np.uint8)
    p = np.zeros((120, 80), np.uint8)
    p[20:110, 25:55] = 12                    # 肌
    a[20:110, 25:55] = (230, 190, 170)
    p[60:100, 55:62] = 7                     # 服の暗い帯
    a[60:100, 55:62] = 10
    src = tmp_path / "x.png"
    Image.fromarray(a).save(src)
    Image.fromarray(p).save(str(src) + ".parts.png")
    return src


class PhotorealTest(unittest.TestCase):
    def test_band_filled_from_background(self):
        with tempfile.TemporaryDirectory() as tmp_path:
            tmp_path = Path(tmp_path)
            src = _pair(tmp_path)
            im, parts = photoreal.load_source(src, 80, 120)
            out, px = photoreal.clean_band(im, parts)
            o = np.asarray(out)
            assert px > 0
            assert o[60:100, 55:62].max(2).min() > 150          # 帯が背景の明るさで埋まる
            assert (o[30:100, 30:50] == (230, 190, 170)).all()  # 肌には触らない

    def test_blob_scaled_by_width(self):
        a = np.full((400, 768, 3), 200, np.float32)
        a[100:120, 100:120] = 10                      # 400 画素の浮いた塊
        a[300:302, 300:302] = 10                      # 4 画素の点は外す
        self.assertEqual(int(photoreal.find_blobs(a).sum()), 400)
        b = np.full((800, 1536, 3), 200, np.float32)
        b[200:240, 200:240] = 10                      # 2 倍の幅では 1600 画素で同じ塊
        b[600:610, 600:610] = 10                      # 100 画素は 768 幅の 25 画素相当で外す
        self.assertEqual(int(photoreal.find_blobs(b).sum()), 1600)

    def test_hfmix_keeps_low_from_stage2(self):
        from PIL import Image as I
        s1 = I.fromarray(np.random.default_rng(0).integers(0, 255, (64, 64, 3), dtype=np.uint8))
        s2 = I.new("RGB", (96, 96), (120, 120, 120))
        o = np.asarray(photoreal.hfmix(s1, s2)).astype(float)
        self.assertLess(abs(o.mean() - 120), 6)
        self.assertGreater(o.std(), 3)

    def test_tiles_cover_edges(self):
        xs = photoreal.tiles(1152, 768, 128)
        assert xs[0] == 0 and xs[-1] == 1152 - 768
        assert photoreal.tiles(500, 768, 128) == [0]

    def test_dry_run_writes_without_models(self):
        with tempfile.TemporaryDirectory() as tmp_path:
            tmp_path = Path(tmp_path)
            src = _pair(tmp_path)
            out = tmp_path / "out"
            assert photoreal.main([str(src), str(out), "--width", "80", "--height", "120", "--dry-run"]) == 0
            assert (out / "x-0-clean.png").exists() and (out / "x-0-lineart.png").exists()
            assert json.loads((out / "times.json").read_text())["band_px"] > 0

    def test_request_points_at_tracked_image(self):
        req = json.loads((ROOT / "config" / "photoreal-request.json").read_text())
        assert not req["src"].startswith(".worklog")
        assert (ROOT / req["src"]).exists()   # .parts.png は git に入れないので、無ければ台本が作る



if __name__ == "__main__":
    unittest.main()


def _sphere(cel=False):
    """球（肌の部位 12）を左上の光で塗る。cel なら 2 段の影にする。奥行きは球の高さ"""
    import measure  # noqa: F401
    H = W = 768
    yy, xx = np.mgrid[:H, :W].astype(np.float32)
    r = 300.0
    dx, dy = (xx - 384) / r, (384 - yy) / r
    inside = dx ** 2 + dy ** 2 < 1
    dz = np.sqrt(np.clip(1 - dx ** 2 - dy ** 2, 0, 1))
    n = np.stack([dx, dy, dz], -1)
    t, e = np.radians(135), np.radians(40)
    shade = 0.5 + 0.5 * (n @ np.array([np.cos(t) * np.cos(e), np.sin(t) * np.cos(e), np.sin(e)]))   # 回り込む光（陰の側にも陰影が続く）
    if cel:
        shade = np.where(shade > 0.45, 0.9, 0.45)
    L = np.where(inside, 0.4 + 0.55 * shade, 0.6)
    L = L + np.random.default_rng(0).normal(0, 0.03, L.shape)   # 肌理の揺れ（段が分布の端の 1 本に潰れないように）
    rgb = np.stack([L, L * 0.85, L * 0.75], -1)
    seg = np.where(inside, 12, 0).astype(np.uint8)
    depth = Image.fromarray((np.where(inside, dz, 0) * 255).astype(np.uint8))
    return rgb, seg, depth


class ShadowCheckTest(unittest.TestCase):
    def test_cel_steps_fail_and_soft_shading_passes(self):
        import edit
        import measure
        out = {}
        for cel in (True, False):
            rgb, seg, depth = _sphere(cel)
            m = measure.shadow(rgb, seg, edit.LABELS)
            m["normal_corr"], _ = photoreal.normal_corr(Image.fromarray((rgb * 255).astype(np.uint8)), depth, Image.fromarray(np.where(seg > 0, 4, 0).astype(np.uint8)))
            out[cel] = {f["path"] for f in measure.judge_shadow(m)}
        self.assertIn("bimodal", out[True])
        self.assertNotIn("bimodal", out[False])
        self.assertNotIn("normal_corr", out[False])

    def test_photo_refs_mostly_pass(self):
        import measure
        rows = json.loads((ROOT / "tests" / "fixtures" / "photoreal_refs.json").read_text())["rows"]
        self.assertGreaterEqual(len(rows), 10)
        fails = [[f["path"] for f in measure.judge_shadow(r["shadow"])] for r in rows]
        self.assertGreaterEqual(sum(not f for f in fails), 13)   # 強い日差しの 1 枚（bimodal 0.62）だけ落ちる

    def test_anime_left_and_gray_fail(self):
        import measure
        # アニメの塗りが残る絵を測り直した数字（作り直した測り方）。run 40214490230 の post-relight の最後の絵、
        # run 40205259892 の r3 の最後の絵（cowboy-s12）。どちらも bimodal で落ちる
        for b, flat in ((0.466, 0.0401), (0.67, 0.0081)):
            m = {"bimodal": b, "spread": 160, "ratio": 0.6, "normal_corr": 0.5, "flat_skin": flat}
            self.assertIn("bimodal", {f["path"] for f in measure.judge_shadow(m)})
        gray = {"sat_ratio": 0.153, "color_dab": 12.09, "hair_de": 49.29}
        self.assertEqual({f["path"] for f in measure.judge_shadow(gray)}, {"sat_ratio", "color_dab", "hair_de"})

    def test_color_keep_catches_gray_and_hair(self):
        import edit
        import measure
        rgb = np.zeros((200, 200, 3), np.float32)
        seg = np.zeros((200, 200), np.uint8)
        seg[20:80, 50:150] = 2
        rgb[20:80, 50:150] = 0.05                      # 黒髪
        seg[80:190, 50:150] = 12
        rgb[80:190, 50:150] = (0.9, 0.7, 0.6)          # 肌
        same = measure.color_keep(rgb, rgb.copy(), seg, seg, edit.LABELS)
        self.assertAlmostEqual(same["sat_ratio"], 1.0, places=2)
        g = rgb.copy()
        g[80:190, 50:150] = 0.72                        # 灰色に抜けた肌
        g[20:80, 50:150] = 0.9                          # 白くなった髪
        bad = measure.color_keep(rgb, g, seg, seg, edit.LABELS)
        self.assertLess(bad["sat_ratio"], 0.5)
        self.assertGreater(bad["hair_de"], 40)

    def test_iclight_merge_keeps_color(self):
        img = Image.new("RGB", (64, 96), (220, 170, 150))
        seg = np.full((96, 64), 12, np.uint8)
        gray = Image.fromarray(np.tile(np.linspace(60, 200, 64, dtype=np.uint8)[None, :, None], (96, 1, 3)))
        o = np.asarray(photoreal.iclight_merge(img, gray, Image.fromarray(seg))).astype(float)
        self.assertGreater(o[:, :, 0].mean() - o[:, :, 2].mean(), 40)   # 肌の赤みが残る
        self.assertGreater(o[:, -5:].mean(), o[:, :5].mean() + 20)       # 明るさの変わり方は IC-Light から

    def test_relight_follows_one_light(self):
        rgb, seg, depth = _sphere(False)
        seg = np.where(seg > 0, 4, 0).astype(np.uint8)   # 相関は胴と顔の大きな面で測るので、球を胴（4）にする
        flat = Image.fromarray(np.where(seg[..., None] > 0, 200, 150).astype(np.uint8).repeat(3, 2))
        before, _ = photoreal.normal_corr(flat, depth, Image.fromarray(seg))
        after_im = photoreal.relight(flat, Image.fromarray(seg), depth, 135, amount=0.5)
        after, deg = photoreal.normal_corr(after_im, depth, Image.fromarray(seg))
        self.assertGreater(after, before + 0.3)
        self.assertIn(deg, (120, 150))


class CastShadowTest(unittest.TestCase):
    def test_cast_darkens_floor_away_from_light(self):
        H, W = 400, 300
        seg = np.zeros((H, W), np.uint8)
        seg[100:350, 130:170] = 12                       # 立った棒（足は 349 行）
        img = Image.new("RGB", (W, H), (180, 180, 180))
        depth = Image.fromarray((seg > 0).astype(np.uint8) * 200)
        o = np.asarray(photoreal.cast_shadow(img, Image.fromarray(seg), depth, 135, 0.5)).astype(int)
        from scipy import ndimage
        self.assertTrue((o[ndimage.binary_erosion(seg > 0, iterations=3)] == 180).all())   # 人物は暗くしない（縁は 1〜2 画素ぼかして重ねる）
        right, left = o[300:350, 200:290].mean(), o[300:350, 10:100].mean()
        self.assertLess(right, left - 3)                  # 左上の光なら影は右へ
        self.assertLess(o[352, 150, 0], 170)              # 足元の接地の影

    def test_light_gradient_bright_toward_light(self):
        g = np.asarray(photoreal.light_gradient((64, 64), 135).convert("L")).astype(int)
        self.assertGreater(g[0, 0], g[63, 63])


class AsianPromptTest(unittest.TestCase):
    def test_asian_words_reach_prompt_and_negative(self):
        a = photoreal.parse(["x.png", "out", "--asian", "--model", "majicmix"])
        self.assertEqual(a.model, "majicmix")
        self.assertIn("majicmix", photoreal.CHECKPOINTS)
        self.assertTrue(photoreal.ASIAN.strip(", ").startswith("japanese"))
        self.assertIn("caucasian", photoreal.ASIAN_NEG)


class FaceStepsTest(unittest.TestCase):
    def _face(self, lips):
        rgb = np.full((200, 200, 3), (225, 185, 165), np.uint8)
        seg = np.zeros((200, 200), np.uint8)
        yy, xx = np.mgrid[:200, :200]
        seg[(xx - 100) ** 2 / 70 ** 2 + (yy - 100) ** 2 / 90 ** 2 <= 1] = 11
        rgb[lips] = (170, 60, 70)
        return rgb, seg, yy, xx

    def test_mouth_symmetric_passes_smeared_fails(self):
        import qc
        rgb, seg, yy, xx = self._face(np.zeros((200, 200), bool))
        good = (np.abs(xx - 100) <= 14) & (np.abs(yy - 160) <= 4)
        rgb[good] = (170, 60, 70)
        self.assertFalse(qc.mouth_check(rgb, seg)["bad"])
        rgb2, seg, yy, xx = self._face(np.zeros((200, 200), bool))
        # 唇が頬の下へ斜めににじんだ形（6 周目の絵の崩れ）
        smear = ((np.abs(xx - 100) <= 14) & (np.abs(yy - 160) <= 4)) | ((xx > 100) & (xx < 160) & (yy > 156) & (yy < 185) & (yy - 156 > (xx - 100) * 0.45) & (yy - 156 < (xx - 100) * 0.45 + 8))
        rgb2[smear] = (170, 60, 70)
        self.assertTrue(qc.mouth_check(rgb2, seg)["bad"])

    def test_uncover_eye_mirrors_visible_eye(self):
        img = np.full((120, 160, 3), 220, np.uint8)
        seg = np.full((120, 160), 11, np.uint8)
        img[55:65, 95:110] = 20                      # 見えている目（右側）
        seg[40:80, 30:75] = 2                        # 左の目に前髪
        img[40:80, 30:75] = 10
        out, disk, dist = photoreal.uncover_eye(Image.fromarray(img), seg, ((52, 60), (102, 60)))
        o = np.asarray(out)
        self.assertIsNotNone(disk)
        self.assertTrue(disk[60, 52])
        self.assertLess(o[60, 47:57].mean(), 60)     # 反転した目が下絵に入る
        self.assertGreater(o[52, 52].mean(), 150)    # 目の周りは見えている目の周りの肌


class CastCheckTest(unittest.TestCase):
    def test_round6_floor_shadow_fails(self):
        import measure
        # 6 周目の rv-asian の最後の絵（run 40233249025）を cast_check で測った数字。影は左右の塊で、縁に白いにじみがある。
        # 接地は、足の下の暗さだけで測ると 0.78 で通った。写した影とのつながりで測ると 0.0
        bad = {"cast_iou": 0.386, "contact": 0.0, "cast_side": 0.79, "cast_spill": 0.372, "halo": 0.128}
        self.assertEqual({f["path"] for f in measure.judge_shadow(bad)}, set(bad))

    def test_blob_under_feet_is_not_contact(self):
        import measure
        # 足の下を暗くする塊（人物の形をしない楕円）は、接地に数えない
        H, W = 600, 400
        seg = np.zeros((H, W), np.uint8)
        seg[150:520, 180:200] = 12
        seg[150:520, 210:230] = 13
        a = np.full((H, W, 3), 0.6, np.float32)
        yy, xx = np.mgrid[:H, :W]
        blob = ((xx - 205) / 170) ** 2 + ((yy - 515) / 30) ** 2 <= 1
        a[blob & (seg == 0)] = 0.4
        m = measure.cast_check(a, seg, 135)
        self.assertLess(m["contact"], 0.6)

    def test_projected_shadow_with_contact_passes(self):
        import measure
        H, W = 600, 400
        seg = np.zeros((H, W), np.uint8)
        seg[150:520, 180:200] = 12                     # 脚 2 本
        seg[150:520, 210:230] = 13
        seg[100:300, 170:240] = 4
        img = Image.new("RGB", (W, H), (150, 150, 150))
        out = photoreal.cast_shadow(img, Image.fromarray(seg), None, 135, 0.5)
        m = measure.cast_check(np.asarray(out, np.float32) / 255, seg, 135)
        self.assertGreaterEqual(m["cast_iou"], 0.6)
        self.assertGreaterEqual(m["contact"], 0.6)
        self.assertGreaterEqual(m["cast_side"], 0.85)
        self.assertLessEqual(m["cast_spill"], 0.2)
