"""Insights panel: people, speaker roles, relationships, places, contacts, times, money, important rows.
Every item has time buttons that jump to the rows it comes from. With the 'check' engine each claim
carries a jev support score (how well its cited rows back it up)."""
from imgui_bundle import imgui

from .. import db
from .. import theme as th
from ..theme import C
from .timeline import speaker_color

ENGINES = ["rules", "llm", "jev", "check"]
ENGINE_LABELS = ["Rules", "LLM", "jev", "LLM + jev check"]
ENGINE_TIPS = ["Offline patterns: phones, emails, money, dates, times. Instant, no server",
               "The LLM reads everything: people, places, roles, relationships, important rows",
               "Julia-1 scores relationships between speakers and how important each row is",
               "LLM extraction, then jev rates how well each claim is supported (lint)"]
REL_LABELS = {"family": "family", "couple": "a couple", "friends": "friends", "colleagues": "colleagues",
              "boss_staff": "boss and staff", "client_vendor": "customer and provider", "official": "official role",
              "strangers": "strangers", "broadcast": "broadcast / lecture"}


def _flow(width):
    """Place the next small item on this line if it fits, else wrap."""
    imgui.same_line(0, 4)
    if imgui.get_content_region_avail().x < width:
        imgui.new_line()


def refs_buttons(app, c, refs, key):
    first = True
    for k, r in enumerate(refs or []):
        if not isinstance(r, int) or not (0 <= r < len(c.segments)):
            continue
        label = f"{c.segments[r]['abs_start'][11:19]}##{key}_{k}"
        if not first:
            _flow(imgui.calc_text_size(label.split("##")[0]).x + 16)
        first = False
        if imgui.small_button(label):
            app.select(c, c.segments[r]["_t0"])
            app.sel_row = (c.name, r)
        th.tip(c.segments[r]["text"][:200])


def support(item):
    """jev support badge at the start of an item's button line."""
    p = item.get("jev_support")
    if p is None:
        return False
    imgui.align_text_to_frame_padding()
    th.small(f"jev {p:.0%}", "ok" if p >= 0.66 else "warn" if p >= 0.4 else "danger")
    th.tip("How well jev thinks the cited lines support this (Julia-1)")
    imgui.same_line(0, 6)
    return True


def actions(app, c, item, refs, key):
    """One line under an item: jev badge, then time buttons (wrapping)."""
    support(item)
    refs_buttons(app, c, refs, key)


def item_line(text, color="text"):
    imgui.push_text_wrap_pos(imgui.get_content_region_avail().x * 0.92 + imgui.get_cursor_pos_x())
    imgui.text_colored(C(color), text)
    imgui.pop_text_wrap_pos()


def speaker_label(c, spk):
    return c.names.get(spk) or c.default_name(spk)


