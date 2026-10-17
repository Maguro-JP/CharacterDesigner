# 置き場所の表

何をどこに置くか。新しい種類の資料を足すときは、先にこの表に行を足してから置く（同じものが2か所に分かれないようにするため）。

| 置き場所 | 置くもの |
|---|---|
| `tools/` | 道具（描く・検品する・加工する処理）。`tools/gen/` が画像生成と検品 |
| `styles/` | 作風の決まりを数字で持つ JSON |
| `casts/` | 設定集（`tools/gen/design.py batch` で描く人物の一覧と描く言葉） |
| `library/` | 描いて確かめた描き分けのパターンと見本の絵（`library/samples/`） |
| `bible/` | 設定資料集（キャラクターと世界観） |
| `characters/` | 箱庭ドットの職業の部品 |
| `config/` | 設定の見本。利用者ごとの設定は git に入れない |
| `docs/ROADMAP.md` | 予定表 |
| `docs/references.md` | 出典（作品名、記事、ページ）と道具の許諾 |
| `docs/record-policy.md` | 記録に書くもの・書かないものの基準 |
| `docs/knowledge/` | 分かったこと。決めたことは `docs/knowledge/decisions.md`、描かせて分かったことは `docs/knowledge/ai-drawing-notes.md` |
| `docs/knowledge/learning/` | 身につけるために調べたこと（self-learn の記録） |
| `docs/knowledge/fashion/` | 流行のファッション（10代〜20代を中心に、系統・季節ごとの服・髪・小物・色。入口は `README.md`）。描く言葉の札は `casts/fashion.json`、見本の絵は `library/samples/fashion-*.png` |
| `docs/reports/` | 日報・週報・月報と判断待ち |
| `tests/` | 試験 |
| `.worklog/` | 作業中の生の記録（git に入れない） |
