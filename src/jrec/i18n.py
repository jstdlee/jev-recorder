"""UI languages: English (source), 简体中文, 日本語, 한국어.

T("English text", **params) returns the text in the current UI language (English is the key, so a
missing translation simply shows English). Keep the English short and plain; one term = one meaning.
"""
import locale
import os

LANGS = ["en", "zh-CN", "ja", "ko"]
LANG_NAMES = ["English", "简体中文", "日本語", "한국어"]
_current = "en"


def system_lang():
    for v in (os.environ.get("LC_ALL"), os.environ.get("LC_MESSAGES"), os.environ.get("LANG"),
              (locale.getlocale()[0] if locale.getlocale() else None)):
        v = (v or "").lower()
        if v.startswith("zh"):
            return "zh-CN"
        if v.startswith("ja"):
            return "ja"
        if v.startswith("ko"):
            return "ko"
        if v:
            return "en"
    return "en"


def set_lang(code):
    global _current
    _current = system_lang() if code in (None, "", "system") else code if code in LANGS else "en"


def lang():
    return _current


MISSING = set() if os.environ.get("JREC_I18N_MISSING") else None   # dev: collect untranslated strings


def _split(s):
    """'<icon> Label##id' -> ('<icon> ', 'Label', '##id'): only the words are looked up."""
    head = ""
    while s and "\ue000" <= s[0] <= "\uf8ff":
        head += s[0]
        s = s[1:]
    if head:
        sp = len(s) - len(s.lstrip(" "))
        head, s = head + s[:sp], s[sp:]
    word, sep, tail = s.partition("##")
    k = len(word)
    while k and (word[k - 1] == " " or "\ue000" <= word[k - 1] <= "\uf8ff"):
        k -= 1
    return head, word[:k], word[k:] + (sep + tail if sep else "")


def T(_s, **kw):
    if _current != "en" and _s and ("\ue000" <= _s[0] <= "\uf8ff" or "\ue000" <= _s[-1] <= "\uf8ff" or "##" in _s):
        head, word, tail = _split(_s)
        return head + T(word, **kw) + tail
    if _current != "en":
        tab = TABLE.get(_current, {})
        if MISSING is not None and _s not in tab and _s.strip() and not _s.isdigit():
            MISSING.add(_s)
    out = TABLE.get(_current, {}).get(_s, _s) if _current != "en" else _s
    return out.format(**kw) if kw else out


_WD = {"zh-CN": "一二三四五六日", "ja": "月火水木金土日", "ko": "월화수목금토일"}


def fmt_date(dt, year=True, weekday=True):
    """'Fri 3 Oct 2025' in English, '2025年10月3日 周五' / '2025年10月3日(金)' / '2025년 10월 3일 (금)'."""
    if _current == "en":
        return dt.strftime(("%a " if weekday else "") + "%-d %b" + (" %Y" if year else ""))
    wd = _WD[_current][dt.weekday()]
    if _current == "ko":
        return (f"{dt.year}년 " if year else "") + f"{dt.month}월 {dt.day}일" + (f" ({wd})" if weekday else "")
    d = (f"{dt.year}年" if year else "") + f"{dt.month}月{dt.day}日"
    if not weekday:
        return d
    return d + (f" 周{wd}" if _current == "zh-CN" else f"({wd})")


