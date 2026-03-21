"""AudioSet ラベル → 日本語オノマトペ / 説明 マッピング。"""

# AudioSet tag → (日本語オノマトペ, 日本語カテゴリ説明)
# オノマトペが適切でないもの（楽器名など）はカテゴリ説明のみ
AUDIOSET_JA: dict[str, tuple[str, str]] = {
    # ── 音楽 / 楽器 ─────────────────────────────────
    "Music": ("♪", "音楽"),
    "Musical instrument": ("♪", "楽器"),
    "Guitar": ("ジャーン", "ギター"),
    "Piano": ("ポロロン", "ピアノ"),
    "Electric piano": ("ポロロン", "エレピ"),
    "Keyboard (musical)": ("ポロロン", "キーボード"),
    "Synthesizer": ("ブーン", "シンセサイザー"),
    "Drum": ("ドンドン", "ドラム"),
    "Drum kit": ("ドコドコ", "ドラムキット"),
    "Drum machine": ("ドッドッ", "ドラムマシン"),
    "Drum and bass": ("ドゥンドゥン", "ドラムンベース"),
    "Harp": ("ポロロン", "ハープ"),
    "Glockenspiel": ("キラキラ", "グロッケン"),
    "Mallet percussion": ("コンコン", "鍵盤打楽器"),
    "Marimba, xylophone": ("コロコロ", "マリンバ・木琴"),
    "Percussion": ("ドンドン", "打楽器"),
    "Tambourine": ("シャンシャン", "タンバリン"),
    "Maraca": ("シャカシャカ", "マラカス"),
    "Rattle (instrument)": ("カラカラ", "ガラガラ"),
    "Singing bowl": ("ゴーン", "シンギングボウル"),
    "Gong": ("ゴーン", "ゴング"),
    "Plucked string instrument": ("ポロン", "撥弦楽器"),
    "Pizzicato": ("ピチカート", "ピチカート"),
    # ── 音楽ジャンル ──────────────────────────────────
    "Ambient music": ("", "アンビエント"),
    "Electronic music": ("", "エレクトロニカ"),
    "Electronic dance music": ("", "EDM"),
    "Dubstep": ("ウォブウォブ", "ダブステップ"),
    "Trance music": ("", "トランス"),
    "New-age music": ("", "ニューエイジ"),
    "Scary music": ("", "恐怖音楽"),
    "Video game music": ("", "ゲーム音楽"),
    "Music for children": ("", "子供向け音楽"),
    "Lullaby": ("", "子守唄"),
    "Beatboxing": ("ボッボッ", "ビートボックス"),
    # ── 歌声 ─────────────────────────────────────────
    "Singing": ("♪", "歌"),
    "Female singing": ("♪", "女性の歌声"),
    "Male singing": ("♪", "男性の歌声"),
    "Child singing": ("♪", "子供の歌声"),
    "Synthetic singing": ("♪", "合成歌声"),
    "Humming": ("フンフン", "ハミング"),
    # ── 声 / 話し声 ──────────────────────────────────
    "Speech": ("", "話し声"),
    "Male speech, man speaking": ("", "男性の声"),
    "Female speech, woman speaking": ("", "女性の声"),
    "Child speech, kid speaking": ("", "子供の声"),
    "Conversation": ("", "会話"),
    "Narration, monologue": ("", "ナレーション"),
    "Whispering": ("ヒソヒソ", "ささやき"),
    "Speech synthesizer": ("", "音声合成"),
    # ── 感情・生理的な声 ─────────────────────────────
    "Laughter": ("アハハ", "笑い声"),
    "Giggle": ("クスクス", "くすくす笑い"),
    "Chuckle, chortle": ("フフッ", "含み笑い"),
    "Snicker": ("ニヤニヤ", "忍び笑い"),
    "Baby laughter": ("キャッキャ", "赤ちゃんの笑い"),
    "Crying, sobbing": ("エーン", "泣き声"),
    "Baby cry, infant cry": ("オギャー", "赤ちゃんの泣き声"),
    "Whimper": ("クスン", "すすり泣き"),
    "Wail, moan": ("うーん", "うめき声"),
    "Groan": ("ウウッ", "うなり声"),
    "Grunt": ("ウッ", "うなり"),
    "Sigh": ("ハァ", "ため息"),
    "Screaming": ("キャー", "叫び声"),
    "Yell": ("ワー", "大声"),
    "Gasp": ("ハッ", "息を呑む"),
    # ── 呼吸・生理音 ─────────────────────────────────
    "Breathing": ("スーハー", "呼吸"),
    "Wheeze": ("ゼーゼー", "喘ぎ"),
    "Sniff": ("クンクン", "鼻を鳴らす"),
    "Snort": ("フンッ", "鼻息"),
    "Cough": ("ゴホゴホ", "咳"),
    "Sneeze": ("ハクション", "くしゃみ"),
    "Hiccup": ("ヒック", "しゃっくり"),
    "Burping, eructation": ("ゲップ", "げっぷ"),
    "Throat clearing": ("エヘン", "咳払い"),
    "Gargling": ("ガラガラ", "うがい"),
    "Stomach rumble": ("グルグル", "お腹の音"),
    "Fart": ("ブー", "おなら"),
    # ── 水 / 液体 ────────────────────────────────────
    "Water": ("ジャー", "水"),
    "Water tap, faucet": ("ジャージャー", "蛇口"),
    "Drip": ("ポタポタ", "水滴"),
    "Pour": ("トクトク", "注ぐ"),
    "Fill (with liquid)": ("ジャー", "液体を注ぐ"),
    "Trickle, dribble": ("チョロチョロ", "ちょろちょろ流れる"),
    "Stream": ("サラサラ", "小川"),
    "Waterfall": ("ゴーゴー", "滝"),
    "Bathtub (filling or washing)": ("ジャバジャバ", "浴槽"),
    "Sink (filling or washing)": ("ジャー", "流し台"),
    "Gurgling": ("ゴボゴボ", "ゴボゴボ"),
    "Liquid": ("チャプチャプ", "液体"),
    "Splash, splashing": ("バシャ", "水しぶき"),
    "Babbling": ("ブクブク", "泡立ち"),
    "Spray": ("シュー", "スプレー"),
    "Steam": ("シュー", "蒸気"),
    "Plop": ("ポチャン", "ぽちゃん"),
    "Squish": ("グチュ", "ぐちゅ"),
    # ── 衝撃 / 打撃 ─────────────────────────────────
    "Bang": ("バン", "爆発音"),
    "Whack, thwack": ("バシッ", "叩く"),
    "Crack": ("パキッ", "割れる"),
    "Crunch": ("バリバリ", "砕く"),
    "Crushing": ("グシャ", "押しつぶす"),
    "Breaking": ("ガシャン", "壊れる"),
    "Shatter": ("ガシャーン", "粉砕"),
    "Thunk": ("ドスン", "鈍い音"),
    "Knock": ("コンコン", "ノック"),
    "Clang": ("カーン", "金属音"),
    "Chink, clink": ("チリン", "金属がぶつかる"),
    "Boing": ("ボヨン", "弾む"),
    "Ding": ("チーン", "チーン"),
    "Ding-dong": ("ピンポーン", "ピンポン"),
    # ── 摩擦 / きしみ ───────────────────────────────
    "Creak": ("ギシギシ", "きしむ"),
    "Squeak": ("キーキー", "きしむ"),
    "Scrape": ("ガリガリ", "削る"),
    "Scratch": ("カリカリ", "引っかく"),
    "Rub": ("ゴシゴシ", "こする"),
    "Rustle": ("カサカサ", "かさかさ"),
    "Crumpling, crinkling": ("クシャクシャ", "くしゃくしゃ"),
    "Crackle": ("パチパチ", "パチパチ"),
    "Filing (rasp)": ("シャリシャリ", "やすりがけ"),
    # ── 機械 / 道具 ─────────────────────────────────
    "Clicking": ("カチッ", "クリック"),
    "Clickety-clack": ("カタカタ", "カタカタ"),
    "Typewriter": ("カタカタ", "タイプライター"),
    "Scissors": ("チョキチョキ", "はさみ"),
    "Sewing machine": ("カタカタ", "ミシン"),
    "Zipper (clothing)": ("ジッ", "ジッパー"),
    "Camera": ("カシャ", "カメラ"),
    "Single-lens reflex camera": ("カシャッ", "一眼レフ"),
    "Toothbrush": ("シャカシャカ", "歯ブラシ"),
    "Writing": ("サラサラ", "書く"),
    "Clock": ("チクタク", "時計"),
    "Tick": ("カチカチ", "刻む"),
    "Keys jangling": ("ジャラジャラ", "鍵"),
    "Coin (dropping)": ("チャリン", "硬貨"),
    "Jingle bell": ("リンリン", "鈴"),
    "Jingle, tinkle": ("チリンチリン", "鈴の音"),
    "Zing": ("ビュン", "ビュン"),
    # ── ドア / 建具 ──────────────────────────────────
    "Door": ("バタン", "ドア"),
    "Sliding door": ("ガラガラ", "引き戸"),
    # ── 乗り物 / エンジン ────────────────────────────
    "Vehicle": ("ブーン", "乗り物"),
    "Engine": ("ブルルン", "エンジン"),
    "Train": ("ガタンゴトン", "電車"),
    "Railroad car, train wagon": ("ガタゴト", "列車"),
    "Rail transport": ("ガタンゴトン", "鉄道"),
    "Honk": ("プップー", "クラクション"),
    "Air horn, truck horn": ("パーン", "ホーン"),
    # ── 武器 / 爆発 ─────────────────────────────────
    "Gunshot, gunfire": ("パーン", "銃声"),
    "Machine gun": ("ダダダダ", "機関銃"),
    "Cap gun": ("パンッ", "火薬銃"),
    "Fusillade": ("ダダダダ", "一斉射撃"),
    "Artillery fire": ("ドーン", "砲撃"),
    "Firecracker": ("パンパン", "爆竹"),
    "Fireworks": ("ドーン", "花火"),
    "Arrow": ("ヒュン", "矢"),
    # ── 動物 ─────────────────────────────────────────
    "Animal": ("", "動物"),
    "Dog": ("ワンワン", "犬"),
    "Bark": ("ワン", "犬の吠え声"),
    "Cat": ("ニャー", "猫"),
    "Meow": ("ニャー", "猫の鳴き声"),
    "Purr": ("ゴロゴロ", "猫のゴロゴロ"),
    "Caterwaul": ("ギャー", "猫の叫び"),
    "Bird": ("チュンチュン", "鳥"),
    "Crow": ("カーカー", "カラス"),
    "Caw": ("カーカー", "カラスの鳴き声"),
    "Owl": ("ホーホー", "フクロウ"),
    "Hoot": ("ホーホー", "フクロウの鳴き声"),
    "Duck": ("ガーガー", "アヒル"),
    "Quack": ("ガーガー", "アヒルの鳴き声"),
    "Goose": ("ガーガー", "ガチョウ"),
    "Chicken, rooster": ("コケコッコー", "鶏"),
    "Gobble": ("ゴロゴロ", "七面鳥"),
    "Turkey": ("", "七面鳥"),
    "Fowl": ("", "家禽"),
    "Frog": ("ケロケロ", "カエル"),
    "Snake": ("シャー", "蛇"),
    "Pig": ("ブヒブヒ", "豚"),
    "Oink": ("ブヒッ", "豚の鳴き声"),
    "Goat": ("メェー", "ヤギ"),
    "Bleat": ("メェー", "ヤギの鳴き声"),
    "Sheep": ("メェー", "羊"),
    "Whale vocalization": ("", "クジラの声"),
    "Rodents, rats, mice": ("チューチュー", "ネズミ"),
    "Domestic animals, pets": ("", "ペット"),
    # ── 環境 / 場所 ─────────────────────────────────
    "Inside, small room": ("", "室内"),
    "Outside, rural or natural": ("", "屋外・自然"),
    "Silence": ("シーン", "無音"),
    "Rumble": ("ゴゴゴ", "低い轟き"),
    "Whoosh, swoosh, swish": ("ヒュー", "風切り音"),
    "Hiss": ("シュー", "シュー音"),
    "White noise": ("サー", "ホワイトノイズ"),
    "Pink noise": ("ザー", "ピンクノイズ"),
    "Sine wave": ("ピー", "正弦波"),
    "Sonar": ("ピーン", "ソナー"),
    "Dial tone": ("ツー", "ダイヤルトーン"),
    "Sound effect": ("", "効果音"),
    "Effects unit": ("", "エフェクト"),
    # ── ガラス / 食器 ────────────────────────────────
    "Glass": ("カチン", "ガラス"),
    "Dishes, pots, and pans": ("ガチャガチャ", "食器"),
    # ── 食事 ─────────────────────────────────────────
    "Chewing, mastication": ("モグモグ", "噛む"),
    "Biting": ("ガブッ", "噛みつく"),
    "Chopping (food)": ("トントン", "刻む"),
    "Chop": ("ザクッ", "切る"),
    # ── 手 / 体 ─────────────────────────────────────
    "Hands": ("", "手"),
    "Clapping": ("パチパチ", "拍手"),
    "Shuffle": ("ズルズル", "すり足"),
    "Shuffling cards": ("シャッシャッ", "カード切り"),
    # ── 木 / 素材 ────────────────────────────────────
    "Wood": ("コンコン", "木"),
    "Tearing": ("ビリビリ", "破る"),
    # ── 機械 / 工具 ─────────────────────────────────
    "Mechanisms": ("ガチャガチャ", "機械"),
    "Gears": ("ガリガリ", "歯車"),
    "Pulleys": ("ギーギー", "滑車"),
    "Chainsaw": ("ブイーン", "チェーンソー"),
    "Drill": ("ウィーン", "ドリル"),
    "Dental drill, dentist's drill": ("キュイーン", "歯医者のドリル"),
    "Power tool": ("ウィーン", "電動工具"),
    "Tools": ("", "工具"),
    "Ratchet, pawl": ("カチカチ", "ラチェット"),
}


