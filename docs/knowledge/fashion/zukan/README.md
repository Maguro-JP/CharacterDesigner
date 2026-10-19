# 世界の服装の図鑑

最終確認: 2026-10

古代から今の流行まで、世界の代表的な服装を、キャラクターデザインで使える形（品目・素材・色・髪・小物・背景・描く言葉・出典）にまとめた資料。
今の日本の10代〜20代の流行（2024〜2026年）は、ひとつ上の `../genres.md` にある。

## 章

| 章 | 項目 | 出典 |
|---|---|---|
| [古代（〜500年ごろ）](01-ancient.md) | 15 | 42 |
| [中世（500〜1450年ごろ）](02-medieval.md) | 15 | 49 |
| [近世（1450〜1800年ごろ）](03-early-modern.md) | 15 | 67 |
| [19世紀](04-19th-century.md) | 15 | 35 |
| [1900〜1945年](05-1900-1945.md) | 15 | 51 |
| [1946〜1999年の若者文化](06-1946-1999.md) | 18 | 40 |
| [2000〜2026年](07-2000-now.md) | 18 | 74 |
| [今も着られる世界の伝統衣装](08-world-traditional.md) | 24 | 92 |

合計 135 項目、出典 450 件（章ごとに番号を振っている）。

## 項目の書き方

各項目は同じ欄を持つ: 時代、地域、着た人、一言、上・下・羽織、素材、色・柄、髪・頭、小物・靴、背景、キャラクターの手がかり、描く言葉、出典。

- 「未確認」は、信頼できる出典で確かめられなかったもの。推測で埋めていない
- 色の16進コードは色名の目安で、出典の値ではない（出土品や古い布は退色している）
- 「キャラクターの手がかり」は物語での使い方の候補で、歴史の事実ではない
- 描く言葉は画像生成の英語の言葉の候補。Danbooru のタグとして在るかは、使う前に確かめる
- 宗教・民族の衣装は、その文化での意味（儀礼か日常か、誰が着てよいか）を「背景」に書いた。神聖な装身具には描く言葉を付けず「描くときは注意」とした。考え方は `../../cultural-sensitivity.md`
- 実在の国・軍・団体の印やブランドの商標は、描く言葉に入れない

## 見本の絵

図鑑の人物は `casts/fashion-zukan/characters/` に設定資料集の形で置き、人物と同じ描く流れ（`tools/gen/pipeline.py`、人形の下絵 → 全身 → 顔 → 手 → 検品）で描く。

```
CD_BIBLE=casts/fashion-zukan PYTHONPATH=.cache/gen/lib python3 tools/gen/pipeline.py run <id> <出力>
```

検品担当が通した絵だけを `library/samples/fashion/zukan-<id>.png` に置き、ここの一覧に足す。

## 項目の一覧

### 古代（〜500年ごろ）

シェンティ（shendyt / schenti）、カラシリス（細身の長衣）と襞の巻き衣（kalasiris / sheath dress, New Kingdom wrapped dress）、カウナケス（kaunakes）、アケメネス朝の宮廷衣（Achaemenid court robe）、騎馬の民の上着とズボン（Scythian and Saka caftan and trousers）、キトンとヒマティオン（chiton, himation）、ペプロス（peplos）、トーガ（toga）、ストラとパッラ（stola, palla）、アンタリーヤとウッタリーヤ（antariya, uttariya, kayabandh）、深衣（曲裾・直裾）（shenyi, quju / zhiju）、衣褌・衣裳（きぬはかま・きぬも）、朝服（ちょうふく）、マヤの腰布・腰巻き・ウィピル（Classic Maya loincloth, hip cloth, huipil）、ケルトの格子柄の衣とズボン（Iron Age Celtic dress）

### 中世（500〜1450年ごろ）

