"""頼みの読み取り（語ごとの対応表、読めなかった語）、単語辞書、単語のお気に入り、訳、描き続けて学ぶ仕組みの試験。

語の読み取りは、頼みの文 30 本（SENTENCES）と、表を直すときに見ていない文 30 本（HELD_OUT）で、読めなかった語を数える。
画面は本物と同じ経路で、欄に書き、ボタンとメニューを押して最後まで流す。
"""
import os
import random
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from chatdraw import jaterms  # noqa: E402

SENTENCES = [
    "金髪の女の子が海辺で笑顔で手を振っている", "黒髪ロングの少女が図書館で本を読んでいる", "銀髪の騎士が剣を持って城の前に立っている",
    "猫耳のメイドが紅茶を運んでいる", "赤い帽子と青いドレスの女性", "眼鏡をかけた男性がカフェでコーヒーを飲んでいる",
    "ポニーテールの少女が桜の下で振り返る", "雨の街で傘をさした女の子", "魔法使いの老人が杖を持って森を歩く",
    "白いビキニの女性が砂浜で日よけをしている", "夜の屋上でギターを弾く少年", "狐耳の巫女が神社で微笑む",
    "ツインテールのアイドルが歌っている", "エルフの弓使いが草原で弓を構える", "制服の女の子が教室の窓際に座っている",
    "帽子なしで麦わら帽子を持つ少女", "二人の女の子が公園で手をつないで歩く", "吸血鬼の男性がマントを羽織っている",
    "青い目の少女が雪の中でマフラーを巻いている", "忍者が月夜の屋根の上を走る", "天使の翼の少女が空を飛んでいる",
    "侍が刀を構えて夕焼けの川辺に立つ", "白衣の看護師が病院の廊下で微笑む", "ショートヘアの女性がパーカーを着てスマホを見ている",
    "魔女がほうきに乗って星空を飛ぶ", "浴衣の少女が夏祭りで金魚すくいをする", "鎧の女騎士が盾を持ってひざまずく",
    "ロボットが砂漠で夕日を見上げる", "着物の女性が花を持って座っている", "海賊の少女が船の上で笑う",
]
# 表を直すときに見ていない文。ここで読めなかった語は、言葉の模型か、利用者の直し（読めなかった語の段）で埋める
HELD_OUT = [
    "赤髪の少女が台所でケーキを作っている", "白髪の老人がベンチで新聞を読む", "ピンク髪の魔法少女が杖を振る",
    "青いパーカーの少年が自転車に乗る", "黒いコートの探偵が霧の街を歩く", "金色の瞳のドラゴンが山の上を飛ぶ",
    "ゴスロリの少女が教会の階段に座る", "制服の女の子が電車の窓から外を見ている", "緑の髪のエルフが森で歌う",
    "兵士が雨の中で銃を構える", "お姫様が庭で薔薇を持って微笑む", "うさ耳の少女がにんじんを食べる",
    "眼鏡の先生が黒板の前に立つ", "猫を抱いた女の子がソファで寝ている", "水着の女性がプールで泳ぐ",
    "夜空の下で花火を見上げる浴衣の少女", "紫の目の吸血鬼が月を背にして笑う", "冒険者の少年が剣を背負って草原を走る",
    "マフラーを巻いた少女が冬の駅で待っている", "チャイナドレスの女性が扇子を持つ", "人魚が水中で真珠を持っている",
    "ツインテールの少女がピアノを弾いている", "看護師がカルテを持って廊下を歩く", "妖精が花の上に座っている",
    "ポニーテールの女の子がバスケットボールをする", "侍が桜の下で刀を抜く", "白いワンピースの少女がひまわり畑に立つ",
    "騎士が馬に乗って城へ向かう", "メイドがトレイに紅茶を乗せて運ぶ", "アイドルがステージでマイクを持って踊る",
]
HELD_OUT_LIMIT = 24   # 表だけで読めなかった語の数（直す前は 60）。増えたら表の読み方が後戻りした


