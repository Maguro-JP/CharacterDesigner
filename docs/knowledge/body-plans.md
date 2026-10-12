# 体の設計図（部位の数の決まり）

欠損（足りない）と余分（多い）は、どちらも一番重い崩れ。数の正しさは種族で決まるので、種族ごとの「体の設計図」を
`casts/body-plans.json` に持ち、検品の棚卸しで照らす。数は特別な指示が無いときの既定。設定資料のキャラクターは
`body`（設計図の id）を持ち、無ければ人型（humanoid）とみなす。

## 考え方

- 特別な指示が無い限り、直立の人型は右腕・左腕・右脚・左脚が1本ずつ、体の正しい側から出る。手の指は5本
- 混ぜた種族（ケンタウロス、ラミア、人魚、ハーピー）は、どこで人から獣に変わるか（多くは腰）を決め、境目より下に人の脚を描かない
- 似た名前でも別の物: 西洋のドラゴン（四つ脚＋翼2枚）と飛竜（脚2本＋翼2枚）、東洋の龍（蛇のような胴に脚4本、翼は無い）。
  虫（脚6本）と蜘蛛（脚8本）。タコ（腕8本）とイカ（腕8本＋触腕2本）
- 伝承で決まりがある種族は伝承に合わせる。伝承に無い所（スライムの目の有無、触手の数）は設定資料で決め、決めた数ちょうどにする
- 描く模型は、数の多い部位（指、脚、触手、尾）で数を間違えやすい。棚卸しでは必ず1本ずつ数え、「たぶん合っている」で通さない

## 種族ごとの要点（数は `casts/body-plans.json`）

- 東洋の龍: 長い蛇の胴、脚4本、翼は無い、角2本、長い髭。爪の数は中国では身分を表し、五本爪は皇帝、四本は貴族、三本は庶民とされた。
  日本では三本爪が好まれた。九似（角は鹿、頭は駱駝、目は兎、首は蛇、腹は蜃、鱗は魚、爪は鷹、掌は虎、耳は牛）。
  九似の出典は宋の羅願『爾雅翼』とされる（王符とする説明もあるが、今回は確かめられなかった）
- 西洋のドラゴンと飛竜: 英国の紋章学では、脚4本がドラゴン、脚2本（翼が前肢を兼ねる）が飛竜。他の国の紋章学では分けないこともある
- ケンタウロス: 頭・腕・胴が人で、腰で馬の胴と脚につながる。古いギリシャの絵には、前脚が人の脚の形もある
- 九尾の狐: 年を経るほど尾が増え、最大9本。何年で1本増えるかは資料で違う（100年、1000年で9本目、など）。尾の数は設定で決める
- ラミア・人魚: 腰から上が人、下が蛇の胴・魚の尾。脚は無い
- ハーピー: 腕の代わりに翼、脚は鳥の脚と鉤爪（古典の記述ではなく、現代の描き方の目安）
- 虫: 頭・胸・腹の3つ。脚6本は胸から出る。触角2本。蜘蛛は虫ではなく、頭胸部と腹部の2つに脚8本
- タコ・イカ: どちらも腕8本が口を囲む。イカはさらに長い触腕2本（吸盤は先だけ）と、胴の先のひれ2枚
- 魚: 脚は無い。胸びれと腹びれが左右に1対ずつ、背びれ・尻びれ・尾びれは1枚ずつ（一般的な知識。今回の検索では出典を取れなかった）
- スライム・触手: 伝承の決まりは無い。スライムは手足・関節の無い半透明の塊、触手は関節が無く根元から先へ細くなり、体の決まった所から出る。
  どちらもこのリポジトリの決め方で、目や口の有無・触手の数は設定資料で決める

## 出典

- 龍の爪の数と東西の違い: [現代ビジネス](https://gendai.media/articles/-/119358)、[楽天市場の解説](https://www.rakuten.co.jp/fromseed/contents/dragon_ryu/)、[ピクシブ百科事典](https://dic.pixiv.net/a/%E9%BE%8D)（どれも解説記事。一次資料は池上正治『龍の世界』など）
- 九似: [Dreweatts: Chinese art dragons](https://www.dreweatts.com/news-videos/chinese-art-dragons/)、[潮新聞](https://tidenews.com.cn/news.html?id=2711676)
- ドラゴンと飛竜: [Wyvern（Wikipedia）](https://en.wikipedia.org/wiki/Wyvern)
- ケンタウロス: [World History Encyclopedia](https://www.worldhistory.org/centaur/)、[Edward Worth Library](https://mythicalcreatures.edwardworthlibrary.ie/ancient-world/centaurs/)
- 九尾の狐: [Kitsune（Wikipedia）](https://en.wikipedia.org/wiki/Kitsune)
- ラミア: [New World Encyclopedia](https://www.newworldencyclopedia.org/entry/Lamia_(mythology))
- ハーピー・人魚（現代の描き方）: [Anime News Network](https://www.animenewsnetwork.com/feature/2015-09-04/a-field-guide-to-dating-monster-girls/.92532)
- 虫と蜘蛛: [Museum of the Earth: Insect Anatomy](https://www.museumoftheearth.org/six-legged-science/insect-anatomy)
- タコとイカ: [Te Ara](https://teara.govt.nz/mi/octopus-and-squid/page-1)、[dictionary.com](https://www.dictionary.com/e/squid-vs-octopus/)
