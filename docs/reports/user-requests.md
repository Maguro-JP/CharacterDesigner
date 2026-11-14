# 利用者の依頼の一覧（CharacterDesigner のアプリ）

依頼を受けたら、まずこの表に 1 行足し、直したら状態を書き換える。会話の記録は要約で落ちるので、指示はここで管理する。

2026-11-14 に、origin/main（9af2c00e、0.5.28）のコードと試験に照らして全部の行を見直した。
集めた所: `git log --all` の全コミットのメッセージ（マージした PR の題と本文を含む）、CLAUDE.md の「ユーザーの決めたこと」、docs/knowledge/decisions.md、docs/reports/requests-20261113.md、docs/reports/deliverables.md、CHANGELOG.md、.claude/skills/lessons/LESSONS.md、origin の各ブランチにある前の版のこの表。

状態の意味:

- 済み: origin/main のコードと試験に根拠がある（ファイル:行と試験のファイルを書く）
- 一部: コードの一部だけがある、または試験が無い・実機で確かめていない
- 消えた: 前の版にあったのに今の main に無い（消えた版を書く）
- 未着手: コードに根拠が無い
- 作業中: 未マージのブランチがある（ブランチ名。origin に無い手元だけのブランチは「手元のみ」と書く）

見方の限り: 根拠はファイルと語の検索で確かめた。試験は流していない。Windows の実機と GPU では何も確かめていない。

## 数

| 状態 | 数 |
|---|---|
| 済み | 35 |
| 一部 | 80 |
| 消えた | 29 |
| 未着手 | 15 |
| 作業中 | 0（未マージのブランチは、消えた・未着手・一部の行の根拠の欄に書いた。消えた 29 件のうち、origin のブランチで戻す物は 6 件、手元だけのブランチの物は 12 件） |
| 合計 | 159 |

消えた 29 件のうち 23 件は 0.5.23（#409、fca48949）で消えた。0.5.23 は描けなくなった不具合を直すために chatdraw を 0.5.18 に戻し、0.5.19〜0.5.22 で入れた機能のファイル 46 本（autosel.py、lora.py、charafile.py、modes.py、director.py、typeguard.py、batch.py、debuglog.py、persist.py、refs.py、seamfix.py など）と試験をまとめて外した。11-07〜11-08 の依頼（C・B・A の行）のほとんどは、このとき消えた。
戻す作業は origin/claude/FIX-backui-20261114 と、それを取り込んだ origin/claude/FIX-rel529-20261114（0.5.29、未マージ）にある。LoRA・モード・担当編集者・加工の直し・自動選択・チャットと描くワードの分け方を戻すコミットは、手元のブランチ claude/FIX-backchara-20261114 と claude/FIX-backredpen-20261114 にだけあり、origin に push されていない。

なぜ完成しないか（記録から分かること）: 0.5.19〜0.5.22 で一度に多くを足して描けなくなり、0.5.23 で全部を外した。外すときにこの表と照らさなかったので、済んだ依頼が黙って消えた。0.5.24〜0.5.28 は 11-13 の順番の 1〜11 を進めたが、消えた物を戻す作業は未マージのまま残っている。

## 作業の順番（消えた・未着手の物）

壊れていて使えない物を先、頼まれた回数の多い物を先に並べた。回数は、この表・前の版の表・コミットに出た回数（私の数え方）。

