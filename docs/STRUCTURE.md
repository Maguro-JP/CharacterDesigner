# 置き場所の決まり

どのセッションも、資料はこの表の置き場にだけ置く。表に無い種類のものを作るときは、先にこの表へ行を足す。
同じ種類のものを 2 か所に置かない（どちらが新しいか分からなくなり、片方だけ直されて食い違った）。

| 置き場 | 置くもの | 置かないもの |
|---|---|---|
| `tools/` `app/` `packaging/` `templates/` | 道具（プログラム、アプリ、配布物の作り方、ほかのリポジトリへ配るひな型） | 絵、知見の文章 |
| `styles/` | 道具が読む数字の決まり（作風、ジャンルの頭身、学んだ基準、模型の癖） | 文章の説明（それは `docs/knowledge/`） |
| `config/` | 利用者ごとの設定の見本（`*.example.json`）と既定 | 利用者の実際の設定（git に入れない） |
| `bible/` | 設定資料集（人物 `characters/`、世界観 `worlds/`）と、その人物の通った絵 | ほかの人物の比べ図 |
| `casts/` | 描く題材の一覧（作品ごとの登場人物、言葉の札、体の設計図、ポーズ、体型、描き分けのパターン） | 絵 |
| `characters/` | 箱庭ドットの職業の部品（`parts.json`、`sprite.json`） | イラストの人物（それは `bible/`） |
| `designs/<作品>/` | 依頼された作品のデザインの決まり（`README.md`）と決定稿の絵 | 道具の知見 |
| `library/` | 見本の絵（`samples/`）、作例集（`book/`）、比べた絵の記録（`progress/`）、職業の一覧の絵（`sheets/`）、日ごとの作例（`daily/`、`women/`） | 参考にした作品の画像（置かない。出典だけを `docs/references.md` に） |
| `docs/` 直下 | 使う人向けの案内（README から辿る文書、`ROADMAP.md`、`STRUCTURE.md`、`models.md`、`references.md`、`record-policy.md`） | 研究のメモ |
| `docs/knowledge/` | 分かったこと（描かせ方、検品、解剖、作画の決まり）と、決めたこと（`decisions.md`、1 か所だけ） | 絵 |
| `docs/knowledge/learning/` | 学習の記録（self-learn） | |
| `docs/knowledge/fashion/` | 流行のファッション資料（10代〜20代を中心に、系統・季節ごとの服・髪・小物・色と出典。入口は `README.md`）。描く言葉の札は `casts/fashion.json`、見本の絵は `library/samples/fashion-*.png` | 実在ブランドの写真や他人の画像（言葉と数字と出典だけ） |
| `docs/reports/` | 日報・週報・月報、確かめたいことの一覧（`pending.md`） | |
| `docs/images/` | README とアプリの案内の画面の絵 | 作例（それは `library/`） |
| `tests/` `tests/fixtures/` | 試験と、試験・精度の測定に使う小さな正解の記録 | 大きな絵（作業場所に置き、記録には道だけ書く） |
| `.worklog/` | 作業中の試行錯誤（git に入れない） | |

作業中の絵（描かせた候補、落ちた絵）は git に入れず、作業場所（scratchpad）に置く。残すのは、見本や比べの記録として選んだ絵だけ。
