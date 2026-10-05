"""VRM（glb）の中の画像を長い辺 max_px までに縮め、作り直す。形・骨・表情はそのまま。"""
import io, json, struct, sys
from PIL import Image
src, dst, max_px = sys.argv[1], sys.argv[2], int(sys.argv[3])
d = open(src, 'rb').read()
n = struct.unpack_from('<I', d, 12)[0]
js = json.loads(d[20:20 + n]); off = 20 + n + 8
binlen = struct.unpack_from('<I', d, 20 + n)[0]
blob = d[off:off + binlen]
img_views = {im['bufferView']: im for im in js.get('images', []) if 'bufferView' in im}
new = bytearray(); views = []
for i, bv in enumerate(js['bufferViews']):
    chunk = blob[bv.get('byteOffset', 0): bv.get('byteOffset', 0) + bv['byteLength']]
    if i in img_views:
        im = Image.open(io.BytesIO(chunk)); im.load()
        if max(im.size) > max_px:
            k = max_px / max(im.size)
            im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
        b = io.BytesIO(); im.save(b, 'PNG', optimize=True); chunk = b.getvalue()
        img_views[i]['mimeType'] = 'image/png'
    while len(new) % 4: new += b'\0'
    bv = dict(bv); bv['byteOffset'] = len(new); bv['byteLength'] = len(chunk); bv['buffer'] = 0
    new += chunk; views.append(bv)
while len(new) % 4: new += b'\0'
js['bufferViews'] = views; js['buffers'] = [{'byteLength': len(new)}]
j = json.dumps(js, ensure_ascii=False).encode('utf-8')
while len(j) % 4: j += b' '
out = b'glTF' + struct.pack('<II', 2, 12 + 8 + len(j) + 8 + len(new)) + struct.pack('<I', len(j)) + b'JSON' + j + struct.pack('<I', len(new)) + b'BIN\0' + bytes(new)
open(dst, 'wb').write(out)
print(len(d), '->', len(out))