| 順 | # | 依頼 | 状態 | 回数 | 理由 |
|---|---|---|---|---|---|
| 1 | A11 | 文字入力中にショートカットに取られない（アプリ全体） | 消えた（0.5.23） | 3 | 急ぎと言われた。打った文字が消える。rel529 にある |
| 2 | N2 | 描くボタンで落ちない（閉じた窓の裏の糸） | 消えた（0.5.23） | 2 | 落ちる。rel529 にある |
| 3 | A12 | 落とさない。メモリの使い方を選ばせる | 消えた（0.5.23） | 3 | 落ちる。rel529 にある |
| 4 | 36 | 進捗のポップアップが出なくなる | 未着手 | 1 | 進みが見えない |
| 5 | 9 | フリーズする言葉がある | 未着手 | 1 | 固まる |
| 6 | 29 | 追加ダウンロードが要る模型が動かない | 未着手 | 1 | 使えない。origin/claude/FIX-partsmodels-20261114 が検品の部品を初回に取る |
| 7 | A1 | 枚数と種をまとめない | 消えた（0.5.23） | 4 | 72・A1・0.5.18・0.5.21 で 4 回。rel529 にある |
| 8 | B5 | マウスの戻る・進む | 消えた（0.5.23） | 2 | rel529 にある |
| 9 | B3 | ライブラリーの右クリックから「一覧から外す」を除く | 消えた（0.5.23） | 1 | 1 行の直し |
| 10 | C1 | AI の自動選択（選択と赤ペン） | 消えた（0.5.23） | 3 | 手元の backredpen のみ |
| 11 | C4 | チャットと描くワードを分ける | 消えた（0.5.23） | 3 | CLAUDE.md の決まりにもある。手元の backredpen のみ |
| 12 | A2〜A5 | ディテール追加・画風を加工のメニューに・拡大の文言・奇麗にする | 消えた（0.5.23） | 2 | 手元の backchara のみ |
| 13 | A13 | LoRA（Civitai・Hugging Face）とキャラクターシート・学習セット | 消えた（0.5.23） | 2 | 手元の backchara のみ |
| 14 | N1 | デバッグモード | 消えた（0.5.23） | 1 | 描けない理由を見るのに要る。rel529 にある |
| 15 | N3 | 模型に本当に渡した言葉をツールチップに出す | 消えた（0.5.23） | 1 | 頼んだ通りに描かない原因を見るのに要る。rel529 にある |
| 16 | A14 | 工程ごとの秒・並べて比べる（Ctrl+Shift+K）・操作を探す（Ctrl+K） | 消えた（0.5.23） | 1 | |
| 17 | B4 | 技能（加工・仕上げ・組み合わせ）が全部効く | 消えた（0.5.23） | 2 | 359 件押した試験（test_function_check）ごと消えた |
| 18 | A7 | プリセットを精査する | 消えた（0.5.23） | 2 | 手元の backchara のみ |
| 19 | C2 | 自動選択の印にも境目の確かめ、加工のあと全体を確かめる | 消えた（0.5.23） | 2 | 手元の backredpen のみ |
| 20 | K5 | 赤ペンの指示の欄の確定のボタン、印の右クリックから囲みの中だけ加工 | 消えた（0.5.23） | 2 | 手元の backredpen のみ |
| 21 | 88 | 参考画像を探させる、参考先を保存 | 消えた（0.5.23、refs.py） | 2 | |
| 22 | K3 | キャラデザモード（設定資料集・三面図・表情差分がそろうまで場面の絵を描かない） | 消えた（0.5.23、charafile.py・modes.py） | 2 | 手元の backchara のみ |
| 23 | 86 | チャットで繰り返し・予定の依頼、アップロードの自動化 | 未着手 | 1 | |
| 24 | 87 | ワードではなく文で依頼・修正・加工 | 未着手 | 2 | 11-14 の fixprompt が直しの訳を作る |
| 25 | 2・13 | 描けるまで描き直す・何回も回す | 消えた（0.5.25） | 4 | 11-13 の順 5（繋げて無限ループにしない）で外した。CLAUDE.md の「工程の数や回数に上限を決めない」と食い違うので、どちらにするか利用者に聞く |
| 26 | 33 | 好みの絵を学習した模型のように使う | 未着手 | 1 | いずれ |
| 27 | 93 | アプリ版とウェブサービス版の準備 | 未着手 | 1 | 後で |

残りの未着手（65・92・K-行の 3 件など）は表の中に書いた。

## 2026-11-14 の決まり（未マージのブランチ）

| # | 依頼 | 状態 | 根拠 |
|---|---|---|---|
| D1 | 基本は性能向上（確認・精査・改善）。機能の追加は指示があったときだけ | 未着手 | origin/claude/FIX-rule-20261114（CLAUDE.md の 1 行。未マージ） |
| D2 | 絵は工程（構図・線画・塗り・仕上げ）に分けて描き、工程ごとに検品して 1 回だけ直す | 未着手 | origin/claude/FIX-flow-20261114（決まり）、origin/claude/FIX-phases-20261114（比べの台）。main のコードに工程分けは無い |
| D3 | 直しの指示（赤ペン・加工）を模型に確実に届ける。訳せない語は黙って描かずに出す | 一部 | main: engine.py の untranslated の知らせ（「模型に伝わらない言葉があります」）。直しの訳は origin/claude/FIX-fixprompt-20261114 |
| D4 | 依頼を受けたらこの表に 1 行足し、直す前に消える機能が無いか照らす | 未着手 | origin/claude/FIX-flow-20261114。0.5.23 はこれをしなかった |
| D5 | 修正依頼の一覧と、模型を使わない整える・揃える・消す | 未着手 | origin/claude/FIX-fixrequests-20261114 |
| D6 | 画風の加工が本物の模型で変わらなかった 7 つを直し、画風を足す | 未着手 | origin/claude/FIX-restyle-20261114 |

## 2026-11-13 の依頼と順番（requests-20261113.md）

