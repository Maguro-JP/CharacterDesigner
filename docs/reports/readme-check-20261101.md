# README の項目とコードの入口の対応（2026-11-01）

README.md と README.en.md に書いた機能を、chatdraw/ の入口（メニュー・ボタン・右クリック）と試験に突き合わせた表。入口の名前はコードの文字列のまま。

| README の項目 | 入口（コードの場所） | 試験 |
|---|---|---|
| 使い方ツアー・機能ごとの案内 | 「ヘルプ」→「使い方ツアー」（F1）、「機能ごとの案内」（`chatdraw/app.py` の help_menu、`chatdraw/tours.py`） | test_chatdraw |
| AI の欄のタブ | 描く内容・作風・模型・詳しい設定・加工（`chatdraw/aipanel.py` の SECTIONS） | test_aitabs |
| プリセットと画風 | `chatdraw/aipanel.py` の PRESETS と STYLES | test_presetui |
| 声で頼む | 「🎤」（`chatdraw/app.py` の mic_button、`chatdraw/voice.py`） | 無し |
| 参考画像 | 「参考画像に寄せる」（`chatdraw/aipanel.py`） | test_chatdraw |
| おまかせ | 「AI」メニューの「おまかせ」（`chatdraw/app.py` の _fill_ai_menu）→ `chatdraw/engine.py` → `chatdraw/omakase.py` | test_omakase |
| 描き直し・頼み直し | 履歴の右クリックの「この設定で描き直す」（`chatdraw/app.py` の _history_menu） | test_chatdraw |
| キャラクターデザイン | 「キャラクターデザイン」メニュー（`chatdraw/app.py` の _fill_chara_menu、`chatdraw/charadesign.py`） | test_chatdraw、test_features |
| 赤ペンで直す | 道具の「赤ペン（AI に直す所を囲む）」、キャンバスの右クリックの「道具」（`chatdraw/redpen.py`） | test_chatdraw |
| 既存の絵の編集 | 「ファイル」→「画像を開いて直す…」、履歴の右クリックの「編集する（囲んで直す）」 | test_editing |
| 綺麗にする | キャンバスの右クリックの「綺麗にする」（`chatdraw/app.py` の canvas_menu、`chatdraw/finishers.py`） | test_editing、test_original_finish |
| 絵の外へ広げる | キャンバスの右クリックの「絵の外へ広げる」（outpaint_canvas） | test_editing |
| 加工 | 「ちびキャラに」「線画に」「ドット絵に」「絵を 2 倍に拡大」（`chatdraw/aipanel.py`） | test_aitabs |
| 3D に進む | 履歴の右クリックの「3D に進む…」（`chatdraw/to3d.py`） | test_features |
| 独自の作画監督 | おまかせの検品（`chatdraw/omakase.py` から `chatdraw/origqc.py`） | test_original_qc |
| 模型の選択・お気に入り・直しに使う模型 | 「AI」メニュー | test_aitabs |
| 模型の管理・ブロック | 「模型の管理…」、行の「…」と右クリック（`chatdraw/manager.py`） | test_modelmgr、test_modelblock |
| テーマ・配置・欄の位置 | 「表示」→「テーマ」、「配置」メニュー、「ウィンドウ」→「欄の位置」「帯の位置」 | test_panels |
| タイムラプス | 「表示」→「タイムラプスを記録する」「タイムラプスを見る…」、「GIF に書き出す」「動画に書き出す」 | test_chatdraw |
| 保存・書き出し | 「ファイル」→「保存」「名前を付けて保存…」「書き出す」「ディレクトリを開く」 | test_aitabs（PSD） |
| ごみ箱 | 「ファイル」→「ごみ箱…」、履歴の「消す（ごみ箱へ）」（`chatdraw/trash.py`） | test_panels |
| ライブラリー・学習用に集める | 「ライブラリー」の欄（作品・資料・好み）、右クリックの「学習用に集める」（`chatdraw/librarypanel.py`、`chatdraw/ownstyle.py`） | test_ownstyle |
| SNS に送る | 履歴の右クリックの「SNS に送る」（`chatdraw/share.py`） | test_chatdraw、test_features |
| 更新を確かめる | 「ヘルプ」→「更新を確かめる」（`chatdraw/updater.py`） | test_chatdraw |
| 固定の制限 | `chatdraw/engine.py` の refused | test_chatdraw |

## README から外したもの

- ユーザーのフィルターの板（「フィルター」の板、`config/filters.json`）: chatdraw/ に入口が無い
- 作画監督の数字の検品と学習の長い説明: アプリの入口は おまかせ の検品だけなので、道具の節に短くまとめた
- 画面の絵（`docs/images/material-slime.jpg` はファイルが無い、`material-kinds.jpg`・`atmosphere-moods.jpg` はアプリに無い道具の絵）。`chatdraw-main.jpg` は AI の欄をタブにする前の画面なので使わない
