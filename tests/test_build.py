"""tools/build.py の試験。

見た目の良し悪しは画像で判定する（docs/progress/）。ここで固定するのは、
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
    s = {"name": "t", "style": "hd2d", "canvas": list(canvas), "materials": MATS, "parts": parts}
    s.update(kw)
    return s


class BuildTest(unittest.TestCase):
    def test_committed_sprites_are_reproducible(self):
        # sprite.json は parts.json から書き出したもの。手で直すと次の書き出しで消えるので、一致を見る
        for parts in ROOT.glob("characters/*/parts.json"):
            with self.subTest(parts=parts.parent.name):
                sp = build.load_spec(parts)
                for name, got in build.build_frames(sp).items():
                    want = json.loads(build.sprite_path(parts, name).read_text(encoding="utf-8"))
                    self.assertEqual(got, want, name or "基本")

    def test_thin_part_keeps_its_inside(self):
        # 2ドット幅の剣: 輪郭を外に足すので、中身の色が残る
        sp = spec([{"name": "blade", "material": "metal",
                    "shapes": [{"type": "rect", "at": [5, 2, 7, 10]}]}])
        out, _ = build.build(sp)
        pal = out["palette"]
        inside = {pal[c] for row in out["rows"][2:10] for c in row[5:7]}
        self.assertTrue(inside <= set(MATS["metal"]["ramp"]), inside)
        self.assertEqual({pal[r[4]] for r in out["rows"][2:10]}, {"#101010"})

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
        r = subprocess.run([sys.executable, "tools/check.py", "characters/hd2d-warrior-v4/sprite.json",
                            "styles/hd2d.json"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)


if __name__ == "__main__":
    unittest.main()