| # | 依頼 | 状態 | 根拠 |
|---|---|---|---|
| R1 | 頼みを正確に伝える（勝手に変えない・消さない・足さない） | 一部 | chatdraw/engine.py:1455（vary_background は頼みをそのまま返す、0.5.24）。試験: chatdraw/tests/test_variety.py。adhere-bench（chatdraw/adherebench.py）で前の版と比べた数字は記録に無い。origin/claude/FIX-noextra-20261114 が 2 段の構図の足し言葉を外す（未マージ） |
| R2 | 直しをまともに（赤ペン修正のバグ、赤ペンのレイヤーを履歴に載せない） | 一部 | chatdraw/layerpanel.py:124-235（印ごとの行、消す・全部消す）、chatdraw/redpen.py:98（元に戻す）。試験: test_redpenfix.py、test_redpeninput.py。履歴に載せない・消したら何も残さない（0.5.22）は 0.5.23 で消え、手元の backredpen のみ |
| R3 | 加工をまともに | 一部 | chatdraw/finishers.py。試験: test_finish_quality.py、test_nobreak.py。0.5.22 の直し（A2〜A5）は消えた |
| R4 | 「描けませんでした」と出さない | 一部 | engine.py:105（メモリ不足で 1 回だけ設定を下げてやり直す）。0.5.22 の段を下げて描き続ける形は消えた |
| R5 | 検品と直しを個別に動かす（繋げて無限ループにしない） | 済み | chatdraw/engine.py:1793（REDRAW_TRIES = 1）、engine.py:1583-1585 の注。0.5.25。試験: test_qcmanual.py |
| R6 | 検品単体の精度を上げる | 一部 | chatdraw/tests/test_qcbench.py、0.5.28（人の判定 103 枚で取りこぼし無しの割合 93.2% → 95.1%）。origin/claude/FIX-qcaccuracy2-20261114 が台を直す（未マージ） |
| R7 | 検品の手動実施（右クリック、人が描いた絵にも、結果を赤ペンで） | 済み | chatdraw/qcmanual.py、0.5.25。試験: chatdraw/tests/test_qcmanual.py |
| R8 | 赤ペンで指示が無いときは範囲を検品して直す | 済み | chatdraw/app.py:2284。試験: test_qcmanual.py |
| R9 | 正確な図形のアシスタント、AI 補正、線対称・点対称 | 済み | chatdraw/canvas.py:28（対称）、commands.py:111（正多角形）、0.5.26・0.5.27。試験: test_layertools.py、test_shapeassist.py、test_brushtools.py。「AI 補正」は形を整える補正（模型は使わない） |
| R10 | レイヤーのコピー・切り取りなど | 済み | chatdraw/canvas.py:441（copy_layer）、0.5.26。試験: test_layertools.py |
| R11 | 芸術の知識を調べてアルゴリズムに（迫力なら遠近法など） | 一部 | chatdraw/composition.py、engine.py:1546。試験: test_composition.py。構図の言葉を足すだけで、ほかの知識は無い |
| R12 | 急ぎ、加工と直しが出来る版を Release | 一部 | 0.5.24〜0.5.28 を CHANGELOG.md に書いた。Release が出たかは GitHub で見ていない |

## CLAUDE.md「ユーザーの決めたこと」のうち、アプリの機能になる物

作業の進め方の決まり（PR の前に聞く、散らかさない、日本時間で書く など）はコードでは測れないので、この表には入れていない。フックがあるもの（pr_gate.py、reread_check.py、precheck.py、docs_check.py、measure_hooks.py）は .claude/skills/ の下にある。

