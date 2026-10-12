---
name: character-design
description: 「○○なキャラクターを作って」「○○風のキャラクターデザインを作って」「この作風で描いて」「新しい職業を足して」「ドット絵にして」「リアル風にして」と言われたとき、このリポジトリでキャラクターデザインを出すときに使う。まずアニメ風のデザインを画像生成で描いて見せ（tools/gen/design.py draw）、派生（リアル風、ドット絵、3D）は指示を受けてからその絵から作る。箱庭ドットの職業を部品で組む作業（styles/*.json、characters/*/parts.json、tools/build.py）もここ。描画器そのものを直す作業には使わない。
---

# キャラクターデザイン

「本当にその作風だ」と言える水準で出す。数字が通っただけで良しとしない。

## やってはいけないこと

方針として決めたことをまとめる。破ったら見せる前に直す。

見せ方
- 指定していない変化（服・色・付け足し・画風）が出た絵を「できた」と言わない
- 背景を描かない。背景は無地。背景の物（動物・家具など）が残った絵は見せない
- 生き物として破綻した絵（くちばし2つ、足が途切れる、指の崩れ）は見せる前に落とす
- 不気味に見える絵（写実の顔の 3D、白目だけの目など）は見せない
- 正面と背面で色や形が食い違うものを1体として出さない
- 特徴（耳・尾・翼・角・肌）がどこに付いているか分からない絵は通さない
- 亜人は `docs/knowledge/demihuman-anatomy.md` の決まりで見る（獣耳なら人の耳を描かない、尾は尾骶骨、翼は肩甲骨から）

描き方
- モンスターを人型にしない（擬人化は頼まれてから）
- 男女を中性的に寄せない。男女は骨格から描き分ける
- 同じ一覧の中で、一部（老人など）だけ別のモデル・別の画風で描かない
- 図形の部品（SVG など）でキャラクターを組まない
- 既存のキャラクターを写さない。そっくりに寄せる指示を使わない
- 写実の 3D は当面作らない

残し方
- 参考にした作品の画像をリポジトリに置かない。作品名は `docs/references.md` だけに書き、README と PR には出さない
- 数字が通っただけで良しとしない。必ず画像を目で見て判定する
- 分かったことを会話だけに置かない。`docs/knowledge/` と決定の記録に書く

## 女性キャラクターの基準の体

女性を描くときは、利用者が決めた体のベース `ideal` を使う（`library/body-types.json` の anime.ideal、見本 `library/samples/anime-ideal-female.png`）。
`PYTHONPATH=.cache/gen/lib python3 tools/gen/people.py card <出力> <名前> --gender female --base ideal --tags "<種族や特徴>"`
体型を変えるよう頼まれたときだけ、ベースの言葉を変える。

## 亜人（角・獣耳・翼・尾）を描く

「狐娘を作って」「サキュバスを描いて」のように亜人を頼まれたら、この流れで最後まで進める。
言葉だけで描くと、尾の付け根や向きごとの部品の有無が揃わない（6種中0種）。3D の素体を下絵にする `tools/gen/demi.py` を使う。

1. 種の設定を自分で書く（聞き返さない）。`casts/demi3d.json` の cases に1件足す
   - parts: 3D の部品を形の名前で選ぶ。ears: cat / fox / rabbit、tail: cat / fox / devil / rabbit、wings: bat / feather、horns: devil
     - color で部品ごとの色（`{"ears": "#c8682a", "tail": "#c8682a"}`）。描く色と下絵の色を合わせる（下絵の色が絵に効く）
     - 無い形が要るときは `tools/engine/viewer/vrm-base.html` の PART_LIB に足す。付け根は骨に付くので、形を作るだけでよい
   - tags: 種と部品を英語のタグで（例: "fox girl, orange fox ears, large fluffy orange fox tail"）
   - hair: 髪の色と目の色。hair_3d を "hide" にすると下絵の髪を隠し、髪型を hair の言葉で決める（既定は下絵のツインテール）
   - negative: 頼んでいない部品（作り物の耳、余分な尾、頼んでいないとがった耳）
   - anatomy: 体の決まりの指示（animal_ears / tail / wings）
   - strength: 翼のある種は 0.5（0.6 だと斜め前を後ろ向きに描き直した）。他は既定の 0.6
