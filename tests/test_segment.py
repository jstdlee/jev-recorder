from jrec.segment import windows


def test_single_conversation_padded_both_sides():
    (w,) = windows([(3600, 3630), (3700, 3760)], total=10800)
    assert (w.start, w.end) == (3000, 4360)
    assert (w.speech_start, w.speech_end, w.speech_sec) == (3600, 3760, 90)


def test_padding_clamped_to_stream_bounds():
    (w,) = windows([(100, 160)], total=400)
    assert (w.start, w.end) == (0, 400)


def test_short_blip_dropped():
    assert windows([(5000, 5005)], total=10800) == []


def test_gap_splits_conversations_and_overlapping_pads_merge():
    # 15 min apart: separate conversations, but the 10 min pads overlap, so they merge
    (w,) = windows([(3600, 3660), (4560, 4620)], total=10800)
    assert (w.start, w.end, w.speech_sec) == (3000, 5220, 120)


def test_far_apart_conversations_stay_separate():
    ws = windows([(1000, 1100), (5000, 5100)], total=10800)
    assert [(w.start, w.end) for w in ws] == [(400, 1700), (4400, 5700)]


def test_short_speech_bursts_join_within_gap():
    regs = [(1000 + i * 60, 1000 + i * 60 + 5) for i in range(5)]  # 5 s every minute
    (w,) = windows(regs, total=10800)
    assert w.speech_sec == 25