| # | 依頼 | 状態 | 根拠 |
|---|---|---|---|
| K1 | AI の欄の「指示」のタブを、模型・描くワード・登録・禁止ワード・登録の順に詰めて並べ、登録のボタンは折り返す | 一部 | chatdraw/aipanel.py:139-149、chatdraw/wordpanel.py:90（FlowLayout）。並びの順を確かめる試験は見つけていない |
| K2 | 赤ペンの印をレイヤーの欄に「赤ペン」として出し、隠す・全部消す・1 つずつ消す・元に戻す・やり直す | 一部 | chatdraw/layerpanel.py:124-235、chatdraw/redpen.py:32、98。試験: test_redpenfix.py。隠すの試験は見つけていない |
| K3 | キャラデザモードで設計し、そろうまで場面の絵を描かない | 消えた | 0.5.23 で modes.py・charafile.py が消えた。chatdraw/charadesign.py は残る。手元の backchara のみ |
| K4 | AI の結果は一番上の新しいレイヤーに置いて選ぶ | 済み | chatdraw/app.py:5180、finishers.py:184。試験: chatdraw/tests/test_toplayer.py |
| K5 | 赤ペンの指示の欄に確定のボタン、印の右クリックから囲みの中だけ加工 | 消えた | 0.5.22 で入れ、0.5.23 で消えた。手元の backredpen のみ |
| K6 | 赤ペンのレイヤーを消したら、絵・履歴・ライブラリー・作業の保存に何も残さない | 消えた | 0.5.22 で入れ、0.5.23 で消えた（workkeep.py、persist.py）。手元の backredpen のみ |
| K7 | 描く前に止めるのは子どもを性的に描く頼みだけ（childsafe.py の 1 か所） | 一部 | chatdraw/childsafe.py、engine.py:381。専用の試験 test_childsafe.py は 0.5.23 で消えた |
| K8 | 日本語の頼みを、そのまま絵の模型に渡さない | 一部 | chatdraw/jaterms.py、engine.py の untranslated の知らせ。試験: test_words.py、test_chatplan.py。全部の経路は確かめていない |
| K9 | 新しく描いた絵はキャンバスを置き換え、頼んだ言葉を履歴に残す | 一部 | chatdraw/app.py:3457（履歴から頼みを戻す）。試験: test_chatdraw.py。置き換えの試験は見つけていない |
| K10 | 描くのも直すのも、工程の数や回数に上限を決めない | 消えた | 0.5.19 で上限をなくし、0.5.25 で描くのを 1 回にした（engine.py:1793）。R5 と食い違う |
| K11 | 模型の評価は数値 1 つ、推奨は点の順、タグで探す、点の届いた物だけ推奨、削除は管理画面で選んだときだけ | 済み | chatdraw/manager.py:7-8、313、chatdraw/ratings.py。試験: test_folders_ratings.py、test_modelblock.py |
| K12 | 全部の機能の精度を数字で測って上げ続け、前と後の数字を docs/knowledge/ に残す | 一部 | 検品だけ（test_qcbench.py、docs/knowledge/accuracy.md）。自動選択は消えた。ほかの機能の台は無い |
| K13 | 描く言葉・打ち消し・既定・検品に触る変更は adhere-bench で前の版と比べる | 一部 | chatdraw/adherebench.py。0.5.24〜0.5.28 で比べた数字は CHANGELOG と docs/knowledge に見つけていない |
| K14 | 入れた機能はアプリから押して最後まで動くか確かめてから出す | 消えた | 359 件を押す試験（test_function_check.py、test_menuaudit.py）が 0.5.23 で消えた |
| K15 | 実在の道具は調べてから描く | 未着手 | 描く仕組みに調べる工程は無い（docs/knowledge の記録だけ） |

## 0.5.23 で消え、前の版の表にあった行

| # | 依頼 | 状態 | 根拠 |
|---|---|---|---|
| N1 | デバッグモード（記録の欄、例外の全文、制限を外す項目） | 消えた | 0.5.20 で入れ、0.5.23 で debuglog.py ごと消えた。origin/claude/FIX-rel529-20261114（e69dd852）で戻す |
| N2 | 描くボタンで落ちない（閉じた窓の裏の糸、アプリ全体のキー） | 消えた | 0.5.22 で直し、0.5.23 で消えた。rel529（b7f1baef）で戻す |
| N3 | 模型に本当に渡した言葉を、頼みの欄とチャットの欄のツールチップに出す | 消えた | 0.5.20 で入れ、0.5.23 で sent.py ごと消えた。rel529（c03fcdc8）で戻す |

## 11-07〜11-08 の依頼

