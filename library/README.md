# 描き分けのパターン集

`patterns.json` に、描いて確かめた描き分けのパターン（皮膚、体型、角、耳、亜人間など）を名前で保存する。
設定集の人物に `"patterns": ["skin-dark", "horns-ram"]` と書くと、その部品が入る。

- `verified` は男女それぞれで描いて確かめた結果。「出た」でも、括弧の中に指定外の変化（余計な変化）を書く
- `samples/` は見本の絵（素体、簡素な無地の肌着）。`base-male.png` と `base-female.png` が比べる基準
- 効かなかった部品はここに置かない。結果は `docs/knowledge/traits.md`
- パターンを足すときは、男女の素体（`"framing": "body"`）で描いて基準と並べて見てから足す（`casts/repertoire.json`）