def lost(sentences) -> list[str]:
    return [w for s in sentences for w in jaterms.leftover(s)]


class Home:
    """利用者のデータの置き場を一時の所にする（本物の辞書と記録に触れない）"""

    def __enter__(self):
        self.d = TemporaryDirectory()
        self.p = mock.patch.dict(os.environ, {"CD_HOME": self.d.name})
        self.p.start()
        return Path(self.d.name)

    def __exit__(self, *a):
        self.p.stop()
        self.d.cleanup()


class ReadEveryWordTest(unittest.TestCase):
    def test_thirty_sentences_lose_no_word(self):
        with Home():
            self.assertEqual(lost(SENTENCES), [])
            for s in SENTENCES:   # 対応表の語は、言い回しを除いて全部タグに乗る
                for row in jaterms.align(s):
                    if row["kind"] in ("draw", "neg"):
                        self.assertTrue(row["tags"], (s, row))

    def test_held_out_no_worse(self):
        with Home():
            got = lost(HELD_OUT)
            self.assertLessEqual(len(got), HELD_OUT_LIMIT, got)

    def test_align_shows_every_word_in_order(self):
        with Home():
            rows = jaterms.align("赤い帽子なしで紅茶を運ぶメイドがベンチに座る")
            self.assertEqual([(r["word"], r["kind"]) for r in rows],
                             [("赤い帽子なし", "neg"), ("紅茶", "draw"), ("運ぶ", "draw"), ("メイド", "draw"), ("ベンチ", "lost"), ("座る", "draw")])
            self.assertEqual(jaterms.coverage("紅茶を運ぶメイドがベンチに座る"), (5, 1))

    def test_mixed_english_tags_kept(self):
        with Home():   # 単語のお気に入りから足した英語のタグが、日本語の頼みの中で落ちない
            self.assertEqual(jaterms.tags_from("猫耳の少女、red scarf, full body"), ["1girl", "solo", "cat ears", "red scarf", "full body"])   # 人数の言葉が先頭（jaterms.order）
            self.assertEqual(jaterms.tags_from("Tシャツの少女"), ["1girl", "solo", "t-shirt"])

    def test_verb_forms(self):
        with Home():
            self.assertIn("lying", jaterms.tags_from("ソファで寝ている"))
            self.assertIn("riding", jaterms.tags_from("自転車に乗っている"))

    def test_user_fix_reads_lost_word(self):
        from chatdraw import worddict
        with Home():
            self.assertIn("ベンチ", jaterms.leftover("ベンチに座る少女"))
            worddict.set_term("ベンチ", "bench")
            self.assertNotIn("ベンチ", jaterms.leftover("ベンチに座る少女"))
            self.assertIn("bench", jaterms.tags_from("ベンチに座る少女"))
            worddict.set_term("ベンチ", "ベンチ")   # 日本語のタグは絵の模型に渡さない
            self.assertNotIn("ベンチ", jaterms.tags_from("ベンチに座る少女"))

    def test_language_model_reads_word_by_word(self):
        """言葉の模型があるときは、表で読めなかった語を 1 語ずつ訳させ、辞書に覚える。訳せない語は読めなかった語に出す"""
        from chatdraw import worddict
        from chatdraw.engine import ASK_WORD, Words

        class Fake(Words):
            def __init__(self):
                self.asked = []

            def ready(self):
                return True

            def ask(self, system, text, max_tokens=64, one_line=True):
                self.asked.append((system, text))
                if system == ASK_WORD:
                    return {"ベンチ": "bench", "新聞": "newspaper"}.get(text, "わからない")
                return "old man, reading"
        with Home():
            w = Fake()
            out = w.to_prompt("白髪の老人がベンチで新聞を読むカルテ")
            for t in ("bench", "newspaper", "old man", "reading"):
                self.assertIn(t, out)
            self.assertEqual(w.untranslated, ["カルテ"])
            self.assertEqual(worddict.terms()["新聞"], "newspaper")
            worddict.set_term("新聞", "news paper")              # 利用者の直しを、模型の訳で上書きしない
            worddict.set_term("新聞", "paper", source="llm")
            self.assertEqual(worddict.terms()["新聞"], "news paper")