ビザンツ帝国の宮廷服（Byzantine court dress: chlamys, loros）、ヨーロッパ中世前期の服（Early medieval tunic and cloak）、ヴァイキングの服（Viking Age dress）、西ヨーロッパの宮廷・都市の服: コット、シュルコ、ウープランド、エナン（Cotte, surcote, houppelande, hennin）、騎士の鎖帷子と陣羽織（Mail hauberk and surcoat）、中世の農民・職人（Medieval peasants and craftsmen）、修道服（Monastic habit）、アッバース朝の宮廷と都市の服（Abbasid court and urban dress）、モンゴル帝国の騎馬と宮廷の服（Mongol Empire dress）、宋の官服と女性の褙子（Song dynasty official robe and women's beizi）、高麗の服（Goryeo dress）、平安の束帯と女房装束（十二単）（Sokutai and nyōbō shōzoku / jūni-hitoe）、平安の狩衣と水干（Kariginu and suikan）、鎌倉・室町の直垂と小袖（Hitatare, armor, and kosode）、マリ帝国の宮廷の服（Court dress of the Mali Empire）

### 近世（1450〜1800年ごろ）

イタリア・ルネサンスの服（Italian Renaissance dress: gamurra, giornea, farsetto）、16世紀の宮廷服（スペイン風とテューダー朝）（Spanish black fashion / Tudor and Elizabethan dress）、17世紀前半の西欧（騎士風とオランダ市民）（Cavalier fashion / Dutch burgher dress）、ロココの宮廷服（Robe à la française / habit à la française）、船乗りの服（海賊の時代を含む）（Sailor's slops, petticoat breeches）、オスマン帝国のカフタン（Ottoman kaftan）、サファヴィー朝の服（Safavid dress, taj-i Haidari）、ムガル帝国のジャーマ（Mughal jama, patka, peshwaz）、明代の漢服（Ming dynasty hanfu: yuanlingpao, aoqun, mamianqun）、清の満洲族の服（Qing Manchu dress: horse-hoof cuffs, queue, qizhuang）、朝鮮王朝後期の韓服（Joseon hanbok: jeogori, chima, dopo, heungnip）、安土桃山〜元禄の小袖と打掛（Kosode and uchikake, Momoyama to Genroku）、江戸の男たち（裃・町人・火消し）（Kamishimo, Edo townsmen, machi-bikeshi）、アシャンティのケンテ（Asante kente）、植民地期アンデスのインカ貴族（Colonial Inca nobility: unku, lliclla, acsu）

### 19世紀

1. エンパイア・スタイル（Empire style / Neoclassical dress）、2. リージェンシーの紳士とダンディ（Regency gentleman, dandy）、3. ロマン主義期からクリノリンへ（Romantic era / crinoline）、4. バッスルとジャポニスム（Bustle, Japonisme）、5. ヴィクトリア朝の喪服（Victorian mourning dress）、6. ヴィクトリア朝の労働者と農民（Working-class dress, smock frock）、7. 紳士のフロックコートとシルクハット（Frock coat, top hat, lounge suit）、8. 19世紀の軍服の流れ（Military uniform in the 19th century）、9. アメリカ西部（カウボーイと開拓者）（Cowboy, vaquero, pioneer）、10. ガウチョ（Gaucho）、11. 清末の中国（Late Qing dress）、12. 幕末・明治の洋装の始まり（Western dress in Meiji Japan）、13. 明治の書生と女学生（Shosei and jogakusei）、14. オスマン末期（Late Ottoman dress）、15. 英領時代のインド（Dress in colonial India）

### 1900〜1945年

ベル・エポックの S 字シルエットとギブソン・ガール（S-bend silhouette / Gibson Girl）、ポワレの筒形ドレス（Paul Poiret, chemise / hobble skirt / lampshade tunic）、第一次大戦の女性軍需工員（Munitionettes）、フラッパー（Flapper / la garçonne）、ジャズ時代の紳士とハーレムの装い（1920s menswear / Oxford bags）、シャネルのジャージーと黒のドレス（Gabrielle Chanel, jersey / little black dress）、1930年代のバイアスカットのイブニングドレス（Bias-cut evening gown）、大恐慌期の農民と労働者（Depression-era workwear / feed sack dresses）、戦時の配給服とユーティリティ服（Clothes rationing / Utility clothing, CC41）、ズートスーツ（Zoot suit）、女学生の袴（海老茶式部）（Jogakusei hakama / ebicha-shikibu）、モダンガール・モダンボーイと銘仙（Moga, Mobo and meisen）、上海の旗袍（Qipao / cheongsam）、テワナの服（Traje de tehuana）、カディと独立運動の白い服（Khadi / Gandhi cap）

