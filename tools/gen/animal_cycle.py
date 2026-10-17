"""動物1種を、簡単な画風から本格的なリアル風まで12の画風で順に描く（毎時の描画の周）。

使い方:
  PYTHONPATH=.cache/gen/lib CD_FETCH=1 python3 tools/gen/animal_cycle.py <出力フォルダ>

まだ描いていない動物を ANIMALS の上から1つ選び、描き終えたら DONE に名前を足す。
特徴（features）は全部の画風に同じ言葉で入れる。デフォルメでもリアルでも、
同じ動物だと分かる目印（模様・耳・尾の形）を揃えるため。
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DONE = ROOT / "docs" / "knowledge" / "feedback" / "animals-done.json"

# 名前, 特徴（体の数と目印）
ANIMALS = [
    ("capybara", "a capybara, four short legs, blunt square snout, small round ears, brown fur"),
    ("axolotl", "an axolotl, four small legs, three pairs of feathery pink gills, smiling mouth, long tail"),
    ("pangolin", "a pangolin, four legs, body covered in overlapping brown scales, long tail"),
    ("toucan", "a toucan, two wings, two feet, huge orange and yellow beak, black body, white throat"),
    ("chameleon", "a chameleon, four legs, curled tail, bulging eyes, green skin"),
    ("snow leopard", "a snow leopard, four legs, grey-white fur with black rosettes, very long thick tail"),
    ("manta ray", "a manta ray, wide diamond-shaped body, two cephalic fins, long thin tail"),
    ("tapir", "a malayan tapir, four legs, short trunk-like nose, black body with white middle"),
    ("hummingbird", "a hummingbird, two wings, long thin beak, iridescent green feathers, hovering"),
    ("armadillo", "an armadillo, four legs, banded armored shell, pointed snout"),
    ("seahorse", "a seahorse, curled tail, long tube snout, small dorsal fin, upright body"),
    ("okapi", "an okapi, four legs, brown body, zebra-striped legs, long neck"),
    ("puffin", "a puffin, two wings, two orange feet, colorful triangular beak, black and white body"),
    ("quokka", "a quokka, small round body, four legs, short rounded ears, smiling face"),
    ("shoebill", "a shoebill stork, two wings, two long legs, huge shoe-shaped beak, grey feathers"),
    ("fennec fox", "a fennec fox, four legs, very large ears, cream fur, bushy tail"),
    ("hippo", "a hippopotamus, four short legs, huge mouth, grey-pink skin"),
    ("koi", "a koi carp, orange and white scales, long fins, whiskers"),
    ("sloth", "a three-toed sloth, four long limbs with curved claws, dark eye mask, hanging from a branch"),
    ("moose", "a moose, four legs, wide flat antlers, long face, dark brown fur"),
]

# 簡単なものから本格的なものへ
STYLES = [
    ("01-yurukyara", "yuru-chara mascot, super simple round shapes, thick outline, flat colors, cute"),
    ("02-chibi", "chibi deformed sticker, big head, flat 2d, white outline"),
    ("03-character", "anime character design sheet style, cel shading, clean lineart"),
    ("04-anime", "1990s anime cel animation still"),
    ("05-manga", "black and white manga ink drawing, screentone, monochrome"),
    ("06-illust", "digital illustration, soft lighting, detailed"),
    ("07-kirie", "paper cut-out art, layered colored paper, flat shapes"),
    ("08-nihonga", "nihonga japanese painting, mineral pigments, gold leaf background"),
    ("09-ukiyoe", "ukiyo-e woodblock print, bold outlines, flat colors"),
    ("10-oil", "classical oil painting, visible brush strokes"),
    ("11-watercolor", "loose watercolor painting, paper texture"),
    ("12-real", "wildlife photograph, realistic, natural habitat, sharp focus"),
]


def main():
    out = Path(sys.argv[1])
    done = json.loads(DONE.read_text()) if DONE.exists() else []
    left = [a for a in ANIMALS if a[0] not in done]
    if not left:
        print("all animals done")
        return
    name, feat = left[0]
    d = out / name.replace(" ", "-")
    d.mkdir(parents=True, exist_ok=True)
    print("animal:", name, flush=True)
    for key, style in STYLES:
        p = d / f"{key}.png"
        if p.exists():
            continue
        # 画風を先頭に置く（先頭の言葉ほど効く）。体は小さめに収め、端で切れないようにする
        # 「 style」を含めると design.py がアニメ塗りの決まり文句を付けない
        prompt = f"{style} style, {feat}, full body, small in frame"
        r = subprocess.run([sys.executable, str(ROOT / "tools/gen/design.py"), "draw", str(p), prompt,
                            "--kind", "creature", "--style", "xl", "--seed", "1"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(key, "exit", r.returncode, flush=True)
    DONE.write_text(json.dumps(done + [name], indent=1) + "\n")


if __name__ == "__main__":
    main()