# English -> (zh-CN, ja, ko)
_ROWS = {
    # shell
    "Search": ("搜索", "検索", "검색"),
    "Search  Ctrl+P": ("搜索  Ctrl+P", "検索  Ctrl+P", "검색  Ctrl+P"),
    "Tasks and logs": ("任务和日志", "タスクとログ", "작업 및 로그"),
    "Help": ("帮助", "ヘルプ", "도움말"),
    "Settings": ("设置", "設定", "설정"),
    "Minimize": ("最小化", "最小化", "최소화"),
    "Maximize / restore": ("最大化 / 还原", "最大化 / 元に戻す", "최대화 / 복원"),
    "Close": ("关闭", "閉じる", "닫기"),
    "Ready": ("就绪", "準備完了", "준비됨"),
    "Tasks": ("任务", "タスク", "작업"),
    "Logs": ("日志", "ログ", "로그"),
    "Concepts": ("概念", "コンセプト", "개념"),
    "Glossary": ("术语", "用語集", "용어집"),
    "Shortcuts": ("快捷键", "ショートカット", "단축키"),
    "Type a command, setting, help topic or words from a transcript": (
        "输入命令、设置、帮助主题或转写中的文字", "コマンド、設定、ヘルプ、文字起こしの言葉を入力", "명령, 설정, 도움말 또는 대본의 단어 입력"),
    "No results for “{q}”": ("没有找到“{q}”", "「{q}」は見つかりません", "“{q}”에 대한 결과 없음"),
    "Commands": ("命令", "コマンド", "명령"),
    "Talks": ("对话", "会話", "대화"),
    "Transcript": ("转写", "文字起こし", "대본"),
    "Recent": ("最近", "最近", "최근"),
    # sidebar
    "People": ("人物", "人物", "사람"),
    "Files": ("文件", "ファイル", "파일"),
    "Moments": ("片段", "モーメント", "순간"),
    "Tags": ("标签", "タグ", "태그"),
    "Transcribe new": ("转写新录音", "新しい録音を文字起こし", "새 녹음 전사"),
    "Transcribe new ({n})": ("转写新录音（{n}）", "新しい録音を文字起こし（{n}）", "새 녹음 전사 ({n})"),
    "Search: roof (price OR 屋顶) -friday": ("搜索：屋顶 (价格 OR roof) -星期五", "検索：屋根 (価格 OR roof) -金曜", "검색: 지붕 (가격 OR roof) -금요일"),
    "Clear the search": ("清除搜索", "検索をクリア", "검색 지우기"),
    "Conversations, newest first": ("对话，最新的在前", "会話（新しい順）", "대화, 최신순"),
    "Everyone you have named, and where they speak": ("你命名过的人，以及他们在哪里说话", "名前を付けた人と発言箇所", "이름을 붙인 사람과 말한 곳"),
    "Original recordings from the recorder (read-only archive)": ("录音笔的原始录音（只读存档）", "レコーダーの元の録音（読み取り専用）", "녹음기 원본 녹음 (읽기 전용 보관)"),
    "Your notes and saved A–B stretches": ("你的笔记和保存的 A–B 片段", "メモと保存した A–B 区間", "메모와 저장한 A–B 구간"),
    "Create, rename, merge and delete tags; see where each is used": ("新建、重命名、合并和删除标签；查看使用位置", "タグの作成・名前変更・統合・削除、使用場所の確認", "태그 만들기·이름 바꾸기·병합·삭제, 사용 위치 보기"),
    "A job is already running": ("已有任务在运行", "ジョブを実行中です", "이미 작업이 실행 중입니다"),
    "Everything is transcribed": ("全部已转写", "すべて文字起こし済み", "모두 전사됨"),
    "not transcribed": ("未转写", "未文字起こし", "전사 안 됨"),
    "transcribed": ("已转写", "文字起こし済み", "전사됨"),
    "summarized": ("已总结", "要約済み", "요약됨"),
    "Library is empty": ("资料库是空的", "ライブラリは空です", "라이브러리가 비어 있음"),
    "No names yet": ("还没有名字", "まだ名前がありません", "아직 이름 없음"),
    "Nothing saved yet": ("还没有保存内容", "まだ何も保存されていません", "아직 저장된 것 없음"),
    "Add": ("添加", "追加", "추가"),
    # header and actions
    "Transcribe": ("转写", "文字起こし", "전사"),
    "Summarize": ("总结", "要約", "요약"),
    "Summarize again": ("重新总结", "もう一度要約", "다시 요약"),
    "Translate": ("翻译", "翻訳", "번역"),
    "Verify clips": ("校验片段", "クリップを検証", "클립 확인"),
    "Translate the whole transcript into": ("把整份转写翻译成", "文字起こし全体を翻訳：", "전체 대본 번역:"),
    "Clips match the archived originals": ("片段与存档原件一致", "クリップは元の録音と一致", "클립이 원본과 일치함"),
    "Another job is running; see the indicator on the left": ("另一个任务正在运行", "別のジョブを実行中です", "다른 작업이 실행 중입니다"),
    "Speech to text, word timings and speakers in the background (GPU, ~11 GB)": (
        "后台进行语音转文字、词级时间和说话人识别（GPU，约 11 GB）", "音声認識・単語の時刻・話者をバックグラウンドで（GPU 約 11 GB）",
        "백그라운드에서 음성 인식, 단어 시간, 화자 구분 (GPU 약 11GB)"),
    "+ tag": ("+ 标签", "+ タグ", "+ 태그"),
    # player
    "Play": ("播放", "再生", "재생"),
    "Pause": ("暂停", "一時停止", "일시 중지"),
    "Speed": ("速度", "速度", "속도"),
    "Sound": ("声音", "音声", "소리"),
    "Original": ("原始", "オリジナル", "원본"),
    "Clearer": ("更清晰", "クリア", "더 선명하게"),
    "Cleaned": ("降噪版", "ノイズ除去", "잡음 제거"),
    "Channel": ("声道", "チャンネル", "채널"),
    "Both": ("双声道", "両方", "양쪽"),
    "Left": ("左", "左", "왼쪽"),
    "Right": ("右", "右", "오른쪽"),
    "Skip silence": ("跳过静音", "無音をスキップ", "무음 건너뛰기"),
    "Follow": ("跟随", "追従", "따라가기"),
    "Off": ("关", "オフ", "끔"),
    "On": ("开", "オン", "켬"),
    "Once": ("一次", "1 回", "한 번"),
    "Repeat": ("重复", "リピート", "반복"),
    "Set A": ("设 A", "A を設定", "A 설정"),
    "Set B": ("设 B", "B を設定", "B 설정"),
    "Save as moment": ("存为片段", "モーメントとして保存", "순간으로 저장"),
    "Play nearby": ("从附近播放", "前後から再生", "근처부터 재생"),
    "Fit talk": ("对话范围", "会話に合わせる", "대화에 맞춤"),
    "Whole": ("全部", "全体", "전체"),
    "Find in this conversation (Ctrl+F)": ("在本对话中查找（Ctrl+F）", "この会話内を検索（Ctrl+F）", "이 대화에서 찾기 (Ctrl+F)"),
    "Go to 14:15:30, +30, @5:00": ("跳到 14:15:30、+30、@5:00", "移動 14:15:30・+30・@5:00", "이동 14:15:30, +30, @5:00"),
    "or Shift+drag on the timeline": ("或在时间轴上 Shift+拖动", "またはタイムライン上で Shift+ドラッグ", "또는 타임라인에서 Shift+드래그"),
    "matches show in yellow": ("匹配项以黄色显示", "一致箇所は黄色", "일치 항목은 노란색"),
    # transcript
    "Show": ("显示", "表示", "보기"),
    "Rows": ("行", "行", "행"),
    "One line": ("单行", "1 行", "한 줄"),
    "Full text": ("全文", "全文", "전체 텍스트"),
    "Time": ("时间", "時刻", "시간"),
    "By": ("说话人", "話者", "화자"),
    "Text": ("文字", "テキスト", "텍스트"),
    "Notes": ("笔记", "メモ", "메모"),
    "click = select · double-click = play": ("单击 = 选中 · 双击 = 播放", "クリック = 選択 · ダブルクリック = 再生", "클릭 = 선택 · 더블클릭 = 재생"),
    "Preview": ("预览", "プレビュー", "미리보기"),
    "Click a row to read it here in full. Double-click plays it.": (
        "单击一行在这里阅读全文，双击播放。", "行をクリックするとここに全文を表示、ダブルクリックで再生。", "행을 클릭하면 여기에 전체 표시, 더블클릭하면 재생."),
    "Insights": ("洞察", "インサイト", "인사이트"),
    "Summary": ("摘要", "要約", "요약"),
    "Analyze": ("分析", "分析", "분석"),
    "Analyze again": ("重新分析", "もう一度分析", "다시 분석"),
    "Copy": ("复制", "コピー", "복사"),
    "Note": ("笔记", "メモ", "메모"),
    # settings
    "Appearance": ("外观", "外観", "모양"),
    "Theme": ("主题", "テーマ", "테마"),
    "System": ("跟随系统", "システム", "시스템"),
    "Light": ("浅色", "ライト", "라이트"),
    "Dark": ("深色", "ダーク", "다크"),
    "Language": ("语言", "言語", "언어"),
    "Text size": ("文字大小", "文字サイズ", "글자 크기"),
    "Time axis": ("时间轴", "時間軸", "시간 축"),
    "Clock": ("时钟", "時計", "시계"),
    "From start": ("从开头", "開始から", "시작부터"),
    "Reduce motion": ("减少动态效果", "動きを減らす", "움직임 줄이기"),
    "Playback": ("播放", "再生", "재생"),
    "Summaries and translation": ("摘要和翻译", "要約と翻訳", "요약 및 번역"),
    "Analysis": ("分析", "分析", "분석"),
    "Library": ("资料库", "ライブラリ", "라이브러리"),
    "Search settings (Ctrl+P)": ("搜索设置（Ctrl+P）", "設定を検索（Ctrl+P）", "설정 검색 (Ctrl+P)"),
    "Changes are saved as you make them.": ("更改会立即保存。", "変更はすぐに保存されます。", "변경 사항은 바로 저장됩니다."),
    "Dark or light; applies at once": ("深色或浅色；立即生效", "ダークまたはライト。すぐに反映", "다크 또는 라이트, 즉시 적용"),
    "Everything in the window; Ctrl+ Ctrl– Ctrl+0 too": ("整个窗口；也可用 Ctrl+ Ctrl– Ctrl+0", "ウィンドウ全体。Ctrl+ Ctrl– Ctrl+0 でも可", "창 전체, Ctrl+ Ctrl– Ctrl+0 도 가능"),
    "Interface language; text from recordings is never changed": ("界面语言；录音中的文字不会改变", "画面の言語。録音の文字は変わりません", "화면 언어, 녹음의 글자는 바뀌지 않음"),
    "Pitch stays natural at every speed": ("任何速度下音调都自然", "どの速度でも音程は自然", "어떤 속도에서도 음높이가 자연스러움"),
    "Jump over quiet gaps longer than 3 s while playing": ("播放时跳过超过 3 秒的安静段", "再生中、3 秒以上の無音を飛ばす", "재생 중 3초 넘는 무음을 건너뜀"),
    "Test connection": ("测试连接", "接続テスト", "연결 테스트"),
    "Done": ("完成", "完了", "완료"),
    "Cancel": ("取消", "キャンセル", "취소"),
    "Save": ("保存", "保存", "저장"),
    "Delete": ("删除", "削除", "삭제"),
    # tasks
    "Waiting": ("等待中", "待機中", "대기 중"),
    "Running": ("进行中", "実行中", "실행 중"),
    "Paused": ("已暂停", "一時停止", "일시 중지됨"),
    "Failed": ("失败", "失敗", "실패"),
    "Canceled": ("已取消", "キャンセル済み", "취소됨"),
    "Stopped": ("已停止", "停止済み", "중지됨"),
    "Resume": ("继续", "再開", "재개"),
    "Stop": ("停止", "停止", "중지"),
    "Retry": ("重试", "再試行", "다시 시도"),
    "Remove": ("移除", "削除", "제거"),
    "Pause all": ("全部暂停", "すべて一時停止", "모두 일시 중지"),
    "Cancel all": ("全部取消", "すべてキャンセル", "모두 취소"),
    "Clear done": ("清除已完成", "完了分を消去", "완료 항목 지우기"),
    "No tasks. Long jobs like transcription show here.": ("没有任务。转写等长时间工作会显示在这里。", "タスクはありません。文字起こしなど長い処理がここに表示されます。", "작업 없음. 전사 같은 긴 작업이 여기에 표시됩니다."),
    "{done} of {total} · {pct}%": ("{done}/{total} · {pct}%", "{done}/{total} · {pct}%", "{done}/{total} · {pct}%"),
    "Open log folder": ("打开日志文件夹", "ログフォルダを開く", "로그 폴더 열기"),
    "Error": ("错误", "エラー", "오류"),
    "Warning": ("警告", "警告", "경고"),
    "Info": ("信息", "情報", "정보"),
    # shell, commands, tasks, help (polish-app)
    "Search and commands": ("搜索和命令", "検索とコマンド", "검색 및 명령"),
    "Keyboard shortcuts": ("键盘快捷键", "キーボードショートカット", "키보드 단축키"),
    "Switch theme": ("切换主题", "テーマを切り替え", "테마 전환"),
    "Switch language": ("切换语言", "言語を切り替え", "언어 전환"),
    "Show or hide the sidebar": ("显示或隐藏侧栏", "サイドバーの表示切替", "사이드바 보이기/숨기기"),
    "Larger text": ("放大文字", "文字を大きく", "글자 크게"),
    "Smaller text": ("缩小文字", "文字を小さく", "글자 작게"),
    "Normal text size": ("正常文字大小", "標準の文字サイズ", "기본 글자 크기"),
    "Quit": ("退出", "終了", "종료"),
    "Show conversations": ("显示对话", "会話を表示", "대화 보기"),
    "Show people": ("显示人物", "人物を表示", "사람 보기"),
    "Show recordings": ("显示录音", "録音を表示", "녹음 보기"),
    "Show moments": ("显示片段", "モーメントを表示", "순간 보기"),
    "Manage tags": ("管理标签", "タグを管理", "태그 관리"),
    "Find in this conversation": ("在本对话中查找", "この会話内を検索", "이 대화에서 찾기"),
    "Go to a time": ("跳到某个时间", "時刻へ移動", "시간으로 이동"),
    "Play / pause": ("播放 / 暂停", "再生 / 一時停止", "재생 / 일시 중지"),
    "Next speech": ("下一段说话", "次の発話", "다음 발화"),
    "Previous speech": ("上一段说话", "前の発話", "이전 발화"),
    "Add a note here": ("在此添加笔记", "ここにメモを追加", "여기에 메모 추가"),
    "Repeat A–B on or off": ("开关 A–B 重复", "A–B リピートの切替", "A–B 반복 켜기/끄기"),
    "Back / forward 5 s (Shift 1 s, Alt 30 s)": ("后退 / 前进 5 秒（Shift 1 秒，Alt 30 秒）", "5 秒戻る / 進む（Shift 1 秒、Alt 30 秒）", "5초 뒤로 / 앞으로 (Shift 1초, Alt 30초)"),
    "Zoom the timeline": ("缩放时间轴", "タイムラインを拡大縮小", "타임라인 확대/축소"),
    "Open the selected row": ("打开选中的行", "選択した行を開く", "선택한 행 열기"),
    "Clear A–B; close a dialog": ("清除 A–B；关闭对话框", "A–B を消去、ダイアログを閉じる", "A–B 지우기, 대화 상자 닫기"),
    "Resume all": ("全部继续", "すべて再開", "모두 재개"),
    "Transcribe this conversation": ("转写这段对话", "この会話を文字起こし", "이 대화 전사"),
    "Translate…": ("翻译…", "翻訳…", "번역…"),
    "General": ("通用", "一般", "일반"),
    "Navigation": ("导航", "ナビゲーション", "탐색"),
    "View": ("视图", "表示", "보기"),
    "Conversation": ("对话", "会話", "대화"),
    "Settings ": ("设置", "設定", "설정"),
    "Help ": ("帮助", "ヘルプ", "도움말"),
    "Transcript ": ("转写", "文字起こし", "대본"),
    "Search help": ("搜索帮助", "ヘルプを検索", "도움말 검색"),
    "Search settings": ("搜索设置", "設定を検索", "설정 검색"),
    "Where you see it": ("在哪里看到", "表示される場所", "보이는 곳"),
    "Related": ("相关", "関連", "관련"),
    "Output": ("输出", "出力", "출력"),
    "Done in {s}": ("用时 {s}", "{s} で完了", "{s} 만에 완료"),
    "left": ("剩余", "残り", "남음"),
    "Transcribing…": ("正在转写…", "文字起こし中…", "전사 중…"),
    "Already in the task queue": ("已在任务队列中", "すでにタスクキューにあります", "이미 작업 대기열에 있음"),
    "Loading models (the first run takes 1-2 minutes)…": ("正在加载模型（首次约 1-2 分钟）…", "モデルを読み込み中（初回は 1〜2 分）…", "모델 불러오는 중 (처음엔 1-2분)…"),
    "Speech to text  ·  part {d} of {t}": ("语音转文字  ·  第 {d}/{t} 部分", "音声認識  ·  {d}/{t}", "음성 인식  ·  {d}/{t} 부분"),
    "Word timings": ("词级时间", "単語の時刻", "단어 시간"),
    "Who spoke when": ("谁在何时说话", "誰がいつ話したか", "누가 언제 말했는지"),
    "Summarising  ·  part {d} of {t}": ("总结中  ·  第 {d}/{t} 部分", "要約中  ·  {d}/{t}", "요약 중  ·  {d}/{t} 부분"),
    "Translating  ·  {d} of {t} rows": ("翻译中  ·  {d}/{t} 行", "翻訳中  ·  {d}/{t} 行", "번역 중  ·  {d}/{t} 행"),
    "Preparing": ("准备中", "準備中", "준비 중"),
    "Pick a conversation on the left, or plug in the recorder.": ("在左侧选择一段对话，或插入录音笔。", "左の会話を選ぶか、レコーダーを接続してください。", "왼쪽에서 대화를 고르거나 녹음기를 연결하세요."),
    "Pauses transcription between conversations; finished ones are kept": ("在对话之间暂停转写；已完成的保留", "会話の区切りで文字起こしを一時停止。完了分は残ります", "대화 사이에서 전사를 일시 중지, 완료된 것은 유지"),
    "Move up": ("上移", "上へ", "위로"),
    "Move down": ("下移", "下へ", "아래로"),
    "Remove from the list": ("从列表移除", "リストから削除", "목록에서 제거"),
    "Nothing to show.": ("没有内容。", "表示するものはありません。", "표시할 것 없음."),
    "Transcribing new conversations": ("转写新对话", "新しい会話を文字起こし", "새 대화 전사"),
    "System follows your desktop; applies at once (Ctrl+Shift+T)": ("“跟随系统”随桌面设置；立即生效（Ctrl+Shift+T）", "「システム」はデスクトップに合わせます。すぐに反映（Ctrl+Shift+T）", "‘시스템’은 데스크톱을 따름, 즉시 적용 (Ctrl+Shift+T)"),
    "{n} min": ("{n} 分钟", "{n} 分", "{n}분"),
    "{n} notes": ("{n} 条笔记", "メモ {n} 件", "메모 {n}개"),
    "{n} results": ("{n} 条结果", "{n} 件の結果", "결과 {n}개"),
    "{n} files": ("{n} 个文件", "{n} ファイル", "파일 {n}개"),
    "Conversation at {t}": ("{t} 的对话", "{t} の会話", "{t} 대화"),
    "talk {a}–{b} ({n} min)": ("对话 {a}–{b}（{n} 分钟）", "会話 {a}–{b}（{n} 分）", "대화 {a}–{b} ({n}분)"),
    "kept {a}–{b} with 10 min either side": ("保留 {a}–{b}，前后各 10 分钟", "前後 10 分を含め {a}–{b} を保存", "앞뒤 10분 포함 {a}–{b} 보관"),
    "not transcribed yet": ("尚未转写", "まだ文字起こしされていません", "아직 전사 안 됨"),
    "Add a note to this row": ("给这一行加笔记", "この行にメモを追加", "이 행에 메모 추가"),
    "Copy text": ("复制文字", "テキストをコピー", "텍스트 복사"),
    "Play row": ("播放这一行", "この行を再生", "이 행 재생"),
    "Repeat row": ("重复这一行", "この行をリピート", "이 행 반복"),
    "＋ Note": ("＋ 笔记", "＋ メモ", "＋ 메모"),
    "Translate into English": ("翻译成英文", "英語に翻訳", "영어로 번역"),
    "Export A–B ({n} s)": ("导出 A–B（{n} 秒）", "A–B を書き出し（{n} 秒）", "A–B 내보내기 ({n}초)"),
    "Find people, places, phone numbers, times and the rows that matter, and guess how the speakers know each other. Rules work offline; LLM and jev need their servers (Settings).": (
        "找出人物、地点、电话号码、时间和重要的行，并推测说话人之间的关系。规则离线可用；LLM 和 jev 需要各自的服务器（设置）。",
        "人物・場所・電話番号・時刻・重要な行を見つけ、話者どうしの関係を推測します。ルールはオフラインで動作し、LLM と jev はそれぞれのサーバーが必要です（設定）。",
        "사람, 장소, 전화번호, 시간, 중요한 행을 찾고 화자들의 관계를 추측합니다. 규칙은 오프라인으로 동작하고, LLM과 jev는 각 서버가 필요합니다(설정)."),
    "No summary yet. Press Summarize above (needs the LLM server).": ("还没有摘要。按上方的“总结”（需要 LLM 服务器）。", "まだ要約はありません。上の「要約」を押してください（LLM サーバーが必要）。", "아직 요약이 없습니다. 위의 ‘요약’을 누르세요 (LLM 서버 필요)."),
    "No tags yet. Add one here, or with + tag on a talk.": ("还没有标签。在这里添加，或在对话上用“+ 标签”。", "まだタグはありません。ここで追加するか、会話の「+ タグ」で追加します。", "아직 태그가 없습니다. 여기서 추가하거나 대화의 ‘+ 태그’로 추가하세요."),
    "Nothing found. Try the LLM engine for people, places and relationships.": ("没有找到。人物、地点和关系可试试 LLM 引擎。", "見つかりません。人物・場所・関係は LLM エンジンを試してください。", "찾은 것 없음. 사람, 장소, 관계는 LLM 엔진을 써 보세요."),
    "Not transcribed yet. Press Transcribe above.": ("尚未转写。按上方的“转写”。", "まだ文字起こしされていません。上の「文字起こし」を押してください。", "아직 전사되지 않았습니다. 위의 ‘전사’를 누르세요."),
    "Original recordings and clips are never changed. Notes, translations, names, moments and summaries are kept separately in the library database.": (
        "原始录音和片段永不改动。笔记、翻译、名字、片段和摘要另存在资料库数据库中。",
        "元の録音とクリップは変更しません。メモ・翻訳・名前・モーメント・要約はライブラリのデータベースに別に保存します。",
        "원본 녹음과 클립은 절대 바뀌지 않습니다. 메모, 번역, 이름, 순간, 요약은 라이브러리 데이터베이스에 따로 저장됩니다."),
    "Your notes": ("你的笔记", "あなたのメモ", "내 메모"),
    "Transcription": ("转写", "文字起こし", "전사"),
    "Rules": ("规则", "ルール", "규칙"),
    "LLM + jev check": ("LLM + jev 核查", "LLM + jev チェック", "LLM + jev 확인"),
    "Test jev": ("测试 jev", "jev をテスト", "jev 테스트"),
    "Original, Cantonese": ("原始，粤语", "オリジナル、広東語", "원본, 광둥어"),
    "Analysing {t}": ("分析 {t}", "{t} を分析", "{t} 분석"),
    "Summarising {t}": ("总结 {t}", "{t} を要約", "{t} 요약"),
    "Transcribing {t}": ("转写 {t}", "{t} を文字起こし", "{t} 전사"),
    "Translating {what} into {to}": ("把{what}翻译成 {to}", "{what}を {to} に翻訳", "{what}을(를) {to}(으)로 번역"),
    "Making the cleaned copy": ("生成降噪副本", "ノイズ除去版を作成", "잡음 제거 사본 만들기"),
    "LLM server not reachable at http://localhost:8888/v1": ("无法连接 LLM 服务器 http://localhost:8888/v1", "LLM サーバー http://localhost:8888/v1 に接続できません", "LLM 서버 http://localhost:8888/v1 에 연결할 수 없음"),
    "Cantonese": ("粤语", "広東語", "광둥어"),
    "Chinese": ("中文", "中国語", "중국어"),
    "English": ("英语", "英語", "영어"),
    "Malay": ("马来语", "マレー語", "말레이어"),
    "New tag, e.g. 家庭 or roof": ("新标签，例如 家庭 或 roof", "新しいタグ（例：家庭、roof）", "새 태그, 예: 家庭 또는 roof"),
    "Search: roof (price OR 屋顶) -friday": ("搜索：屋顶 (价格 OR roof) -星期五", "検索：屋根 (価格 OR roof) -金曜", "검색: 지붕 (가격 OR roof) -금요일"),
    "Important rows ({n})": ("重要的行（{n}）", "重要な行（{n}）", "중요한 행 ({n})"),
    "Use as name": ("用作名字", "名前に使う", "이름으로 사용"),
    "Name {who} “{name}”": ("把 {who} 命名为“{name}”", "{who} を「{name}」と命名", "{who} 이름을 ‘{name}’(으)로"),
    "Delete #{tag} from {n} places?": ("从 {n} 处删除 #{tag}？", "{n} か所から #{tag} を削除しますか？", "{n}곳에서 #{tag} 을(를) 삭제할까요?"),
    "Delete #{tag}": ("删除 #{tag}", "#{tag} を削除", "#{tag} 삭제"),
    "Plug in the recorder: the import dialog opens here. A copied folder can be imported with  jrec import <folder>.": (
        "插入录音笔：导入对话框会在这里打开。复制出来的文件夹可用  jrec import <文件夹>  导入。",
        "レコーダーを接続すると、ここに取り込みダイアログが開きます。コピーしたフォルダは  jrec import <フォルダ>  で取り込めます。",
        "녹음기를 연결하면 여기서 가져오기 대화 상자가 열립니다. 복사한 폴더는  jrec import <폴더>  로 가져올 수 있습니다."),
    "Voices show as Char 1, Char 2… Click a name in the By column of a transcript to say who it is.": (
        "声音显示为 Char 1、Char 2…… 在转写的“说话人”列点击名字即可标明是谁。",
        "声は Char 1、Char 2… と表示されます。文字起こしの「話者」列の名前をクリックして誰かを設定します。",
        "목소리는 Char 1, Char 2… 로 표시됩니다. 대본의 ‘화자’ 열에서 이름을 클릭해 누구인지 정하세요."),
    "Add a note (M or ＋ Note) or mark A–B and press Save as moment.": ("添加笔记（M 或 ＋ 笔记），或标记 A–B 后按“存为片段”。", "メモを追加（M または ＋ メモ）、または A–B を付けて「モーメントとして保存」。", "메모를 추가하거나 (M 또는 ＋ 메모) A–B를 표시하고 ‘순간으로 저장’을 누르세요."),
    "Nothing matches. Hover ? for the search syntax.": ("没有匹配。把鼠标移到 ? 上查看搜索语法。", "一致なし。? にポインタを置くと検索の書き方を表示。", "일치 없음. ? 에 마우스를 올리면 검색 문법이 보입니다."),
    "Delete note": ("删除笔记", "メモを削除", "메모 삭제"),
    "Delete this moment": ("删除这个片段", "このモーメントを削除", "이 순간 삭제"),
    "Add to the recording": ("加到录音上", "録音に追加", "녹음에 추가"),
    "Play from here": ("从这里播放", "ここから再生", "여기서 재생"),
    "Add note here…": ("在这里加笔记…", "ここにメモを追加…", "여기에 메모 추가…"),
    "Edit this note…": ("编辑这条笔记…", "このメモを編集…", "이 메모 편집…"),
    "Set A here": ("在这里设 A", "ここに A を設定", "여기에 A 설정"),
    "Set B here": ("在这里设 B", "ここに B を設定", "여기에 B 설정"),
    "Clear A–B": ("清除 A–B", "A–B を消去", "A–B 지우기"),
    "Clear": ("清除", "消去", "지우기"),
    "Hide": ("隐藏", "隠す", "숨기기"),
    "Import": ("导入", "取り込む", "가져오기"),
    "Find in this conversation (Ctrl+F)": ("在本对话中查找（Ctrl+F）", "この会話内を検索（Ctrl+F）", "이 대화에서 찾기 (Ctrl+F)"),
    "Go to 14:15:30, +30, @5:00": ("跳到 14:15:30、+30、@5:00", "移動 14:15:30・+30・@5:00", "이동 14:15:30, +30, @5:00"),
    "Theme: {name}": ("主题：{name}", "テーマ：{name}", "테마: {name}"),
    "Language: {name}": ("语言：{name}", "言語：{name}", "언어: {name}"),
    "About jev-recorder": ("关于 jev-recorder", "jev-recorder について", "jev-recorder 정보"),
    "Open config folder": ("打开配置文件夹", "設定フォルダを開く", "설정 폴더 열기"),
    "Open library folder": ("打开资料库文件夹", "ライブラリフォルダを開く", "라이브러리 폴더 열기"),
    "Folders": ("文件夹", "フォルダ", "폴더"),
    "Advanced": ("高级", "詳細", "고급"),
    "Press Ctrl+P to find anything": ("按 Ctrl+P 查找任何内容", "Ctrl+P で何でも検索", "Ctrl+P 로 무엇이든 찾기"),
    "Got it": ("知道了", "了解", "확인"),
    "LLM server online": ("LLM 服务器在线", "LLM サーバー接続中", "LLM 서버 연결됨"),
    "LLM server offline": ("LLM 服务器离线", "LLM サーバー未接続", "LLM 서버 꺼짐"),
    "Cooling down": ("降温中", "冷却中", "식히는 중"),
    "Waiting for GPU": ("等待 GPU", "GPU 待ち", "GPU 대기 중"),
    "Paused by you": ("由你暂停", "あなたが一時停止", "직접 일시 중지함"),
    "Interrupted": ("被中断", "中断されました", "중단됨"),
    "Cancel “{name}”? {done} of {total} are done; they are kept.": ("取消“{name}”？已完成 {done}/{total}，会保留。", "「{name}」をキャンセルしますか？ {done}/{total} 件は完了済みで、残ります。", "‘{name}’을(를) 취소할까요? {done}/{total} 완료, 완료분은 유지됩니다."),
    "Cancel task": ("取消任务", "タスクをキャンセル", "작업 취소"),
    "Keep running": ("继续运行", "続ける", "계속 실행"),
    "Minimize ": ("最小化", "最小化", "최소화"),
    "Screen readers cannot read this app (Dear ImGui has no accessibility tree). Everything works from the keyboard.": (
        "屏幕阅读器无法读取本应用（Dear ImGui 没有无障碍树）。所有功能都可用键盘操作。",
        "スクリーンリーダーはこのアプリを読み上げられません（Dear ImGui にアクセシビリティツリーがありません）。すべてキーボードで操作できます。",
        "화면 낭독기는 이 앱을 읽을 수 없습니다 (Dear ImGui 에 접근성 트리가 없음). 모든 기능은 키보드로 쓸 수 있습니다."),
    "{n} rows": ("{n} 行", "{n} 行", "{n}행"),
    "Move the timeline at once instead of gliding; dialogs still fade": ("时间轴直接跳转，不再滑动；对话框仍会淡入", "タイムラインを滑らかに動かさず即座に移動。ダイアログのフェードは残ります", "타임라인을 미끄러지지 않고 바로 이동, 대화 상자는 계속 페이드"),
    "Label the timeline with the clock, or time since the clip starts": ("时间轴用时钟时间，或从片段开始计时", "タイムラインの目盛りを時刻、またはクリップ開始からの時間で表示", "타임라인에 시계 시간 또는 클립 시작부터의 시간 표시"),
    "Clearer is a live noise filter; Cleaned plays the DeepFilterNet copy": ("“更清晰”是实时降噪；“降噪版”播放 DeepFilterNet 副本", "「クリア」は再生中のノイズフィルター、「ノイズ除去」は DeepFilterNet のコピーを再生", "‘더 선명하게’는 실시간 잡음 필터, ‘잡음 제거’는 DeepFilterNet 사본 재생"),
    "Server": ("服务器", "サーバー", "서버"),
    "Any OpenAI-compatible endpoint": ("任何兼容 OpenAI 的接口", "OpenAI 互換のエンドポイント", "OpenAI 호환 엔드포인트"),
    "Model": ("模型", "モデル", "모델"),
    "Name the server expects": ("服务器使用的模型名", "サーバーが期待するモデル名", "서버가 기대하는 모델 이름"),
    "API key variable": ("API 密钥变量", "API キーの環境変数", "API 키 변수"),
    "Read the key from this environment variable": ("从这个环境变量读取密钥", "この環境変数からキーを読みます", "이 환경 변수에서 키를 읽음"),
    "Chunk size": ("分块大小", "チャンクサイズ", "청크 크기"),
    "Long transcripts are summarised in parts this long (characters)": ("长转写按这个长度（字符）分段总结", "長い文字起こしはこの長さ（文字数）ごとに要約", "긴 대본은 이 길이(문자)씩 나눠 요약"),
    "Overlap": ("重叠", "重なり", "겹침"),
    "Each part repeats the end of the previous one, for context": ("每段重复上一段的结尾，保留上下文", "各部分は前の部分の終わりを繰り返し、文脈を保ちます", "각 부분은 앞 부분의 끝을 반복해 문맥 유지"),
    "Translate into": ("翻译成", "翻訳先", "번역 대상"),
    "Target language for the translate buttons": ("翻译按钮的目标语言", "翻訳ボタンの翻訳先言語", "번역 버튼의 대상 언어"),
    "Connection": ("连接", "接続", "연결"),
    "Check that the server answers": ("检查服务器是否响应", "サーバーが応答するか確認", "서버가 응답하는지 확인"),
    "Speech model": ("语音模型", "音声モデル", "음성 모델"),
    "Used by the next Transcribe; files already done keep their text": ("用于下次转写；已转写的文件保留原文字", "次の文字起こしで使用。完了済みのファイルはそのまま", "다음 전사에 사용, 이미 끝난 파일은 그대로"),
    "Cohere language": ("Cohere 语言", "Cohere の言語", "Cohere 언어"),
    "Engine": ("引擎", "エンジン", "엔진"),
    "Rules work offline; LLM and jev need their servers": ("规则离线可用；LLM 和 jev 需要各自的服务器", "ルールはオフラインで動作。LLM と jev はサーバーが必要", "규칙은 오프라인 동작, LLM과 jev는 서버 필요"),
    "jev server": ("jev 服务器", "jev サーバー", "jev 서버"),
    "Julia-1 /v1/systemone, for relationship scores and checking claims": ("Julia-1 /v1/systemone，用于关系打分和核查说法", "Julia-1 /v1/systemone。関係の採点と主張の確認に使用", "Julia-1 /v1/systemone, 관계 점수와 주장 확인용"),
    "jev model": ("jev 模型", "jev モデル", "jev 모델"),
    "Model name the jev server expects": ("jev 服务器使用的模型名", "jev サーバーが期待するモデル名", "jev 서버가 기대하는 모델 이름"),
    "jev connection": ("jev 连接", "jev 接続", "jev 연결"),
    "Check that jev answers": ("检查 jev 是否响应", "jev が応答するか確認", "jev가 응답하는지 확인"),
    "Folder": ("文件夹", "フォルダ", "폴더"),
    "Where recordings, clips and the database live": ("录音、片段和数据库所在位置", "録音・クリップ・データベースの場所", "녹음, 클립, 데이터베이스 위치"),
    "Evidence": ("证据", "証拠", "증거"),
    "What is never changed": ("永不改动的内容", "決して変更しないもの", "절대 바뀌지 않는 것"),
    "Accessibility": ("无障碍", "アクセシビリティ", "접근성"),
    "Keyboard focus": ("键盘焦点", "キーボードフォーカス", "키보드 포커스"),
    "Tab and the arrow keys move between controls; Esc returns the keys to the player": ("Tab 和方向键在控件间移动；按 Esc 把按键交回播放器", "Tab と矢印キーでコントロール間を移動。Esc でキーをプレーヤーに戻します", "Tab과 화살표 키로 컨트롤 사이 이동, Esc로 키를 플레이어에 돌려줌"),
    "Screen readers": ("屏幕阅读器", "スクリーンリーダー", "화면 낭독기"),
    "Config, logs and the library, in your file manager": ("在文件管理器中打开配置、日志和资料库", "設定・ログ・ライブラリをファイルマネージャーで開く", "설정, 로그, 라이브러리를 파일 관리자에서 열기"),
    "System follows your desktop; applies at once": ("“跟随系统”随桌面设置；立即生效", "「システム」はデスクトップに合わせます。すぐに反映", "‘시스템’은 데스크톱을 따름, 즉시 적용"),
    "Fit talk": ("适配对话", "会話に合わせる", "대화에 맞춤"),
    "Whole": ("全部", "全体", "전체"),
    "Test connection ": ("测试连接", "接続テスト", "연결 테스트"),
    "+{n} more": ("另外 {n} 个", "ほか {n} 件", "{n}개 더"),
    "Start command": ("启动命令", "起動コマンド", "시작 명령"),
    "Starts the server when a task needs it (cold boot); empty = start it yourself": ("有任务需要时启动服务器（冷启动）；留空 = 自己启动", "タスクが必要なときにサーバーを起動（コールドブート）。空欄なら自分で起動", "작업에 필요할 때 서버 시작 (콜드 부트), 비우면 직접 시작"),
    "Stop command": ("停止命令", "停止コマンド", "중지 명령"),
    "Frees its memory when it is idle and before speech recognition": ("空闲时和语音识别前释放其内存", "アイドル時と音声認識の前にメモリを解放", "유휴 시와 음성 인식 전에 메모리 해제"),
    "Stop when idle": ("空闲时停止", "アイドル時に停止", "유휴 시 중지"),
    "After the last summary or translation": ("在最后一次总结或翻译之后", "最後の要約や翻訳のあと", "마지막 요약이나 번역 후"),
    "Right away": ("立即", "すぐに", "바로"),
    "Never": ("从不", "しない", "안 함"),
    "Memory needed": ("所需内存", "必要なメモリ", "필요한 메모리"),
    "GiB; the app checks free memory before a start": ("GiB；启动前检查可用内存", "GiB。起動前に空きメモリを確認", "GiB, 시작 전에 여유 메모리 확인"),
    "LLM server off (starts when needed)": ("LLM 服务器已关闭（需要时启动）", "LLM サーバー停止中（必要時に起動）", "LLM 서버 꺼짐 (필요할 때 시작)"),
    "Starting LLM server": ("正在启动 LLM 服务器", "LLM サーバーを起動中", "LLM 서버 시작 중"),
    "Stopping LLM server": ("正在停止 LLM 服务器", "LLM サーバーを停止中", "LLM 서버 중지 중"),
    "Show subtitles": ("显示字幕", "字幕を表示", "자막 표시"),
    "Pick a conversation": ("选择对话", "会話を選ぶ", "대화 선택"),
}
TABLE = {code: {en: row[k] for en, row in _ROWS.items()} for k, code in enumerate(["zh-CN", "ja", "ko"])}