### 1946〜1999年の若者文化

ニュールック（New Look）、テディボーイ（Teddy Boys）、グリーサーとサークルスカート（Greasers / poodle skirt）、ビートニク（Beatnik）、モッズ（Mods）、スペースエイジとミニ丈（Space Age / miniskirt）、みゆき族とアイビー（Miyuki-zoku / Ivy look）、ヒッピー（Hippies）、パンク（Punk）、ニューロマンティック（New Romantic）、特攻服（暴走族とヤンキー）、竹の子族（Takenoko-zoku）、パワースーツ（Power dressing）、DCブランドブーム（DC brands）、ヒップホップ（Hip-hop fashion）、グランジ（Grunge）、裏原宿（Ura-Harajuku）、サプール（La Sape）

### 2000〜2026年

Y2K（2000年代前半の本来の姿）（Y2K fashion, McBling）、ボーホー・シック（Boho chic）、ギャルとお姉系（Gyaru, Onee-kei）、原宿系（ロリータ・ゴシックロリータ・デコラ）（Harajuku style: Lolita, Gothic Lolita, Decora）、森ガール（Mori girl）、エモ（スクリーモ・シーン）（Emo, Screamo, Scene）、インディー・スリーズ（ヒップスター）（Indie sleaze, hipster）、ノームコアとアスレジャー（Normcore, Athleisure）、ストリートの高級化（Luxury streetwear）、K-POP と韓流の装い（K-pop and Hallyu style）、ジェンダーレス（Genderless kei）、コテージコアとダーク・アカデミア（Cottagecore, Dark academia）、テックウェア（Techwear）、漢服の復興（Hanfu movement）、アフリカの布と現代の服（アンカラ、アディレ、アフロフューチャリズム）（Contemporary African fashion, Ankara, Adire, Afrofuturism）、モデスト・ファッション（Modest fashion, Contemporary Muslim fashion）、インドのフュージョン・ウェア（Indo-western fusion wear）、チョリータの装い（チョラ・パセーニャ）（Chola paceña / cholita fashion）

### 今も着られる世界の伝統衣装

着物・浴衣（kimono / yukata）、アイヌの衣服（attush, ruunpe, chikarkarpe ほか）、琉装と紅型（Ryukyu bingata）、韓服（hanbok）、旗袍と漢服（qipao / hanfu）、デール（deel）、アオザイ（áo dài）、バティックとサロン（batik / sarong）、チュット・タイ（Chut Thai Phra Ratchaniyom）、サリー（sari / saree）、サルワール・カミーズとクルタ（salwar kameez / kurta）、チャパン（chapan / khalat）、湾岸の装い（ディシュダーシャ・アバヤ）とヒジャブ（dishdasha / abaya / hijab）、西アフリカの装い（ケンテ・ダシキ・ブーブー）（kente / dashiki / boubou）、東アフリカの布（カンガ・シュカ）（kanga / shuka）、ディアンドルとレーダーホーゼン（Dirndl / Lederhosen）、キルト（kilt）、ブーナッド（bunad）、ヴィシヴァンカ（スラブの刺繍の服）（vyshyvanka）、フラメンカ衣装（traje de flamenca）、中南米の装い（ポンチョ・ウイピル・ポジェラ）（poncho / huipil / pollera）、北米先住民のレガリア（regalia）、ポリネシアの装い（アロハ・ムームー・ラバラバ）（aloha shirt / muʻumuʻu / ʻie lavalava）、マオリのカーカフ（外套）（kākahu）

