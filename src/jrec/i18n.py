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


def T(_s, **kw):
    out = TABLE.get(_current, {}).get(_s, _s) if _current != "en" else _s
    return out.format(**kw) if kw else out


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
    "Show subtitles": ("显示字幕", "字幕を表示", "자막 표시"),
    "Pick a conversation": ("选择对话", "会話を選ぶ", "대화 선택"),
}
TABLE = {code: {en: row[k] for en, row in _ROWS.items()} for k, code in enumerate(["zh-CN", "ja", "ko"])}
