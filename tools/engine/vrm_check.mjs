// 書き出した .vrm と .glb が、ほかの道具で読めるかを確かめる（Actions の chara3d で使う。手元では動かさない）。
// 1. Khronos の glTF の検査器（gltf-validator）で、誤り（severity 0）が 0 か。
// 2. three.js の GLTFLoader と three-vrm（VRMLoaderPlugin）で読み、人型の骨と MToon の材質が取れるか（.vrm だけ）。
//    node には画像を読む部品が無いので、読む前に貼る絵の参照だけを外す（形・骨・重み・材質の拡張はそのまま）。
// 使い方: node tools/engine/vrm_check.mjs <a.vrm> <b.glb> ...
//   部品は版を固定して入れる: npm i three@0.169.0 @pixiv/three-vrm@3.1.0 gltf-validator@2.0.0-dev.3.10
import fs from "node:fs";
import validator from "gltf-validator";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { VRMLoaderPlugin } from "@pixiv/three-vrm";

function stripTextures(buf) {
  const jsonLen = buf.readUInt32LE(12);
  const g = JSON.parse(buf.subarray(20, 20 + jsonLen).toString("utf8"));
  const bin = buf.subarray(20 + jsonLen + 8);
  delete g.images; delete g.textures; delete g.samplers;
  for (const m of g.materials || []) {
    if (m.pbrMetallicRoughness) delete m.pbrMetallicRoughness.baseColorTexture;
    const t = m.extensions && m.extensions.VRMC_materials_mtoon;
    if (t) delete t.shadeMultiplyTexture;
  }
  let js = Buffer.from(JSON.stringify(g), "utf8");
  js = Buffer.concat([js, Buffer.alloc((4 - (js.length % 4)) % 4, 0x20)]);
  const head = Buffer.alloc(12); head.write("glTF", 0); head.writeUInt32LE(2, 4);
  head.writeUInt32LE(12 + 8 + js.length + 8 + bin.length, 8);
  const jh = Buffer.alloc(8); jh.writeUInt32LE(js.length, 0); jh.write("JSON", 4);
  const bh = Buffer.alloc(8); bh.writeUInt32LE(bin.length, 0); bh.write("BIN\0", 4);
  const out = Buffer.concat([head, jh, js, bh, bin]);
  return out.buffer.slice(out.byteOffset, out.byteOffset + out.byteLength);
}

let failed = 0;
for (const path of process.argv.slice(2)) {
  const bytes = fs.readFileSync(path);
  const report = await validator.validateBytes(new Uint8Array(bytes));
  const n = report.issues.numErrors;
  const msgs = report.issues.messages.filter((m) => m.severity === 0).slice(0, 5).map((m) => `${m.code} ${m.pointer || ""}`);
  const kinds = {};
  for (const m of report.issues.messages) if (m.severity === 1) kinds[m.code] = (kinds[m.code] || 0) + 1;
  console.log(`${path}: glTF の検査 誤り ${n}、注意 ${report.issues.numWarnings}${msgs.length ? " " + msgs.join(" / ") : ""} 注意の種類 ${JSON.stringify(kinds)}`);
  if (n) failed++;
  if (!path.endsWith(".vrm")) continue;
  const loader = new GLTFLoader();
  loader.register((p) => new VRMLoaderPlugin(p));
  try {
    const gltf = await new Promise((res, rej) => loader.parse(stripTextures(bytes), "", res, rej));
    const vrm = gltf.userData.vrm;
    const need = ["hips", "head", "leftUpperArm", "rightHand", "leftFoot"];
    const missing = need.filter((b) => !vrm.humanoid.getRawBoneNode(b));
    const mtoon = [];
    const types = new Set();
    gltf.scene.traverse((o) => {
      for (const m of [].concat(o.material || [])) {
        types.add(m.type);
        if (m.isMToonMaterial || m.type === "MToonMaterial") mtoon.push(m);
      }
    });
    console.log(`${path}: 材質の種類 ${[...types].join(",")}`);
    console.log(`${path}: three-vrm で読めた。骨 ${Object.keys(vrm.humanoid.humanBones).length} 本、足りない骨 ${missing.length}、MToon ${mtoon.length}、名前 ${vrm.meta.name}`);
    if (missing.length || !mtoon.length) failed++;
  } catch (e) {
    console.log(`${path}: three-vrm で読めなかった: ${(e && e.message) || e}`);
    failed++;
  }
}
process.exit(failed ? 1 : 0);