class DictionaryTest(unittest.TestCase):
    def test_record_and_translation(self):
        from chatdraw import worddict
        with Home() as home:
            worddict.record(["red scarf", "1girl"], True, {"red scarf": "赤いマフラー"})
            worddict.record(["red scarf", "smile"], False)
            rows = {r["tag"]: r for r in worddict.entries()}
            self.assertEqual(set(rows), {"red scarf", "1girl"})   # 通った語だけを辞書に出す
            self.assertEqual((rows["red scarf"]["used"], rows["red scarf"]["passed"]), (2, 1))
            self.assertEqual(rows["red scarf"]["last"], time.strftime("%Y-%m-%d"))
            self.assertEqual(worddict.translation("red scarf", "日本語"), "赤いマフラー")
            self.assertEqual(worddict.translation("smile", "日本語"), "笑顔")      # 表の逆引き
            self.assertEqual(worddict.translation("smile", "English"), "smile")
            worddict.set_translation("smile", "にっこり", "日本語")
            self.assertEqual(worddict.translation("smile", "日本語"), "にっこり")
            worddict.set_translation("smile", "", "日本語")
            self.assertEqual(worddict.translation("smile", "日本語"), "笑顔")
            self.assertTrue((home / "words.json").is_file())
            self.assertFalse((ROOT / "words.json").exists())

    def test_favorites(self):
        from chatdraw import worddict
        with Home():
            self.assertTrue(worddict.add_favorite("red scarf"))
            self.assertFalse(worddict.add_favorite("red scarf"))
            worddict.add_favorite("猫耳")
            self.assertEqual(worddict.favorites(), ["red scarf", "猫耳"])
            worddict.remove_favorite("red scarf")
            self.assertEqual(worddict.favorites(), ["猫耳"])


class LearnTest(unittest.TestCase):
    def test_learns_hard_tags_and_caps(self):
        from chatdraw import wordlearn
        with Home():
            for i in range(30):
                wordlearn.record(f"/x/{i}.png", "1girl, red scarf, umbrella", "m", 1, ["umbrella"], False)
            st = wordlearn.stats()
            self.assertLessEqual(wordlearn.weight("umbrella", st), wordlearn.MAX_WEIGHT)
            self.assertEqual(wordlearn.weight("red scarf", st), 0.0)
            out, moved, explored = wordlearn.adjust("1girl, red scarf, umbrella", "m", random.Random(1))
            if not explored:
                self.assertEqual(moved, ["umbrella"])
                self.assertEqual(out, "1girl, umbrella, red scarf")
            self.assertLessEqual(wordlearn.guidance("m", 5.0), 5.0 + wordlearn.MAX_NUDGE)
            self.assertGreater(wordlearn.guidance("m", 5.0), 5.0)

    def test_few_draws_count_weakly(self):
        from chatdraw import wordlearn
        with Home():
            wordlearn.record("/x/a.png", "1girl, hat", "m", 0, ["hat"], False)
            self.assertLess(wordlearn.weight("hat"), wordlearn.MIN_WEIGHT)   # 1 回外れただけでは前に出さない
            self.assertEqual(wordlearn.adjust("1girl, hat", "m", random.Random(5))[1], [])

    def test_same_preference_never_drops_asked_words(self):
        """同じ好み（同じタグの絵ばかり「良い」）を 300 回続けても、頼みの語は足しも消しもしない。学ばない回も混ざる"""
        from chatdraw import wordlearn
        with Home():
            for i in range(300):
                p = f"/x/{i}.png"
                wordlearn.record(p, "1girl, pink hair, maid", "m", 0, [] if i % 3 else ["maid"], True)
                wordlearn.set_verdict(p, "good") if i % 10 == 0 else None
            rng = random.Random(7)
            asked = "1girl, blue hair, knight, sword, castle"
            explored = 0
            for _ in range(500):
                out, moved, ex = wordlearn.adjust(asked, "m", rng)
                explored += ex
                self.assertEqual(sorted(t.strip() for t in out.split(",")), sorted(t.strip() for t in asked.split(",")))
                self.assertNotIn("pink hair", out)
                self.assertNotIn("maid", out)
            self.assertTrue(0.12 < explored / 500 < 0.28, explored)
            st = wordlearn.stats()
            self.assertLessEqual(wordlearn.weight("maid", st), wordlearn.MAX_WEIGHT)
            self.assertEqual(wordlearn.weight("pink hair", st), 0.0)   # 「良い」はタグを強めない

    def test_verdict(self):
        from chatdraw import wordlearn
        with Home():
            wordlearn.record("/x/a.png", "1girl", "m", 0, [], True)
            self.assertTrue(wordlearn.set_verdict("/x/a.png", "fixed"))
            self.assertEqual(wordlearn.verdict_of("/x/a.png"), "fixed")
            self.assertFalse(wordlearn.set_verdict("/x/none.png", "good"))
            self.assertGreater(wordlearn.stats()["models"]["m"]["fail"], 0)


