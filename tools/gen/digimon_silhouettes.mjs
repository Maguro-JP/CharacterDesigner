// DigiMon の設定資料（Beast Design Sheets.dc.html）のシルエットを、段階ごとの SVG に書き出す。
// 文章の指示だけでは手足の数や「手足の無い塊」を守らせきれなかったので、作者が決めた体型の当たりを
// 下絵にして画像生成に渡す（design.py の init）。シルエットの描き方は設定資料のコードをそのまま動かす。
// 使い方: node tools/gen/digimon_silhouettes.mjs <Beast Design Sheets.dc.html> <出力フォルダ>
import fs from "node:fs";
import path from "node:path";

const [src, out] = process.argv.slice(2);
const html = fs.readFileSync(src, "utf8");
const body = html.split("data-dc-script>")[1].split("class Component")[0].replace("function art(", "function _art(");
const LINES = new Function(`${body}; return LINES;`)();
const IDS = { "トルネ": "tor", "ハク": "hak", "エンボウ": "emb", "カメロ": "kam", "ライトリ": "rai", "ゴロン": "gor", "ヨル": "yor" };
fs.mkdirSync(out, { recursive: true });
for (const L of LINES) {
  L.stages.forEach((s, i) => {
    if (i === 0) return; // 卵は描かない
    const fill = s.palette[0];
    // 目は抜かずに白で置く（下絵の目の位置を生成に渡す）
    const svg = s.svg.replaceAll('fill="#0d1222"', 'fill="#ffffff"');
    const doc = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="-20 -20 140 140" width="768" height="768">` +
      `<rect x="-20" y="-20" width="140" height="140" fill="#ffffff"/><g fill="${fill}" stroke="#111111" stroke-width="1.2">${svg}</g></svg>`;
    fs.writeFileSync(path.join(out, `${IDS[L.name]}-${i + 1}.svg`), doc);
  });
}
console.log("ok");
