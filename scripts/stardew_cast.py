#!/usr/bin/env python3
"""stardew_cast —— 星露谷物语全员演员卡(游戏还原模式,look="game").

已入库 4 人(角色C_阿比盖尔/D_艾米丽/E_莉亚/F_潘妮)不再重做;
本名单补齐其余 25 名成年村民(排除儿童 Jas/Vincent、少年 Leo、非人形 Krobus/矮人)。
外观按 wiki/sprite 公认特征转写实人脸 DNA;提交: python3 scripts/stardew_cast.py [起始下标] [人数]
"""
import json
import random
import sys
import urllib.request

BASE = "http://127.0.0.1:8620"

# (name, positioning_cn, face_dna, outfit_dna)  —— look 一律 game
CAST = [
    # ── 可婚角色(剩余 8)──
    ("亚历克斯", "星露谷运动系男主:阳光自恋的橄榄球少年",
     "athletic young man with short sandy-blond hair, warm tan skin, bright hazel eyes, "
     "confident wide grin, muscular gridball-player build in his early twenties",
     "a green letterman jacket with yellow trim over a white tee, dark slim jeans, "
     "white sneakers, a gridball tucked under one arm"),
    ("艾利欧特", "星露谷文艺系男主:海滩木屋里的浪漫小说家",
     "refined young man in his late twenties with long flowing copper-red wavy hair tied "
     "loosely at the nape, fair skin, gentle green eyes, romantic literary aura",
     "an elegant teal velvet frock coat over a ruffled white poet shirt, tailored brown "
     "trousers, polished leather boots"),
    ("海莉", "星露谷时尚系女主:爱拍照的甜心辣妹",
     "fashionable young woman in her early twenties with long silky golden-blonde hair, "
     "bright blue eyes, fair glowing skin, bubbly confident smile",
     "a pink cropped cardigan over a white camisole, light denim skirt, small pearl "
     "earrings, pink sandals"),
    ("玛鲁", "星露谷理工系女主:天文台发明家少女",
     "curious young woman in her early twenties with warm brown skin, black hair pulled "
     "into a short ponytail with a yellow headband, bright amber eyes, intelligent "
     "sparkling gaze",
     "a mustard-yellow long-sleeved knit top under a canvas work apron filled with small "
     "tools and gadget parts, cargo pants, practical sneakers"),
    ("山姆", "星露谷活力系男主:滑板乐队少年",
     "energetic young man in his early twenties with tousled spiky sun-blond hair, blue "
     "eyes, light freckles across the nose, playful skater grin",
     "a bright blue hoodie over a graphic tee, ripped slim jeans, colorful skateboard "
     "sneakers, a yellow skateboard beside him"),
    ("塞巴斯蒂安", "星露谷暗黑系男主:车库里的程序员浪子",
     "pale introverted young man in his mid twenties with straight black hair and "
     "side-swept bangs, cool gray-blue eyes, quietly brooding expression, slender build",
     "a black zip-up motorcycle jacket over a dark band tee, black slim jeans, silver "
     "rings, worn black boots"),
    ("谢恩", "星露谷救赎系男主:借酒消愁的Joja职员",
     "rugged young man in his late twenties with messy dark brown hair, pale tired blue "
     "eyes, light stubble along the jaw, guarded defensive expression",
     "a royal-blue JojaMart staff vest over a gray tee, worn dark jeans, scuffed work "
     "boots"),
    ("哈维", "星露谷温柔系男主:小镇飞行梦医生",
     "gentle bookish man in his early thirties with neat short chestnut-brown hair, round "
     "wire-frame glasses, warm hazel eyes, a thin mustache, caring slightly-nervous smile",
     "a sage-green button-up shirt with a brown knit sweater vest, dark trousers, a "
     "stethoscope draped around the neck, polished brown shoes"),
    # ── 村民(17)──
    ("罗宾", "星露谷木匠大姐:山顶工坊的当家人",
     "strong capable woman in her forties with a vivid copper-red chin-length bob, rosy "
     "freckled cheeks, sturdy carpenter build, hearty welcoming smile",
     "an olive-green utility work shirt with rolled sleeves over a white tee, a worn "
     "leather tool belt, straight-cut jeans, scuffed work boots"),
    ("德米特里厄斯", "星露谷科学家:山上实验室的父亲",
     "distinguished Black scientist in his forties with short salt-and-pepper black hair, "
     "rectangular glasses, warm thoughtful brown eyes, calm professorial presence",
     "a lavender-purple button-up shirt under a dark gray blazer, khaki trousers, a field "
     "notebook in the chest pocket"),
    ("莱纳斯", "星露谷隐士:山间帐篷里的善良老人",
     "weathered kind-hearted hermit in his sixties with deeply tanned leathery skin, a "
     "mostly bald head fringed with white hair, gentle humble eyes, wiry build",
     "a patched heavy brown canvas coat over layered worn shirts, fingerless gloves, "
     "sturdy old boots, a simple cloth satchel"),
    ("皮埃尔", "星露谷杂货店老板:镇上的小商人",
     "neat shopkeeper man in his forties with short brown hair, a well-trimmed mustache, "
     "small shrewd brown eyes, polite merchant smile",
     "a crisp white shirt with sleeves rolled, a green shop apron, dark pressed "
     "trousers, comfortable store shoes"),
    ("卡罗琳", "星露谷茶艺主妇:阿比盖尔的母亲",
     "serene woman in her forties with dark teal-green hair in a neat low bun, soft green "
     "eyes, a gentle tea-loving calm smile",
     "a flowing sage-green blouse with a light cardigan, a long earth-toned skirt, simple "
     "jade earrings"),
    ("乔治", "星露谷固执老人:炉边的外公",
     "gruff elderly man in his late seventies with a bald crown and white side hair, deep "
     "frown lines, thick gray eyebrows, stubborn proud expression",
     "a red knit cardigan over a checked flannel shirt, brown trousers, a wooden cane, "
     "warm wool slippers"),
    ("伊芙琳", "星露谷慈祥奶奶:镇上的老甜心",
     "sweet elderly woman in her late seventies with soft white hair in a neat bun, pale "
     "blue eyes, gentle smile lines, frail but warm grandmotherly face",
     "a pink floral-print dress with a small white collar, a knitted lavender cardigan, "
     "simple pearl earrings, comfortable shoes"),
    ("刘易斯", "星露谷镇长:爱面子的老领导",
     "portly self-important mayor in his sixties with gray-brown combed-back hair, a "
     "thick mustache, small shrewd eyes, pompous avuncular smile",
     "a golden-yellow dress shirt with buttoned sleeves, a purple patterned neckerchief, "
     "dark slacks, polished brown loafers"),
    ("克林特", "星露谷铁匠:羞涩的打铁人",
     "stocky shy blacksmith in his thirties with thick dark brown hair, heavy stubble, "
     "muscular arms, reserved awkward expression",
     "a heavy dark-blue blacksmith apron over a rolled-sleeve gray work shirt, "
     "soot-stained leather gloves tucked in the belt, sturdy boots"),
    ("帕姆", "星露谷大巴司机:帕姆阿姨的豪爽与落魄",
     "gruff broad-shouldered woman in her fifties with bleach-blonde choppy short hair, "
     "ruddy weathered face, loud tired laugh lines",
     "a faded plum-purple long-sleeve shirt under a worn denim vest, jeans, heavy work "
     "boots, a well-used bus driver cap in hand"),
    ("玛妮", "星露谷牧场主:养牛大姐的温柔",
     "warm curvy rancher woman in her forties with wavy honey-brown shoulder-length hair, "
     "rosy cheeks, a motherly earthy smile",
     "a cozy olive-green long-sleeved knit top with denim overalls, leather work gloves "
     "tucked in a pocket, rubber farm boots"),
    ("古斯", "星露谷酒馆老板:热情的大厨",
     "jolly heavyset Black chef in his fifties with a clean-shaven bald head, a neat black "
     "goatee, round friendly face, warm hospitable grin",
     "a crisp white double-breasted chef jacket with the sleeves rolled, a long white "
     "apron, checked chef trousers, non-slip kitchen shoes"),
    ("威利", "星露谷老渔夫:码头的钓鱼传说",
     "weathered old fisherman in his sixties with a bushy gray beard and matching long "
     "gray hair under a worn fishing bucket hat, sea-worn ruddy skin, crinkled kind eyes",
     "a bright yellow slicker raincoat over a chunky knit sweater, olive waders, heavy "
     "rubber boots, an old pipe and a tackle box beside him"),
    ("桑迪", "星露谷沙漠店主:绿洲商会的神秘美人",
     "mysterious desert shopkeeper in her thirties with fair sun-shy skin, golden-blonde "
     "hair tucked beneath a rust-red wrapped headscarf veil, striking teal-green eyes "
     "with soft blue eyeshadow, gold hoop earrings, an enigmatic warm smile",
     "a flowing turquoise-and-rust patterned desert dress with layered bead necklaces, "
     "embroidered sandals"),
    ("拉斯莫迪乌斯", "星露谷法师:塔楼里的隐世魔法师",
     "arcane old wizard in his sixties with long silver-white hair and a flowing beard, "
     "deep-set piercing pale eyes, mysterious gaunt features",
     "a deep purple hooded sorcerer robe with silver celestial embroidery, a rope belt "
     "hung with pouches of reagents, worn leather boots"),
    ("马隆", "星露谷冒险家工会:独眼老佣兵",
     "battle-scarred old adventurer in his sixties with an iron eyepatch over his left "
     "eye, long gray-streaked dark hair tied back, a weathered scarred face, stalwart "
     "mercenary posture",
     "a maroon leather pauldron over a studded battle tunic, a heavy adventurer cloak, a "
     "leather bracer, sturdy travel boots, a greatsword sheathed on his back"),
    ("莫里斯", "星露谷反派示人:Joja商务经理",
     "slick corporate manager in his forties with neatly gelled-back chestnut hair, thin "
     "arched eyebrows, a wide insincere salesman smile",
     "a sharp navy-blue Joja corporate suit with a light blue tie and a Joja name badge, "
     "polished black shoes"),
]


def build_cards(start=0, count=None):
    rows = CAST[start:start + count] if count else CAST[start:]
    return [{"name": n, "positioning_cn": p, "face_dna": f, "outfit_dna": o,
             "look": "game", "seed": random.randint(1_000_000, 9_999_999)}
            for n, p, f, o in rows]


def main():
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    count = int(sys.argv[2]) if len(sys.argv) > 2 else None
    cards = build_cards(start, count)
    out = f"stardew_cards_{start}.json"
    with open(out, "w") as f:
        json.dump(cards, f, ensure_ascii=False, indent=1)
    print(f"{len(cards)} 张卡已写 {out}: {[c['name'] for c in cards]}")
    if "--submit" in sys.argv:
        body = json.dumps({"cards": cards}).encode()
        req = urllib.request.Request(BASE + "/api/audition/sign-cards", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
        print("job:", d["job_id"], d["job"]["title"])


if __name__ == "__main__":
    main()