| # | 依頼 | 状態 | 根拠・担当 |
|---|---|---|---|
| C1 | AI の自動選択（選択と赤ペン）。丸・四角・全選択・自動選択の赤ペン | 消えた | 0.5.22 で入れ、0.5.23 で autosel.py ごと消えた。手元の claude/FIX-backredpen-20261114（9857c60e、origin に無い） |
| C2 | 自動選択の印にも境目の確かめを通し、加工のあとは全体を確かめる | 消えた | 0.5.23 で seamfix.py が消えた。手元の backredpen のみ |
| C3 | 自動選択を含め、全部の機能の精度を上げ続ける | 一部 | K12 と同じ |
| C4 | チャットは言語の模型への指示、描くワードは描画の模型への設定として分ける | 消えた | 0.5.22 で入れ、0.5.23 で chatwords.py・chatintent.py が消えた。手元の backredpen（9b834552）のみ |
| C5 | 描く前に止めるのは子どもを性的に描く頼みだけ | 一部 | K7 と同じ |
| B1 | 前の版より絵の質が下がった。好みは質にだけ効かせる | 一部 | 0.5.24 で足す言葉を止めた（engine.py:1455）。好みの効かせ方の 0.5.22 の直しは消えた。origin/claude/FIX-noextra-20261114（未マージ） |
| B2 | 効いていないフィルターを直すか外す | 一部 | docs/knowledge/filter-audit.md。0.5.24 で決まり文句と打ち消しを外した。試験は見つけていない |
| B3 | ライブラリーの右クリックから「一覧から外す」を除く | 消えた | 0.5.22 で除き、0.5.23 で戻った。今も chatdraw/librarypanel.py:157 にある |
| B4 | 技能（加工・仕上げ・組み合わせ）が全部効くようにする | 消えた | K14 と同じ。手元の backchara（163a1865）のみ |
| B5 | マウスの戻る・進むボタン | 消えた | 0.5.22 で入れ、0.5.23 で消えた（main に BackButton の扱いが無い）。origin/claude/FIX-backui-20261114、rel529 |
| B6 | 絵に矛盾が無いように、まともに効く検品 | 一部 | chatdraw/qcmanual.py、test_qcmanual.py、test_qcbench.py。0.5.22 の矛盾の検品（test_qc3.py）は消えた |
| A1 | 枚数と種をまとめない。枚数の入力欄 | 消えた | 描くボタンの左の作成枚数の欄はある（app.py:683-686）。詳しい設定はまだ「枚数と種」の 1 つの見出し（aipanel.py:195）。0.5.23 で戻った。rel529（2a67255a） |
| A2 | ディテール追加が効かない | 消えた | 0.5.22 の直し（変わりの平均 0.79 → 1.84）が 0.5.23 で消えた。手元の backchara のみ |
| A3 | 画風を加工のメニューに入れる | 消えた | メニューバーに「加工」が無い（app.py:816-1285）。手元の backchara のみ |
| A4 | 拡大の文言を直す | 消えた | 0.5.22 の文言が 0.5.23 で消えた。手元の backchara のみ |
| A5 | 奇麗にするを直す（崩さない・速く） | 消えた | 0.5.22（4 枚で 93〜114 秒 → 50〜65 秒）が 0.5.23 で消えた。手元の backchara のみ |
| A6 | 右クリックメニューを編集できるようにする | 一部 | chatdraw/menuedit.py はメニューと帯の編集だけで、右クリックの編集は 0.5.23 で消えた。手元の backchara（3afbf4e9）のみ |
| A7 | プリセットを精査する | 消えた | 0.5.22 のまとめが 0.5.23 で消えた。手元の backchara のみ |
| A8 | チャットを有効活用する（チャットで描く・直す・加工・設定を変える） | 一部 | chatdraw/chatplan.py、app.py:2082（枚数を読む）。試験: test_chatplan.py |
| A9 | 訳の分からない制限で「描けませんでした」にしない | 一部 | R4 と同じ。止めるのは childsafe.py だけ |
| A10 | 頼んだ指示を模型が無視しない | 一部 | R1 と同じ |
| A11 | 文字入力中にショートカットに取られない | 消えた | 赤ペンの指示の欄だけは守る（test_redpeninput.py）。アプリ全体の typeguard.py は 0.5.23 で消えた。rel529（5cd8ea1d） |
| A12 | 落とさない。メモリの使い方を選ばせる | 消えた | membudget.py に MODES が無い（置き方の選択 PLACEMENTS だけ）。0.5.23 で消えた。origin/claude/FIX-backui-20261114（352ca7cd） |
| A13 | キャラクターシートと LoRA、学習セット、Civitai・Hugging Face から取る | 消えた | 0.5.23 で lora.py・loradialog.py が消えた。残るのは自分の作風の LoRA の入口（ownstyle.py、test_ownstyle.py）。手元の backchara（2932633f）のみ |
| A14 | ComfyUI を参考に見やすい画面（工程ごとの秒、並べて比べる、操作を探す） | 消えた | 0.5.20 で入れ、0.5.23 で消えた（test_comfyui_ui.py ごと） |
| A15 | 作画監督を早く完成させる | 一部 | R6 と同じ |
| A16 | 機能が足されたら Release、急ぎの直しは急いで Release | 一部 | R12 と同じ。0.5.29 は未マージ |

## 描く（10-25〜10-31）

| # | 依頼 | 状態 | 根拠 |
|---|---|---|---|
| 1 | 頼んだ通りの絵を描かせる | 一部 | engine.py:1455、1461（emphasize）。R1 と同じ。実際の模型で効くかは確かめていない |
| 2 | 手足・目など細かい所をきちんと描く。描けるまで描き直す | 消えた | 描き直しは 0.5.25 で外した（engine.py:1793、REDRAW_TRIES = 1）。11-13 の順 5 に従った。直すのは手で呼ぶ検品と赤ペン |
| 3 | 質が先。時間をかけてよいので奇麗で正しい絵 | 一部 | chatdraw/twostage.py。工程分け（D2）は未マージ |
| 4 | 頼んでいない物を描かせない | 一部 | engine.py:1567-1572（頼んでいない物を描かない物に足す）。描き直しが 1 回になったので次の回が無い。試験: test_variety.py |
| 5 | 標準的な体型で描く | 一部 | chatdraw/body.py、bodycheck.py。試験名は確かめていない |
| 6 | 背景がワンパターンで魅力が無い | 消えた | vary_background は 0.5.24 で頼みをそのまま返すようにした（engine.py:1455）。R1 に従った |
| 7 | 日本語の頼みをそのまま絵の模型に渡さない | 一部 | K8 と同じ |
| 8 | 3D のキャラデザも出来るようにする | 一部 | chatdraw/to3d.py（入口だけ）。試験: test_features.py |
| 9 | フリーズする言葉がある | 未着手 | 原因の言葉の記録が無い |

