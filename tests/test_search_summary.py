import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from jrec import db, search, summarize

SEGS = [
    {"abs_start": "2025-10-01T09:25:31.000+08:00", "speaker": "S1", "lang": "Chinese", "text": "我们下周三开会讨论预算。"},
    {"abs_start": "2025-10-01T09:25:40.000+08:00", "speaker": "S2", "lang": "English", "text": "OK, I will send the budget sheet by Friday."},
    {"abs_start": "2025-10-01T09:26:02.000+08:00", "speaker": "S1", "lang": "Malay", "text": "Terima kasih, jumpa lagi."},
]


def _folder(tmp_path, segs=SEGS):
    f = tmp_path / "2025-10-01_092531_abcd"
    f.mkdir()
    (f / "transcript.json").write_text(json.dumps({"segments": segs}, ensure_ascii=False))
    return f


def test_search_cjk_substring_short_query_and_english(tmp_path):
    con = db.connect(tmp_path / "j.sqlite")
    search.index_transcript(con, _folder(tmp_path))
    assert [h["speaker"] for h in search.search(con, "讨论预算")] == ["S1"]   # trigram, CJK inside a run
    assert len(search.search(con, "开会")) == 1                             # 2 chars -> LIKE fallback
    assert search.search(con, "budget sheet")[0]["abs_start"].startswith("2025-10-01T09:25:40")
    assert search.search(con, "BUDGET")                                      # case-insensitive
    search.index_transcript(con, tmp_path / "2025-10-01_092531_abcd")         # re-index replaces, no dupes
    assert len(search.search(con, "budget")) == 1


class _Fake(BaseHTTPRequestHandler):
    replies = []
    seen = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Fake.seen.append((self.path, body, self.headers.get("Authorization")))
        r = _Fake.replies
        content = r(body) if callable(r) else r.pop(0)
        data = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def log_message(self, *a):
        pass


def _server():
    srv = HTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_summary_retries_bad_json_strips_think_and_cites_times(tmp_path, monkeypatch):
    good = {"title": "预算会议安排", "summary": "约定下周三开会讨论预算。", "language": "Chinese",
            "key_points": [{"text": "下周三开会", "refs": [0]}],
            "action_items": [{"text": "Send budget sheet", "owner": "S2", "due": "Friday", "refs": [1]}],
            "people": [], "places": []}
    _Fake.replies = ["Sure! Here is the summary.", "<think>reasoning…</think>\n" + json.dumps(good, ensure_ascii=False)]
    _Fake.seen = []
    srv = _server()
    monkeypatch.setenv("TEST_KEY", "sk-test")
    prof = {"base_url": f"http://127.0.0.1:{srv.server_port}/v1", "model": "m", "api_key_env": "TEST_KEY"}
    f = _folder(tmp_path)
    d = summarize.summarize_folder(f, prof)
    srv.shutdown()
    assert len(_Fake.seen) == 2 and _Fake.seen[0][0] == "/v1/chat/completions"
    assert _Fake.seen[0][2] == "Bearer sk-test"
    assert "[0] 09:25:31 S1: 我们下周三开会讨论预算。" in _Fake.seen[0][1]["messages"][1]["content"]
    assert d["key_points"][0]["times"] == ["09:25:31"] and d["action_items"][0]["times"] == ["09:25:40"]
    md = (f / "summary.md").read_text()
    assert md.startswith("# 预算会议安排") and "- [ ] Send budget sheet — S2 (due Friday) (09:25:40)" in md


def test_long_transcript_is_chunked_then_merged(tmp_path, monkeypatch):
    monkeypatch.setattr(summarize, "CHUNK_CHARS", 120)
    segs = [dict(SEGS[1], text=f"Point number {i} about the budget.") for i in range(8)]
    notes = json.dumps({"notes": [{"text": "budget discussed", "refs": [0]}], "people": [], "places": []})
    final = json.dumps({"title": "Budget", "summary": "s", "key_points": [{"text": "k", "refs": [3]}],
                        "action_items": [], "people": [], "places": [], "language": "English"})
    _Fake.replies = lambda body: notes if "one part of a longer" in body["messages"][1]["content"] else final
    _Fake.seen = []
    srv = _server()
    d = summarize.summarize_folder(_folder(tmp_path, segs), {"base_url": f"http://127.0.0.1:{srv.server_port}/v1",
                                                             "model": "m"})
    srv.shutdown()
    n_notes = sum("one part of a longer conversation" in b["messages"][1]["content"] for _, b, _ in _Fake.seen)
    assert n_notes >= 2 and d["title"] == "Budget" and d["key_points"][0]["times"] == ["09:25:40"]
