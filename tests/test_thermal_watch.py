from jrec import thermal, watch


def test_wait_cool_returns_immediately_when_cool():
    assert thermal.wait_cool(read=lambda: 60.0, log=lambda *a: None) == 0.0


def test_wait_cool_pauses_until_resume_threshold():
    temps = iter([95.0, 92.0, 86.0, 81.0])
    slept = []
    waited = thermal.wait_cool(read=lambda: next(temps), sleep=slept.append, log=lambda *a: None)
    assert waited == 15.0 and len(slept) == 3


def test_no_sensors_means_no_wait():
    assert thermal.wait_cool(read=lambda: None, log=lambda *a: None) == 0.0


def test_new_mounts_only_reports_newly_plugged():
    assert watch.new_mounts({"/media/u/IC RECORDER"}, {"/media/u/IC RECORDER": 1, "/media/u/OTHER": 2}) == ["/media/u/OTHER"]


def test_goto_parsing():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from jrec.timeref import parse
    t0 = datetime(2025, 10, 2, 14, 2, 13, tzinfo=ZoneInfo("Asia/Singapore"))
    dur = 1560.0
    assert parse("14:15:30", t0, 100, dur) == 797.0           # clock time
    assert parse("14:15", t0, 100, dur) == 767.0              # clock (inside the clip)
    assert parse("+30", t0, 100, dur) == 130.0                # from the playhead
    assert parse("-1:00", t0, 100, dur) == 40.0
    assert parse("@5:00", t0, 100, dur) == 300.0              # from the start
    assert parse("2:30", t0, 100, dur) == 150.0               # not a plausible clock time -> mm:ss
    assert parse("90", t0, 100, dur) == 90.0
    assert parse("99:99:99", t0, 100, dur) == dur             # clamped
    assert parse("abc", t0, 100, dur) is None
