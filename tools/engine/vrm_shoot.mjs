// 3D の素体（tools/engine/viewer/vrm-base.html）を画面なしのブラウザで開き、向きごとに色の絵と部品の型を撮る。
// 使い方: node tools/engine/vrm_shoot.mjs '{"url":"http://127.0.0.1:8770/index.html","out":"dir/name","kind":"devil","body":"ideal","pose":"stand","views":[0,35,145,180]}'
// 出力: <out>-color-<i>.png（背景は透明）、<out>-mask-<i>.png（肌は緑、部品は赤、それ以外は黒）
const pwPath = process.env.PLAYWRIGHT_MODULE || 'playwright';
const { chromium } = await import(pwPath);
const a = JSON.parse(process.argv[2]);
const b = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
  // GPU が無い環境でも WebGL を描けるよう、CPU の描画（SwiftShader）を使う。素体は手元の配信から読むので代理サーバーを通さない
  args: ['--no-proxy-server', '--use-gl=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const p = await b.newPage({ viewport: { width: 420, height: 1000 }, deviceScaleFactor: 2 });
const errs = []; p.on('pageerror', e => errs.push(e.message));
await p.goto(a.url);
await p.waitForFunction(() => window.ready === true, null, { timeout: 300000 });
// parts（耳・尾・翼・角の形と色）があればそれを使い、無ければ kind（猫・悪魔などの組）を使う。hair: "hide" で髪を隠す
await p.evaluate(a => {
  tool.barefoot(a.barefoot !== false); tool.body(a.body || 'ideal');
  if (a.parts) tool.parts(a.parts); else tool.kind(a.kind || 'none');
  tool.hair(a.hair !== 'hide'); tool.pose(a.pose || 'stand');
}, a);
const stage = p.locator('#stage');
for (const [i, deg] of (a.views || [0, 180]).entries()) {
  await p.evaluate(d => tool.view(d), deg); await p.waitForTimeout(500);
  await stage.screenshot({ path: `${a.out}-color-${i}.png`, omitBackground: true });
  await p.evaluate(() => tool.mask(true)); await p.waitForTimeout(300);
  await stage.screenshot({ path: `${a.out}-mask-${i}.png`, omitBackground: true });
  await p.evaluate(() => tool.mask(false));
}
await b.close();
if (errs.length) { console.error(errs.join('\n')); process.exit(1); }
console.log('ok', (a.views || [0, 180]).length);
