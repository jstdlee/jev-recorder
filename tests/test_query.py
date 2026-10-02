from datetime import datetime
from zoneinfo import ZoneInfo

from jrec.query import fold, match, parse, terms

T = ZoneInfo("Asia/Singapore")
ROW = {"text": "OK, I will fix the roof next Friday, price S$1,200", "translations": ["好，下星期五修屋頂"],
       "notes": ["Contractor promise"], "tags": ["家庭", "Renovation"], "speaker": "Mr Tan", "lang": "English",
       "time": datetime(2025, 10, 3, 14, 12, 30, tzinfo=T)}


def m(q, row=ROW):
    return match(parse(q), row)


def test_and_any_order_and_case():
    assert m("friday ROOF") and m("roof friday") and not m("roof monday")


def test_or_not_parentheses():
    assert m("monday OR friday") and m("monday | friday")
    assert m("roof AND (price OR cost)") and not m("roof AND (cost OR fee)")
    assert m("roof NOT monday") and m("roof -monday") and not m("roof -friday")
    assert m("(roof OR wall) (friday OR monday) -cheap")


def test_phrase_and_regex():
    assert m('"next friday"') and not m('"friday next"')
    assert m(r"/S\$\d,\d{3}/") and not m(r"/\d{5}/")


def test_fields_and_chinese_trad_simplified():
    assert m("note:promise") and not m("note:roof")
    assert m("tag:家庭") and m("tag:renovation") and m("by:tan")
    assert m("屋顶") and m("星期五")              # simplified query finds traditional text
    assert fold("錄音") == fold("录音")
    assert m("lang:english")


def test_time_filters():
    assert m("time:14:00-15:00") and not m("time:15:00-16:00") and m("time:14:12")
    assert m("date:2025-10-03") and m("after:2025-10-01") and not m("before:2025-10-02")
    assert m("roof time:14:00-14:30 -monday")


def test_terms_for_highlight():
    assert terms(parse('roof (price OR "next friday") -cheap')) == ["roof", "price", "next friday"]


def test_library_search_rows_notes_and_tags(tmp_path):
    from types import SimpleNamespace as NS
    from jrec import db, libsearch
    con = db.connect(tmp_path / "j.sqlite")
    db.add_tag(con, "conversation", "c1", "  #家庭 ")
    db.add_tag(con, "source", "abc", "Renovation")
    assert db.tags_for(con, "conversation", "c1") == ["家庭"] and db.all_tags(con) == {"家庭": 1, "Renovation": 1}
    segs = [{"text": "修屋頂要多少錢", "abs_start": "2025-10-03T14:12:30+08:00", "_t0": 10.0, "speaker": "S1", "lang": "Cantonese"},
            {"text": "next Friday", "abs_start": "2025-10-03T14:13:00+08:00", "_t0": 40.0, "speaker": "S2", "lang": "English"}]
    c = NS(segments=segs, notes=[{"t": 41.0, "text": "promise!"}], translations={"English": {0: "How much to fix the roof"}},
           tags=["家庭"], speaker=lambda s, i: {"S1": "Mum", "S2": "Mr Tan"}[s["speaker"]], start=None)
    hits = libsearch.search([c], "tag:家庭 (屋顶 OR roof)")
    assert [(h[1], h[2]) for h in hits] == [(0, "row")]
    assert [h[1] for h in libsearch.search([c], "note:promise by:tan")] == [1]
    assert [h[1] for h in libsearch.search([c], "time:14:13 -monday")] == [1]
    db.remove_tag(con, "conversation", "c1", "家庭")
    assert db.tags_for(con, "conversation", "c1") == []
