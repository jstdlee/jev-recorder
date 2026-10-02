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