2. 初回だけ `python3 tools/gen/demi.py setup`（素体と表示の部品を `.cache/engine/vrm` に取る。約 20 秒）
3. `PYTHONPATH=.cache/gen/lib python3 -u tools/gen/demi.py run <名前> <出力>` を裏で走らせる（run_in_background）
   - 下絵 約20秒、1回 約3分、初回はモデルの読み込みに約10分。待つ間の報告も日本語で書く
4. 機械の検品の結果（`report.json`、各回の `try-N-inspect.png` の ○×）を見る。3回とも落ちたら、落ちた理由から直す
   - 部品が消えた → 下絵の部品を太く・大きく、または strength を下げる
   - 余分な部品が出た → negative に足す
   - 向きが変わった → strength を下げる
5. 通った絵を、`docs/knowledge/demihuman-anatomy.md` の項目で目で見る（人の耳が残っていないか、頼んでいないとがった耳、付け根、色の食い違い）
6. 目で通ったものだけを見せる。`library/samples/demi3d-<名前>.png` に置き、分かったことを `docs/knowledge/demihuman-anatomy.md` に足す

## 完成の1枚絵（背景つき）を頼まれたとき

基準は利用者の目: デザインとの一致より、絵として整っていること（矛盾・あり得ない形が無い、背景が作り込まれている）。
頼まれていない基準を自分で足さない。前の周で良かった要素（ポーズ、構図）は引き継ぐ。決まりと分かったことは `docs/knowledge/illustration.md`。

`PYTHONPATH=.cache/gen/lib python3 tools/gen/layers.py <人物の絵> <出力> --scene "<背景の言葉>" --light front|left|right|back --blend 0.5 --prompt "<人物の言葉>"`
- 人物と背景を別々に作って重ねる。大きさは地平線から遠近で決まる。足元（水・濡れた面・花や草・地面）は自動で判定する
- 出力: layers.psd（Photoshop・CLIP STUDIO）、composite.png（重ねただけ）、final.png（輪郭と足元をなじませた1枚）、layers.json（検品の数字）
- 見せる前に final.png を拡大して目で見る: 人物の周りの白、境界線、水の無い所の映り込み、手前の物より前に出た人物、手足の形

## 0. 頼まれたときの流れ

1. まずアニメ風のデザインを描いて見せる。種を変えて数枚出し、選んでもらう
   `PYTHONPATH=.cache/gen/lib python3 tools/gen/design.py draw out.png "<人物の説明（英語）>" --n 4`
   （初めての環境では `sh tools/gen/setup.sh`。CPU で1枚 約1分）
2. 後の加工は指示を受けてから、選ばれたイラストから作る。文章から作り直さない（同じ人物を保つため）。
   デザインそのものは常にイラストで決める。加工は出来上がったデザインに掛けるオプションで、リアル風は優先度が最も低い
   - デフォルメ・ちびキャラ: 未実装（`docs/ROADMAP.md` の 11）
   - ドット絵（等身を保つ少ない色）: `design.py pixel in.png out.sprite.json --preset survivor`
   - モンスターのドット絵（解像度高め、標準）: `design.py pixel in.png out.sprite.json --preset monster96`
   - 箱庭ドット: 頭を大きくする変換が要る（未完成）。部品で組む場合は下の 1〜3
   - 3D: `tools/engine/`（Blender＋MakeHuman、試作）
   - リアル風（優先度は最低）: `design.py restyle in.png out.png --style real`
3. 出したものは画像で見せる。並べた図は `tools/vsref.py`、ドット絵の数字は `tools/check.py` と `tools/learn.py score`
4. 三面図・持ち物の持ち方・決まった姿勢は、言葉だけで描かない。人形の下絵から描く
   （言葉だけでは横が斜め前、後ろが振り返り、手と持ち物のつながりが崩れた。`docs/knowledge/ai-drawing-notes.md`）
   - 三面図: `PYTHONPATH=.cache/gen/lib python3 tools/gen/bible.py turnaround <キャラクター> OUT_DIR --count 2`
     （下絵の色は設定資料の `turnaround` に持たせる。下絵に無い物（マント）は絵に出ないので、色を足して下絵に置く）
   - 持ち物を担ぐ姿勢: `tools/engine/pose_prop.py` の下絵を `bible.py draw --base 下絵 --strength 0.6〜0.8` に渡す
   - 描いた絵は検品担当に回す。範囲の描き直しは別の物を描き足しやすいので、崩れが多ければ描き直す