## 検品

| # | 依頼 | 状態 | 根拠 |
|---|---|---|---|
| 10 | 手・足の指の数を数える | 一部 | tools/gen/hands.py の count_fingers。小さな絵ではほとんど数えられない |
| 11 | 検品で崩れを逃がさない。読めない絵は崩れとして扱う | 一部 | 0.5.28 で片目の隠れを足した（test_qcbench.py）。0.5.22 の「検品できなかった物も崩れ」は消えた |
| 12 | AI の不出来な絵を AI 自身が直す | 一部 | 赤ペンの直しと app.py:2284（指示の空の囲みを検品して 1 回直す）。自動では直さない（0.5.25） |
| 13 | 模型とのやり取りを 1 回で終えず何回も回す | 消えた | 0.5.25 で 1 回にした（engine.py:1793）。K10 と同じ食い違い |
| 14 | モデルの外の処理を引き続き開発する | 一部 | 0.5.26〜0.5.28 |

## 模型

| # | 依頼 | 状態 | 根拠 |
|---|---|---|---|
| 15 | 優秀な絵画モデルを早急に用意 | 一部 | chatdraw/catalog.json。目録の見直しは origin/claude/FIX-partsmodels-20261114（未マージ） |
| 16 | 動かせるモデルをまとめて GitHub に載せる | 済み | chatdraw/help/install.md、chatdraw/modeldoc.py。試験: test_modeldoc.py |
| 17 | 模型のダウンロード先と導入方法 | 済み | chatdraw/help/install.md。試験: test_modeldoc.py |
| 18 | 模型を精査し、選択肢を増やす | 一部 | chatdraw/manager.py、hfadd.py。実際に動かした点が足りない |
| 19 | 評価は数値 1 つ、都度見直し、推奨をソート | 済み | chatdraw/ratings.py、manager.py:7。試験: test_folders_ratings.py |
| 20 | タグで管理 | 済み | chatdraw/manager.py、ratings.py。試験: test_folders_ratings.py |
| 21 | 評価の低い模型を推奨に出さない | 済み | chatdraw/models.py。試験: test_chatdraw.py |
| 22 | 取得済みの模型は表示する | 済み | chatdraw/manager.py:8、237。試験: test_modelmgr.py |
| 23 | 取得済みを一覧の上に | 済み | chatdraw/manager.py:8（手元にある模型はどの絞り込みでも先頭）。試験: test_modelmgr.py（前の版では未着手） |
| 24 | ★でお気に入りの模型 | 済み | chatdraw/manager.py:8（その中で ★ を先に）、paths.py:133（favorites.json）。試験: test_modelmgr.py |
| 25 | 使いたくない模型を非表示 | 済み | chatdraw/manager.py:311-329（set_hidden）。試験: test_modelblock.py |
| 26 | メニューの AI に使える模型が更新される | 済み | chatdraw/app.py（開くたびに作り直す）。試験: test_chatdraw.py |
| 27 | おまかせが機能していない | 一部 | chatdraw/omakase.py、choose.py。試験: test_omakase.py。「機能していない」原因は記録に無い |
| 28 | 世間の評価の高い模型を優先して評価試験 | 一部 | chatdraw/popular.py（config/verify-models.txt を人気順に書く）。試験: test_chatdraw.py。Actions が使っているかは確かめていない |
| 29 | 追加ダウンロードが要る模型が動かない | 未着手 | main に根拠無し。origin/claude/FIX-partsmodels-20261114 |
| 30 | 大容量の模型も動くように | 一部 | chatdraw/membudget.py:34（置き方 4 つ）。実機で確かめていない |
| 31 | 模型によって絵が描けなくなる | 一部 | 0.5.23 で 0.5.18 に戻した。GPU で確かめていない |
| 32 | 高性能な言語模型の方が時間がかかる | 一部 | engine.py:443（同じ模型は読み直さない） |
| 33 | 好みの絵をオリジナルの学習モデルのように使う | 未着手 | ownstyle.py は ★ の絵を集める入口だけ。学習は無い |

## UI

