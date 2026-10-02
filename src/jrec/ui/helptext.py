"""Help content (Concepts, Glossary) in English, 简体中文, 日本語, 한국어. The same term is used
everywhere in the UI; `en` keeps the English term so search works in any language."""
from .. import i18n
from .. import theme as th

# (icon, en term, {lang: (term, text, where)})
_CONCEPTS = [
    (th.ICON_FILES, "Recording", {
        "en": ("Recording", "An original file copied from the recorder. It is kept read-only with a SHA-256 hash and never changed.",
               "Sidebar › Files"),
        "zh-CN": ("录音", "从录音笔复制的原始文件。以只读方式保存并记录 SHA-256 校验值，永不修改。", "侧栏 › 文件"),
        "ja": ("録音", "レコーダーからコピーした元のファイル。SHA-256 付きで読み取り専用のまま保存し、変更しません。", "サイドバー › ファイル"),
        "ko": ("녹음", "녹음기에서 복사한 원본 파일. SHA-256 해시와 함께 읽기 전용으로 보관하며 절대 바꾸지 않습니다.", "사이드바 › 파일")}),
    (th.ICON_TALKS, "Conversation", {
        "en": ("Conversation", "A stretch of speech found in a recording, cut byte-exact with at least 10 minutes of the original before and after as evidence.",
               "Sidebar › Talks"),
        "zh-CN": ("对话", "在录音中找到的一段说话，按字节精确剪出，前后至少保留 10 分钟原始音频作为证据。", "侧栏 › 对话"),
        "ja": ("会話", "録音の中で見つかった発話の区間。前後に少なくとも 10 分の元の音声を証拠として残し、バイト単位で正確に切り出します。", "サイドバー › 会話"),
        "ko": ("대화", "녹음에서 찾은 말소리 구간. 앞뒤로 원본 10분 이상을 증거로 남기고 바이트 단위로 정확히 잘라 냅니다.", "사이드바 › 대화")}),
    (th.ICON_WAND, "Transcribe", {
        "en": ("Transcribe", "Speech to text on your own GPU (Qwen3-ASR), with word timings and who spoke when. Runs in the task queue.",
               "Sidebar › Transcribe new; a conversation's header"),
        "zh-CN": ("转写", "在本机 GPU 上把语音转成文字（Qwen3-ASR），带词级时间和说话人。在任务队列中运行。", "侧栏 › 转写新录音；对话标题栏"),
        "ja": ("文字起こし", "自分の GPU で音声をテキストに（Qwen3-ASR）。単語の時刻と話者付き。タスクキューで実行します。", "サイドバー › 新しい録音を文字起こし"),
        "ko": ("전사", "내 GPU에서 음성을 텍스트로 (Qwen3-ASR). 단어 시간과 화자 포함. 작업 대기열에서 실행됩니다.", "사이드바 › 새 녹음 전사")}),
    (th.ICON_LIST_CHECK, "Task queue", {
        "en": ("Task queue", "Long jobs wait here and run one at a time. Pause, stop, cancel or retry them; the list survives a restart.",
               "Top right › Tasks and logs (Ctrl+J)"),
        "zh-CN": ("任务队列", "长时间工作在这里排队，一次运行一个。可暂停、停止、取消或重试；重启后仍保留。", "右上角 › 任务和日志（Ctrl+J）"),
        "ja": ("タスクキュー", "長い処理はここで待ち、1 つずつ実行します。一時停止・停止・キャンセル・再試行ができ、再起動後も残ります。", "右上 › タスクとログ（Ctrl+J）"),
        "ko": ("작업 대기열", "긴 작업이 여기서 기다렸다가 하나씩 실행됩니다. 일시 중지, 중지, 취소, 다시 시도 가능하며 다시 시작해도 남습니다.", "오른쪽 위 › 작업 및 로그 (Ctrl+J)")}),
    (th.ICON_MOMENTS, "A–B range", {
        "en": ("A–B range", "A stretch of the timeline you mark to repeat, save as a moment or export byte-exact.",
               "Timeline: Shift+drag, or [ and ]"),
        "zh-CN": ("A–B 区间", "在时间轴上标记的一段，可重复播放、存为片段或按字节精确导出。", "时间轴：Shift+拖动，或 [ 和 ]"),
        "ja": ("A–B 区間", "タイムライン上で印を付けた区間。リピート、モーメントとして保存、バイト単位で書き出しができます。", "タイムライン：Shift+ドラッグ、または [ と ]"),
        "ko": ("A–B 구간", "타임라인에 표시한 구간. 반복 재생, 순간으로 저장, 바이트 단위 내보내기가 가능합니다.", "타임라인: Shift+드래그 또는 [ 와 ]")}),
    (th.ICON_EYE, "Insights", {
        "en": ("Insights", "People, places, contacts, times, money and the rows that matter, with guesses about how speakers know each other.",
               "Right column › Insights"),
        "zh-CN": ("洞察", "人物、地点、联系方式、时间、金额和重要的行，并推测说话人之间的关系。", "右栏 › 洞察"),
        "ja": ("インサイト", "人物・場所・連絡先・時刻・金額・重要な行と、話者どうしの関係の推測。", "右の列 › インサイト"),
        "ko": ("인사이트", "사람, 장소, 연락처, 시간, 금액, 중요한 행과 화자들 관계 추측.", "오른쪽 열 › 인사이트")}),
]

