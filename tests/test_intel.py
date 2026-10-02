"""Intelligence extraction: rules offline; LLM and jev against fake servers."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from jrec import db, intel

SEGS = [
    {"abs_start": "2025-10-01T09:25:31.000+08:00", "speaker": "S1", "lang": "English",
     "text": "Call me at +65 9123 4567 or mail tan@example.com, I can fix the roof next Friday at 3pm."},
    {"abs_start": "2025-10-01T09:25:40.000+08:00", "speaker": "S2", "lang": "English",
     "text": "How much? Is S$1,200 okay? We are at Blk 12 Tampines Street 4."},
    {"abs_start": "2025-10-01T09:25:52.000+08:00", "speaker": "S1", "lang": "Chinese",
     "text": "好的，下星期五下午三点我过来，大概一千二百块。"},
]


def test_rules_find_contacts_money_times_offline():
    r = intel.rules_extract(SEGS)
    texts = {(x["kind"], x["text"]) for k in r for x in r[k]}
    assert ("phone", "+65 9123 4567") in texts and ("email", "tan@example.com") in texts
    assert any(k == "money" and "1,200" in t for k, t in texts)
    assert any(k == "money" and "块" in t for k, t in texts)
    assert ("date", "next Friday") in texts and ("time", "3pm") in texts
    assert any(k == "date" and "星期五" in t for k, t in texts) and any(k == "time" and "三点" in t for k, t in texts)


class _H(BaseHTTPRequestHandler):
    handler = None
    seen = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _H.seen.append((self.path, body))
        data = json.dumps(_H.handler(self.path, body)).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def log_message(self, *a):
        pass


def _serve(handler):
    _H.handler, _H.seen = handler, []
    srv = HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


def _fake(path, body):
    if path.endswith("/chat/completions"):
        out = {"people": [{"name": "Mr Tan", "role": "contractor", "speaker": "S1", "refs": [0]}],
               "places": [{"text": "Blk 12 Tampines Street 4", "refs": [1]}],
               "contacts": [{"text": "+65 9123 4567", "kind": "phone", "refs": [0]}],
               "times": [{"text": "next Friday at 3pm", "meaning": "roof repair visit", "refs": [0, 2]}],
               "important": [{"ref": 2, "why": "agreed price and time"}],
               "speaker_roles": [{"speaker": "S1", "guess": "contractor", "refs": [0]}],
               "relationships": [{"a": "S1", "b": "S2", "relation": "contractor and homeowner", "confidence": 0.8,
                                  "evidence": [0, 1]}]}
        return {"choices": [{"message": {"content": json.dumps(out)}}]}
    # jev: every question gets probabilities; prefer client_vendor / yes
    answers = {}
    for q, spec in body["questions"].items():
        opts = list(spec["criteria"])
        probs = {o: 0.05 for o in opts}
        probs["client_vendor" if "client_vendor" in opts else "yes"] = 0.8
        answers[q] = {"choice": max(probs, key=probs.get), "probabilities": probs}
    return {"answers": answers}


def test_llm_jev_and_check_engines(tmp_path):
    f = tmp_path / "conv"
    f.mkdir()
    (f / "transcript.json").write_text(json.dumps({"segments": SEGS}, ensure_ascii=False), encoding="utf-8")
    con = db.connect(tmp_path / "j.sqlite")
    srv, url = _serve(_fake)
    prof = {"base_url": url + "/v1", "model": "m"}
    jev = {"url": url, "model": "julia-1"}
    d = intel.analyze_folder(f, "llm", prof, jev, con)
    assert d["places"][0]["text"] == "Blk 12 Tampines Street 4" and d["relationships"][0]["a"] == "S1"
    d = intel.analyze_folder(f, "jev", prof, jev, con)
    assert d["relationships"][0]["relation"] == "client_vendor" and d["important"]
    jev_req = [b for p, b in _H.seen if p == "/v1/systemone"][0]
    assert jev_req["model"] == "julia-1" and jev_req["questions"]["rel"]["type"] == "choice"
    d = intel.analyze_folder(f, "check", prof, jev, con)
    srv.shutdown()
    assert all("jev_support" in x for x in d["people"] + d["places"] + d["relationships"] + d["important"])
    assert db.get_insight(con, "conv")["_meta"]["engine"] == "check"
    assert (f / "insights.json").exists()
