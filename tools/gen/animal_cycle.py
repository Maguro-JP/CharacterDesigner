"""その日の動物を、毎時1つの画風で描く（12時のゆるキャラから23時のリアル風まで12の画風）。

使い方:
  PYTHONPATH=.cache/gen/lib CD_FETCH=1 python3 tools/gen/animal_cycle.py <出力フォルダ> [画風の番号 0-11]

画風は STYLES の12個で決まっている。動物は日ごとに ANIMALS からまだ描いていないものを選び、
docs/knowledge/feedback/animals-by-day.json に日付と一緒に残す。動物は足せばいくらでも増やせる。
特徴（features）は全部の画風に同じ言葉で入れる。デフォルメでもリアルでも、
同じ動物だと分かる目印（模様・耳・尾の形）を揃えるため。
"""
import json
import subprocess
from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DONE = ROOT / "docs" / "knowledge" / "feedback" / "animals-by-day.json"

JST = timezone(timedelta(hours=9))
FIRST_HOUR = 12  # 12時がゆるキャラ、23時がリアル風
SEEDS = (1, 2, 3)  # 1つの画風を3枚。1枚約5分で、1時間の枠に収まる

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
    ("kiwi", "a kiwi bird, round brown body, long thin beak, two strong legs, no visible wings"),
    ("red-crowned crane", "a red-crowned crane, two long legs, white body, black neck, red patch on head"),
    ("platypus", "a platypus, four webbed feet, duck bill, flat beaver tail, brown fur"),
    ("meerkat", "a meerkat standing upright on two hind legs, slim tan body, dark eye patches, thin tail"),
    ("jellyfish", "a moon jellyfish, translucent bell, four pale rings, long thin tentacles"),
    ("narwhal", "a narwhal, grey spotted body, one long spiral tusk, two flippers, tail fluke"),
    ("peacock", "a peacock, two legs, blue neck, huge fanned tail with eye spots"),
    ("raccoon dog", "a japanese raccoon dog, four legs, dark eye mask, bushy brown fur"),
    ("mandrill", "a mandrill, four limbs, red and blue face, golden beard"),
    ("lynx", "a eurasian lynx, four legs, black ear tufts, short bobbed tail, spotted fur"),
    ("stag beetle", "a stag beetle, six legs, huge branched jaws, glossy dark brown shell"),
    ("pufferfish", "a pufferfish, round inflated body covered in spines, small fins"),
    ("bison", "an american bison, four legs, huge shaggy hump, short curved horns"),
    ("owl butterfly", "a butterfly with two pairs of wings marked with large eye spots, six thin legs"),
    ("sea turtle", "a green sea turtle, four flippers, smooth oval shell"),
    ("serval", "a serval, four long legs, large ears, golden fur with black spots"),
    ("pelican", "a pelican, two webbed feet, long beak with large throat pouch, white feathers"),
    ("anteater", "a giant anteater, four legs, very long snout, huge bushy tail, diagonal black stripe"),
    ("gecko", "a leopard gecko, four legs with toes, spotted yellow skin, thick tail"),
    ("yak", "a yak, four legs, long shaggy black hair, curved horns"),
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


def today_animal(today):
    """その日の動物。日付ごとに1種を決めて残し、同じ動物を2度選ばない。"""
    days = json.loads(DONE.read_text()) if DONE.exists() else {}
    if today not in days:
        used = set(days.values())
        left = [n for n, _ in ANIMALS if n not in used]
        if not left:
            raise SystemExit("ANIMALS を描き尽くした。新しい動物を足す")
        days[today] = left[0]
        DONE.write_text(json.dumps(days, indent=1, ensure_ascii=False) + "\n")
    name = days[today]
    return name, dict(ANIMALS)[name]


def main():
    # 1日1種。12時から23時（JST）まで毎時1つの画風を描き、23時がリアル風になる
    out = Path(sys.argv[1])
    now = datetime.now(JST)
    slot = now.hour - FIRST_HOUR if len(sys.argv) < 3 else int(sys.argv[2])
    if not 0 <= slot < len(STYLES):
        print("no slot at", now.hour)
        return
    name, feat = today_animal(now.strftime("%Y-%m-%d"))
    draw_one(out / now.strftime("%Y%m%d"), name, feat, [STYLES[slot]])


def draw_one(out, name, feat, styles=STYLES):
    d = out / name.replace(" ", "-")
    d.mkdir(parents=True, exist_ok=True)
    print("animal:", name, flush=True)
    for key, style in styles:
      for seed in SEEDS:
        p = d / f"{key}-{seed}.png"
        if p.exists():
            continue
        # 画風を先頭に置く（先頭の言葉ほど効く）。体は小さめに収め、端で切れないようにする
        # 「 style」を含めると design.py がアニメ塗りの決まり文句を付けない
        prompt = f"{style} style, {feat}, full body, small in frame"
        r = subprocess.run([sys.executable, str(ROOT / "tools/gen/design.py"), "draw", str(p), prompt,
                            "--kind", "creature", "--style", "xl", "--seed", str(seed)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(key, seed, "exit", r.returncode, flush=True)


if __name__ == "__main__":
    main()