def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class WindowTest(unittest.TestCase):
    """本物と同じ経路: 欄に書く → 読めなかった語の段を押して直す → 語を登録 → 押して足す → 描く → 判定 → 辞書の窓"""

    def test_whole_flow(self):
        from PySide6.QtCore import QSettings
        from chatdraw.app import Window
        from chatdraw.engine import Studio, Words
        from chatdraw import worddict, wordlearn
        from chatdraw.tests.test_chatdraw import FakePainter, wait_bg

        class TableWords(Words):   # 言葉の模型の無い環境と同じ（表と辞書だけで読む）
            def __init__(self):
                pass

            def ready(self):
                return False
        app()
        with Home() as home:
            painter = FakePainter()
            w = Window(Studio(TableWords(), painter, home / "out"))
            w.layout_store = QSettings(str(home / "l.ini"), QSettings.IniFormat)
            w.settings.set("output_dir", str(home / "out"))
            w.show()
            # 指示のタブの並びは変えない（模型、描くワード、描くワードの登録、禁止ワード、禁止ワードの登録）。単語の段は登録の中
            lay = w.ai_panel.sections["指示"].body
            order = [lay.itemAt(i).widget() for i in range(lay.count()) if lay.itemAt(i).widget() is not None]
            self.assertLess(order.index(w.entry), order.index(w.tips_scroll))
            self.assertLess(order.index(w.tips_scroll), order.index(w.word_row))
            self.assertLess(order.index(w.word_row), order.index(w.neg_tips_box))
            w.entry.setText("紅茶を運ぶメイドがベンチに座る")
            w.ai_panel.preview_timer.timeout.emit()
            app().processEvents()
            self.assertTrue(w.lost_row.isVisible())
            self.assertEqual(w.lost_row.words, ["ベンチ"])
            chip = w.lost_row.flow.itemAt(0).widget()
            self.assertIn("タグ", chip.toolTip())
            with mock.patch("chatdraw.wordpanel.QInputDialog.getText", return_value=("bench", True)):
                chip.click()
            app().processEvents()
            self.assertFalse(w.lost_row.isVisible())
            self.assertIn("bench", w.ai_panel.preview.text())
            # ★ で語を登録（欄で選んだ語）。登録した語のボタンを押すと欄に足す。訳はツールチップ
            cur = w.entry.textCursor()
            cur.setPosition(0)
            cur.setPosition(2, cur.MoveMode.KeepAnchor)
            w.entry.setTextCursor(cur)
            w.word_row.star.click()
            self.assertEqual(worddict.favorites(), ["紅茶"])
            worddict.add_favorite("red scarf")
            w.word_row.reload()
            chips = {c.property("word"): c for c in w.word_row.chips()}
            self.assertIn("tea", chips["紅茶"].toolTip())
            self.assertIn("訳: 赤いマフラー", chips["red scarf"].toolTip())
            chips["red scarf"].click()
            self.assertTrue(w.entry.text().endswith("、red scarf"))
            w.word_row.edit_translation("red scarf", "赤い襟巻き")
            chips = {c.property("word"): c for c in w.word_row.chips()}
            self.assertIn("赤い襟巻き", chips["red scarf"].toolTip())
            # 右クリックの「お気に入りから外す」
            menu = w.word_row.menu(chips["紅茶"], None, "紅茶", run=False)
            next(a for a in menu.actions() if a.text() == "お気に入りから外す").trigger()
            self.assertEqual(worddict.favorites(), ["red scarf"])
            # 描く。日本語は模型に渡さず、読めた語と直した語・足した英語のタグが全部渡る
            w.button.click()
            end = time.time() + 30
            while (w.thread is not None or not w.images) and time.time() < end:
                app().processEvents()
                time.sleep(0.01)
            wait_bg(app(), w)
            self.assertTrue(w.images)
            sent = painter.calls[0][0]
            for t in ("tea", "carrying", "maid", "bench", "sitting", "red scarf"):
                self.assertIn(t, sent)
            self.assertNotRegex(sent, r"[぀-ヿ一-鿿]")
            log = wordlearn.rows()
            self.assertEqual(len(log), 1)
            self.assertIn("bench", log[0]["tags"])
            self.assertEqual(worddict._load()["words"]["bench"]["used"], 1)
            # 履歴の右クリック → 判定 → 良い
            w.history.setCurrentRow(0)
            pos = w.history.visualItemRect(w.history.item(0)).center()
            m = w._history_menu(pos, run=False)
            judge = next(a for a in m.actions() if a.text() == "判定").menu()
            next(a for a in judge.actions() if a.text() == "良い").trigger()
            self.assertEqual(wordlearn.verdict_of(w.images[0]), "good")
            # 設定 → 単語辞書… で窓を開く。対応表に語ごとのタグ、辞書に通った語、訳を直す
            worddict.record(["bench", "maid"], True, {"bench": "ベンチ"})
            act = next(a for menu in w.menuBar().actions() if menu.menu()
                       for a in menu.menu().actions() if a.text() == "単語辞書…")
            act.trigger()
            app().processEvents()
            from chatdraw.wordpanel import WordDialog
            dlg = next(x for x in app().topLevelWidgets() if isinstance(x, WordDialog) and x.isVisible())
            words = [dlg.map.item(i, 0).text() for i in range(dlg.map.rowCount())]
            self.assertIn("ベンチ", words)
            self.assertEqual(dlg.map.item(words.index("ベンチ"), 1).text(), "bench")
            tags = [dlg.table.item(i, 1).text() for i in range(dlg.table.rowCount())]
            self.assertIn("bench", tags)
            i = tags.index("bench")
            self.assertEqual(dlg.table.item(i, 2).text(), "ベンチ")
            dlg.table.item(i, 2).setText("長椅子")
            self.assertEqual(worddict.translation("bench", "日本語"), "長椅子")
            dlg.table.cellWidget(i, 0).click()   # ☆ で単語のお気に入りへ
            self.assertIn("bench", worddict.favorites())
            self.assertIn("bench", [c.property("word") for c in w.word_row.chips()])
            self.assertIn("記録 1 枚", dlg.learn.text())
            dlg.close()
            w.closing_checked = True   # 閉じる前の保存の問いを出さない
            w.close()


if __name__ == "__main__":
    unittest.main()