5. 人型以外（四足、虫、龍、ケンタウロス、ラミア、スライム、触手など）は、保存したらまず体の設計図を選ぶ（`bible.py set-body <id> <設計図>`）。
   部位の数は伝承と生物の資料に合わせてある（`casts/body-plans.json`、`docs/knowledge/body-plans.md`）。検品は欠損も余分も同じ重さで戻す
6. 目と表情は、キャラクターを保存したら最初に決める（表情担当 face-designer）。目は印象の大半を決めるのに、
   「brown eyes」だけでは描くたびに形もハイライトも変わる
   - 目: `bible.py set-eyes <キャラクター> --tags "形, 大きさ, 瞳, ハイライト, まつ毛, 眉" --notes "意図"`。描く言葉では見た目のすぐ後に入る
   - 表情: 既定の8つ（`bible.py` の `DEFAULT_EXPRESSIONS`）を性格に合わせて差し替え・追加する（`add-expression`）。口・眉・目の3つを必ず書く
   - 表情差分: `PYTHONPATH=.cache/gen/lib python3 tools/gen/bible.py expressions <キャラクター> OUT_DIR [--base 顔の基準の絵]`。
     基準の絵の顔の枠だけを表情ごとに描き直すので、髪・服・体は変わらない。並べた図 `expressions.png` を検品担当に回す

### 作品の登場人物をまとめて頼まれたとき（何人も、系統や進化がある）

依頼された作品は、デザインを作れるようになるための題材。作品の資料はその作品のリポジトリから読み、
このリポジトリには設定集（`casts/<作品>.json`）と決まり（`docs/designs/<作品>.md`）だけを置く。

1. 作品の資料を読み、作風・共通の印・系統ごとに残す印・段階の形を `docs/designs/<作品>.md` に決める。1体ずつ思いつきで書かない
2. 設定集に1人1行で書く。人は `gender`（male / female / androgynous。男女は体と顔の骨格から描かれる）と `age`（child / teen / adult / middle / elder。中年と老人は自動で SDXL 系）、人でない者は `kind: "creature"`（SDXL 系で描き、人の決まり文句を付けない）。
   モンスターの指示文は `docs/knowledge/monster-design.md` の3節の書き方（元の動物の名詞から、部位の数、3色）
3. 系統があるなら、先に各系統のベースの1体を決める（候補を6案ほど描き、検品し、選んでもらう）。ほかの段階はベースを手本に派生させる。
   系統ごとに別々に描くと、同じ系統で違う生き物が生まれる
4. `design.py batch casts/<作品>.json <出力>` → 1枚ずつ検品表で見る（指定していないところが変わった絵を「できた」と言わない。変わった点を添えて報告する） → 落とした絵は `rejected` に理由を書く → もう一度 batch（足りない分だけ描く）
   → `design.py sheet` の一覧図で見せる
5. 同じ破綻が続いたら指示文の書き方を直し、`docs/knowledge/monster-design.md` の6節に足す
6. 依頼先のリポジトリ（作品のリポジトリ）に送る。その作品のセッションが自分で続きを作れるようにするため:
   - `templates/character-design-client/SKILL.md` の `{{DESIGN_DIR}}` と `{{CAST}}` を埋めて、依頼先の `.claude/skills/character-design/SKILL.md` に置く
   - 決定稿の絵・ドット絵・候補の一覧と、状態の表（README.md）を依頼先の決めた置き場に置く（DigiMon は `design/beasts/`、RuleCrawler は `docs/designs/`）
   - push の仕方は依頼先の決まりに従う（どちらも main へ直接、1回にまとめる）。決定稿が増えたら、その都度送り直す

やらないこと: 自前の図形（SVG の部品）でキャラクターを組む・下絵にする（利用者の方針。部品を図形で組んだ絵はデザインとして使わない）。
2つのモデルを同時に動かす（メモリが足りず強制終了される）。

## 1. 作風を決まりに落とす