_GLOSSARY = [
    ("Evidence window", {
        "en": ("Evidence window", "The 10 minutes or more of untouched original kept before and after each conversation."),
        "zh-CN": ("证据窗口", "每段对话前后保留的至少 10 分钟未改动的原始音频。"),
        "ja": ("証拠ウィンドウ", "各会話の前後に残す、手を加えていない 10 分以上の元の音声。"),
        "ko": ("증거 구간", "각 대화 앞뒤로 남기는 손대지 않은 원본 10분 이상.")}, ["Conversation", "Verify clips"]),
    ("Verify clips", {
        "en": ("Verify clips", "Re-check every clip byte for byte against the archived original."),
        "zh-CN": ("校验片段", "逐字节重新核对每个片段与存档原件是否一致。"),
        "ja": ("クリップを検証", "すべてのクリップを保存した元の録音とバイト単位で照合します。"),
        "ko": ("클립 확인", "모든 클립을 보관된 원본과 바이트 단위로 다시 대조합니다.")}, ["Evidence window"]),
    ("Moment", {
        "en": ("Moment", "A saved A–B range with a note, listed under Moments."),
        "zh-CN": ("片段", "保存下来的带笔记的 A–B 区间，列在“片段”中。"),
        "ja": ("モーメント", "メモ付きで保存した A–B 区間。「モーメント」に一覧されます。"),
        "ko": ("순간", "메모와 함께 저장한 A–B 구간, ‘순간’ 목록에 표시.")}, ["A–B range"]),
    ("Note", {
        "en": ("Note", "Your own comment at a point of the timeline; it never changes the audio."),
        "zh-CN": ("笔记", "你在时间轴某一点写的备注，不会改变音频。"),
        "ja": ("メモ", "タイムライン上の位置に付ける自分のコメント。音声は変わりません。"),
        "ko": ("메모", "타임라인의 한 지점에 다는 내 의견, 오디오는 바뀌지 않음.")}, ["Moment"]),
    ("Speaker", {
        "en": ("Speaker", "A voice found by diarization, shown as Char 1, Char 2… until you name it."),
        "zh-CN": ("说话人", "通过说话人分离找到的声音，命名前显示为 Char 1、Char 2…"),
        "ja": ("話者", "話者分離で見つかった声。名前を付けるまで Char 1、Char 2… と表示。"),
        "ko": ("화자", "화자 분리로 찾은 목소리, 이름을 붙이기 전에는 Char 1, Char 2… 로 표시.")}, ["Insights"]),
    ("Clearer", {
        "en": ("Clearer", "A live noise filter while listening; the file is not changed."),
        "zh-CN": ("更清晰", "收听时的实时降噪，文件不变。"),
        "ja": ("クリア", "聞いている間だけ働くノイズフィルター。ファイルは変わりません。"),
        "ko": ("더 선명하게", "듣는 동안만 작동하는 잡음 필터, 파일은 바뀌지 않음.")}, ["Cleaned"]),
    ("Cleaned", {
        "en": ("Cleaned", "A separate DeepFilterNet copy for listening; the original stays as it was."),
        "zh-CN": ("降噪版", "用 DeepFilterNet 另外生成的收听副本；原件保持不变。"),
        "ja": ("ノイズ除去", "聞くための DeepFilterNet の別コピー。元の録音はそのまま。"),
        "ko": ("잡음 제거", "듣기용 DeepFilterNet 별도 사본, 원본은 그대로.")}, ["Clearer"]),
    ("Tag", {
        "en": ("Tag", "A label on a conversation; search it with tag:name."),
        "zh-CN": ("标签", "对话上的标记；用 tag:名称 搜索。"),
        "ja": ("タグ", "会話に付けるラベル。tag:名前 で検索。"),
        "ko": ("태그", "대화에 붙이는 라벨, tag:이름 으로 검색.")}, []),
    ("jev", {
        "en": ("jev", "Julia-1, a local model that scores choices: relationships, importance and how well a claim is supported."),
        "zh-CN": ("jev", "Julia-1，本地打分模型：关系、重要性以及说法有多少依据。"),
        "ja": ("jev", "Julia-1。関係・重要度・主張の裏付けを採点するローカルモデル。"),
        "ko": ("jev", "Julia-1, 관계·중요도·주장 근거를 점수로 매기는 로컬 모델.")}, ["Insights"]),
    ("Search syntax", {
        "en": ("Search syntax", "Words in any order; OR; -word or NOT; ( ); \"phrase\"; /regex/; note: tag: by: lang: time: date:."),
        "zh-CN": ("搜索语法", "词序不限；OR；-词 或 NOT；( )；\"短语\"；/正则/；note: tag: by: lang: time: date:。"),
        "ja": ("検索の書き方", "語順自由・OR・-語 または NOT・( )・\"フレーズ\"・/正規表現/・note: tag: by: lang: time: date:。"),
        "ko": ("검색 문법", "단어 순서 무관, OR, -단어 또는 NOT, ( ), \"구문\", /정규식/, note: tag: by: lang: time: date:.")}, []),
]


def concepts():
    lang = i18n.lang()
    out = []
    for icon, en, tr in _CONCEPTS:
        term, text, where = tr.get(lang, tr["en"])
        out.append({"icon": icon, "en": en, "term": term, "text": text, "where": where})
    return out


def glossary():
    lang = i18n.lang()
    out = []
    for en, tr, related in _GLOSSARY:
        term, text = tr.get(lang, tr["en"])
        rel = [next((t.get(lang, t["en"])[0] for e2, t, _ in _GLOSSARY if e2 == r), r) for r in related]
        out.append({"en": en, "term": term, "text": text, "related": rel})
    return out