def draw(app, c):
    ins = c.insight
    eng = app.cfg.analysis.get("engine", "rules")
    if th.primary_button("Analyze" if not ins else "Analyze again", disabled=app.queued_for(["analyze", str(c.folder), "--engine", eng]) is not None,
                         why="Already in the task queue"):
        app.start_job(["analyze", str(c.folder), "--engine", eng], f"Analysing {c.speech_start:%H:%M}", [c.name])
    imgui.same_line()
    ch, v = th.seg("engine", eng, ENGINES, ENGINE_LABELS, ENGINE_TIPS)
    if ch:
        app.cfg.save_section("analysis", {"engine": v})
    if not ins:
        imgui.dummy(imgui.ImVec2(0, 4))
        imgui.push_text_wrap_pos(0)
        imgui.text_colored(C("text_dim"), "Find people, places, phone numbers, times and the rows that matter, and "
                                          "guess how the speakers know each other. Rules work offline; LLM and jev "
                                          "need their servers (Settings).")
        imgui.pop_text_wrap_pos()
        return
    meta = ins.get("_meta", {})
    th.small(f"{meta.get('engine', '?')}  ·  {meta.get('created', '')[:16].replace('T', ' ')}"
             + (f"  ·  LLM {meta['llm']}" if meta.get("llm") else "") + (f"  ·  jev {meta['jev']}" if meta.get("jev") else ""))

    people = ins.get("people", [])
    if people:
        th.section("People")
        for j, p in enumerate(people):
            line = p.get("name", "?") + (f" — {p['role']}" if p.get("role") else "")
            if p.get("speaker"):
                line += f"  ·  speaks as {speaker_label(c, p['speaker'])}"
            item_line(line)
            actions(app, c, p, p.get("refs"), f"pe{j}")
            if p.get("speaker") and p.get("name") and c.names.get(p["speaker"]) != p["name"]:
                _flow(200)
                if imgui.small_button(f"Name {c.default_name(p['speaker'])} “{p['name']}”##pn{j}"):
                    db.set_speaker_name(app.con, c.name, p["speaker"], p["name"])
                    c.names = db.speaker_names(app.con, c.name)
                    app._cache = {}

    roles = ins.get("speaker_roles", [])
    if roles:
        th.section("Who the speakers seem to be")
        for j, r in enumerate(roles):
            spk = r.get("speaker")
            idx = sorted({s.get("speaker") for s in c.segments if s.get("speaker")})
            col = imgui.color_convert_u32_to_float4(speaker_color(idx.index(spk) if spk in idx else 0, 1.0))
            imgui.text_colored(col, speaker_label(c, spk))
            imgui.same_line()
            item_line(f"probably {r.get('guess', '?')}")
            actions(app, c, r, r.get("refs"), f"ro{j}")
            if spk and r.get("guess") and not c.names.get(spk):
                _flow(100)
                if imgui.small_button(f"Use as name##ru{j}"):
                    db.set_speaker_name(app.con, c.name, spk, r["guess"].strip().capitalize())
                    c.names = db.speaker_names(app.con, c.name)
                    app._cache = {}

    rels = ins.get("relationships", [])
    jrels = [r for r in rels if r.get("source") == "jev"] + ins.get("jev_relationships", [])
    llm_rels = [r for r in rels if r.get("source") != "jev"]
    if llm_rels or jrels:
        th.section("Relationships (a guess)")
        for j, r in enumerate(llm_rels):
            item_line(f"{speaker_label(c, r.get('a'))} ↔ {speaker_label(c, r.get('b'))}: {r.get('relation', '?')}"
                      + (f"  ({float(r['confidence']):.0%})" if isinstance(r.get("confidence"), (int, float)) else ""))
            actions(app, c, r, r.get("evidence"), f"rl{j}")
        for j, r in enumerate(jrels):
            item_line(f"{speaker_label(c, r.get('a'))} ↔ {speaker_label(c, r.get('b'))}  ·  jev", "text_dim")
            for k, (opt, p) in enumerate(list(r.get("scores", {}).items())[:3]):
                imgui.progress_bar(p, imgui.ImVec2(-1, 0), f"{REL_LABELS.get(opt, opt)}  {p:.0%}")

    def plain(title, items, key, kind_label=False):
        if not items:
            return
        th.section(title)
        for j, it in enumerate(items):
            txt = it.get("text", "?") + (f"  ·  {it['meaning']}" if it.get("meaning") else "") \
                + (f"  ({it['kind']})" if kind_label and it.get("kind") else "")
            item_line(txt)
            actions(app, c, it, it.get("refs"), f"{key}{j}")

    rules = ins.get("rules", {})
    plain("Places", ins.get("places", []), "pl")
    plain("Contacts", _merge(ins.get("contacts", []), rules.get("contacts", [])), "co", True)
    plain("Times and dates", _merge(ins.get("times", []), rules.get("times", [])), "ti")
    plain("Money", rules.get("money", []), "mo")

    imp = ins.get("important", [])
    if imp:
        th.section(f"Important rows ({len(imp)})")
        for j, it in enumerate(sorted(imp, key=lambda x: x.get("ref", 0))):
            r = it.get("ref")
            if not isinstance(r, int) or not (0 <= r < len(c.segments)):
                continue
            s = c.segments[r]
            imgui.push_style_color(imgui.Col_.text, C("match"))
            clicked = imgui.selectable(f"{th.ICON_STAR} {s['abs_start'][11:19]}  {s['text'][:70]}##im{j}", False)[0]
            imgui.pop_style_color()
            th.tip(it.get("why", ""))
            if clicked:
                app.select(c, s["_t0"])
                app.sel_row = (c.name, r)
            if it.get("jev_support") is not None:
                imgui.indent(20)
                support(it)
                imgui.new_line()
                imgui.unindent(20)
    if not any([people, roles, rels, ins.get("places"), ins.get("contacts"), ins.get("times"), imp,
                *rules.values()]):
        th.small("Nothing found. Try the LLM engine for people, places and relationships.")


def _merge(a, b):
    seen, out = set(), []
    for it in list(a) + list(b):
        k = str(it.get("text", "")).strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(it)
    return out


def important_rows(c):
    ins = c.insight or {}
    return {it["ref"]: it.get("why", "") for it in ins.get("important", []) if isinstance(it.get("ref"), int)}