| # | 依頼 | 状態 | 根拠 |
|---|---|---|---|
| 34 | 全体的に使いやすく。優れた UI を学ぶ | 一部 | docs/knowledge/ui-design.md、chatdraw/layouts.py |
| 35 | 進みはポップアップに | 済み | chatdraw/notice.py。試験: test_chatdraw.py、test_confirm.py |
| 36 | 進捗のポップアップが出なくなる不具合 | 未着手 | 再現と直しの記録が無い |
| 37 | ボタンの説明はツールチップに。AI タブは枠を取りすぎない | 済み | chatdraw/aipanel.py（setToolTip 21 か所）。試験: test_aiui.py |
| 38 | 右ボタンでつかんで動かす。右クリックの機能を充実 | 済み | chatdraw/canvas.py。試験: test_chatdraw.py（RightButton） |
| 39 | カーソルが邪魔にならない | 一部 | chatdraw/layouts.py、canvas.py。試験名は確かめていない |
| 40 | 描いたあと新しい絵が出ない。表示の選択・固定・解除 | 一部 | chatdraw/app.py。試験名は確かめていない |
| 41 | 完成した絵が表示されない | 一部 | 試験: test_uifix.py。本物の模型で確かめていない |
| 42 | デフォルトのプリセット、リセット | 一部 | chatdraw/aipanel.py。試験: test_presetui.py。リセットの試験は確かめていない |
| 43 | スクロールでシード値などが変わる | 済み | chatdraw/wheelguard.py、app.py:576。試験: test_presetui.py |
| 44 | ツアーなどでフリーズする | 一部 | chatdraw/tour.py、tours.py:112（5 枚まで）。試験: test_freeze.py。Windows で確かめていない |
| 45 | フリーズのあと 1 度正しく閉じないと戻らない | 済み | chatdraw/app.py:254（crashed_before）。試験: test_chatdraw.py |
| 46 | 全体表示のタブに表示領域、動かせる | 済み | chatdraw/app.py:355（view_rect）。試験: test_presetui.py |
| 47 | 模型の管理が開けない | 一部 | 試験: test_modelmgr.py。CUDA 版の Windows では確かめていない |
| 48 | 関係するディレクトリを開くボタン | 一部 | chatdraw/folders.py:27、app.py:829。試験: test_folders_ratings.py にあるかは確かめていない |
| 49 | 増えた機能はプルダウンで整理 | 一部 | chatdraw/layerpanel.py、aipanel.py |
| 50 | 音声入力 | 一部 | chatdraw/voice.py。試験: test_voicechat.py。本物のマイクでは確かめていない |

## チャット

| # | 依頼 | 状態 | 根拠 |
|---|---|---|---|
| 51 | チャットの下に頼んだ言葉の履歴 | 済み | chatdraw/app.py。試験: test_chatdraw.py |
| 52 | お気に入りの言葉・指示を固定・保存 | 済み | chatdraw/app.py:698、721。試験: test_keepsettings.py |
| 53 | チャットとして使えるよう設計 | 一部 | chatdraw/chatpanel.py。試験: test_uifix.py |
| 54 | 描く言葉の指示を AI タブに統合、禁止ワードの欄 | 済み | chatdraw/aipanel.py:147-149、283。試験: test_aitabs.py |

## レイヤー

| # | 依頼 | 状態 | 根拠 |
|---|---|---|---|
| 55 | 真ん中の画像が重なる | 済み | chatdraw/app.py:5180（一番上の新しいレイヤーに置く）。試験: test_toplayer.py |
| 56 | レイヤーの使い方が意図した動きでない | 一部 | chatdraw/layerpanel.py、canvas.py。試験: test_layertools.py、test_layercrash.py。利用者が使って確かめていない |

## ライブラリ

| # | 依頼 | 状態 | 根拠 |
|---|---|---|---|
| 57 | ライブラリが開けなくなった | 済み | 試験: test_uifix.py |
| 58 | 履歴から SNS 連携 | 一部 | chatdraw/share.py。試験: test_features.py。Windows で確かめていない |
| 59 | タイムラプス、録画・GIF | 一部 | chatdraw/timelapse.py。試験: test_works.py、test_features.py |

## リリースと検証

| # | 依頼 | 状態 | 根拠 |
|---|---|---|---|
| 60 | Setup.exe を組む | 済み | .github/workflows、packaging。CHANGELOG.md 0.5.x |
| 61 | Windows を主に検証する | 一部 | chatdraw/windraw.py。実機は利用者待ち |
| 62 | 土日に実機で確かめるので、動く物をリリース | 一部 | 0.5.28 が実機で動くかは確かめていない |
| 63 | Actions を並列で使い、待たずに開発を進める | 一部 | 運用の決まり |
| 64 | リリースと Actions にゴミを残さない | 一部 | 未マージの FIX-*-20261114 のブランチが 19 本ある（rel526〜rel528 はマージ済みで残っている） |

## その他

| # | 依頼 | 状態 | 根拠 |
|---|---|---|---|
| 65 | バグだけでなく設計を見直す | 未着手 | 設計の見直しの文書が無い。0.5.23 で一度に外したことが、設計を見直さずに戻した例 |
| 66 | 遅い原因を調べて直す | 一部 | engine.py:143（bf16 を測る）。0.5.21 の 18 倍の遅れの直しは 0.5.23 で消え、backui で戻す |
| 67 | 未実装の機能を全部やる | 一部 | この表 |
| 68 | その他のバグも直す | 一部 | 一覧が無い |