def get_japanese_description(tags: dict[str, float], audio_type: str, transcript: str | None = None) -> str:
    """タグと種別から日本語の音の説明を生成する。

    Parameters:
        tags: AudioSet タグ名 → 信頼度
        audio_type: "bgm", "se", "voice"
        transcript: Whisper による文字起こし (あれば)

    Returns:
        日本語の音の説明テキスト
    """
    # Voice でトランスクリプトがある場合
    if audio_type == "voice" and transcript:
        return f"[{transcript}]"

    parts_onomatopoeia: list[str] = []
    parts_description: list[str] = []

    for tag, conf in tags.items():
        if conf < 0.08:
            continue
        if tag in AUDIOSET_JA:
            onomatopoeia, desc = AUDIOSET_JA[tag]
            if onomatopoeia and onomatopoeia not in parts_onomatopoeia:
                parts_onomatopoeia.append(onomatopoeia)
            if desc not in parts_description:
                parts_description.append(desc)

    # オノマトペ優先、なければカテゴリ説明
    if parts_onomatopoeia:
        result = "・".join(parts_onomatopoeia[:3])
        if parts_description:
            result += f"（{'/'.join(parts_description[:3])}）"
        return result

    if parts_description:
        return "/".join(parts_description[:3])

    # マッピングにない場合はトップタグをそのまま
    if tags:
        top_tag = next(iter(tags))
        return top_tag

    return ""