作風が `styles/` に無ければ、先に作る。`styles/diorama.json` が見本。

- `sources`: 何を見て決めたか。記事、インタビュー、実物の画像のページ
- 数えられるもの: `canvas`（大きさの範囲、体格の枠 `frames`）、`proportion.heads_tall`、`palette.max_colors`、`outline`、`cleanup.max_orphan_pixels`
- `render`: 箱庭ドット 用の部品から描き分けるときの変換（キャンバス、`shift`、`transforms`。頭は `parts: "head"`）
- 実物を見られないまま記憶で置いた数字には `"unverified": true` を付け、`docs/reports/pending.md` に見たいサイトのドメインを書く

画像そのものはリポジトリに置かない。置くのは数字と出典だけ。既存のキャラクターを写さない。

## 2. キャラクターを部品で組む

似た職業があれば `base` で継承して、差分だけ書く。書き方は `tools/build.py` の `load_spec` と `frame_spec` の説明にある。

- `remove` `override` `add`（`after` `before` で重ね順）、`materials`、`touchups`（目や鼻の1ドット）
- 動き: `frames`（`dy` 呼吸、`move` 脚の前後、`body_dy` 上下動、`override` 構えの差し替え）。`mirror_frames: true` で右向き
- 体格: `transforms`、子供は `frame: "child"`
- 書いたら `python3 tools/fmt.py characters/<名前>/parts.json`

## 3. 描いて確かめる

```bash
python3 tools/build.py characters/<名前>/parts.json [--style <作風>]
python3 tools/check.py characters/<名前>/sprite.json styles/<作風>.json
python3 tools/compare.py out.png 前=<旧 sprite.json> 後=<新 sprite.json>
python3 tools/anim.py --anim walk out.gif characters/<名前>/sprite.json
python3 tools/faces.py out.png   # 全キャラクターの全コマの頭
python3 tools/vsref.py out.png ref=<手本.png>@x0,y0,x1,y1 me=<sprite.json>@x0,y0,x1,y1   # 手本と同じ倍率で並べる
python3 tools/learn.py score styles/diorama.learned.json characters/*/sprite.json   # 手本の全コマの分布からの外れ
```

直す順番は `tools/learn.py score` で決める。手本の全コマ（728 コマ）から学んだ平均とばらつきに対して、特徴ごとの外れ（z）を出す。1体の手本だけを見て直すと、その1体の癖まで写す。手本のシートを足したら `tools/learn.py fit` で学び直す。

比較画像を実際に開いて見る。比べる相手は自分の前の版ではなく手本。部位を直すたびに `tools/vsref.py` で手本の同じ部位と横に並べ、1ドットの置き方は `--dump` で文字に起こして読む。見るもの:

- 職業と体格が輪郭と色で読めるか。並べたほかのキャラクターと見分けられるか
- 部品が隠れていないか。読めないときは形より先に重ね順を疑う
- 顔の1ドットが意図どおりの位置にあるか。継承した `touchups` が合っているか
- 顔は `tools/faces.py` で全コマ（呼吸、歩き、右向き）を見る。最初の1コマだけで良しとしない
- 目の組み方は `docs/knowledge/tech.md` の「顔の足し算と引き算」に従う。奥の目、黒目、白目は同じ行に揃える
- 舞台の図（`tools/render.py`）で沈んでいないか

色数が上限を超えたら、使うドットの少ない段から素材どうしで色を共有する。

## 3.5 3D（頼まれたとき）

手順と詰まったところは `docs/knowledge/3d.md`。専用ベース（アニメ調、体型・水着・亜人の部品・ポーズ・光）は `tools/engine/viewer/vrm-base.html`。
3D は一区切りにしている。広げるのは亜人の下絵に要る部品だけにする。
写実の顔は見せない。アニメ調（頭を大きめ、陰2段、輪郭線、大きな瞳）にしてから、正面・顔を自分で撮って確かめてから見せる。

## 4. 残す

- 比較画像と判定を `docs/progress/` に置く（良くなった所、弱い所を両方書く）
- 分かったことは `docs/knowledge/`、決めたことは `docs/knowledge/decisions.md`
- `python3 -m unittest discover -s tests` を終了コードで確かめる（`| tail` の後ろに `&&` をつながない）