## 11-06 の依頼

| # | 依頼 | 状態 | 根拠 |
|---|---|---|---|
| 69 | 赤ペンの項目ごとにレイヤー、指示はそのレイヤーのコメント | 済み | chatdraw/layerpanel.py:124-128（「赤ペン n: 指示」の行）。試験: test_redpenfix.py |
| 70 | 赤ペンの直しを右クリックからも | 一部 | chatdraw/app.py:3137、3205（右クリックから囲む道具へ）。右クリックから直しを掛けるのは 0.5.23 で消えた（K5） |
| 71 | レイヤーの重ね順（透明、AI の絵、足したレイヤーと赤ペン） | 一部 | layerpanel.py:124（赤ペンは一番上）。透明のレイヤー 1 の試験は見つけていない |
| 72 | 描く枚数を指定する欄 | 済み | chatdraw/app.py:683-686（count_spin）。試験: test_aitabs.py |
| 73 | レイヤーを消したら、そのレイヤーの絵も消す | 済み | chatdraw/canvas.py:615（delete_layer）。試験: test_canvasfix.py、test_uifix.py |
| 74 | レイヤーごとの保存 | 済み | chatdraw/project.py:3（zip の中にレイヤーごとの PNG）、app.py:5358（PSD）。試験: test_canvasfix.py。ORA は 0.5.23 で消えた |
| 75 | 絵を日付のディレクトリに分けて置く | 一部 | chatdraw/app.py:2533（日付のディレクトリ）。描いた絵の置き場の全部の経路かは確かめていない |
| 76 | 加工の精度を上げ、崩れを防ぎ、崩れを検品 | 一部 | 試験: test_nobreak.py（目と髪の色が変わったら戻す） |
| 77 | 拡大した後の加工が重くて止まる | 一部 | finishers.py:557、573（tiled、at_work_size）。試験: test_finish_big.py |
| 78 | 加工を直感的に、組み合わせをお気に入りに | 一部 | finishers.py:1064（組み合わせを順に掛ける） |
| 79 | アプリのウィンドウにもテーマ | 済み | chatdraw/themes.py:288、app.py:1609。試験: test_menuedit.py |
| 80 | メニューの最適化・表示の編集・並べ替え | 一部 | chatdraw/menuedit.py、app.py:4343。試験: test_menuedit.py |
| 81 | リボンの最適化・並べ替え・区切り・固定 | 一部 | chatdraw/ribbon.py。試験: test_viewtools.py |
| 82 | メニューとタブで共通の項目は同じ機能、タブで右クリック | 一部 | chatdraw/commands.py |
| 83 | よく使う物はボタンに | 一部 | chatdraw/layouts.py |
| 84 | ブラシのデモ表示 | 済み | chatdraw/brushpreview.py、app.py:1014。試験: test_brushtools.py |
| 85 | 特殊な色、カラーパレット、描く道具の充実 | 一部 | chatdraw/colorpanel.py、0.5.26〜0.5.27 の道具。palette.py は 0.5.23 で消えた |
| 86 | チャットで繰り返しや予定の依頼、アップロードの自動化 | 未着手 | chatdraw/scheduler.py は模型の scheduler の設定で、予定の依頼ではない |
| 87 | ワードではなく文で依頼・修正・加工 | 未着手 | main に根拠無し。origin/claude/FIX-fixprompt-20261114 が直しの指示の訳を作る |
| 88 | 参考画像を探させる、参考先を保存 | 消えた | 0.5.23 で refs.py が消えた。参考画像を使う欄（aipanel.py:224）は残る |
| 89 | プリセットの充実 | 一部 | chatdraw/aipanel.py:18 |
| 90 | 多言語に対応 | 一部 | chatdraw/i18n.py:15。試験: test_usability.py |
| 91 | 全ての文言を見直す | 一部 | 0.5.18 以降の直しだけ |
| 92 | 今までのフィードバックを活かす | 未着手 | 0.5.23 で前のフィードバックの直しが消えた |
| 93 | アプリ版とウェブサービス版の準備 | 未着手 | 後で |
| 94 | その他のバグを見つけて直し、最適化を進める | 一部 | 0.5.26（ロック・非表示のレイヤーが変わっていた直し） |

## 成果物（deliverables.md）

| # | 依頼 | 状態 | 根拠 |
|---|---|---|---|
| E1 | アプリのウィンドウで起動する CharacterDesigner | 一部 | deliverables.md は app/start.sh と app/launch.py を挙げるが、app/ は #381（e508cf29）で外れ、今は chatdraw のアプリ。deliverables.md の完成条件が今のリポジトリに合っていない |
| E2 | 仕事の進み具合の表示（経過と何回目か） | 消えた | 0.5.20 の工程ごとの秒（A14）が 0.5.23 で消えた。描いています（i/n）の知らせだけ残る（engine.py:1580） |
