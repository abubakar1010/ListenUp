from listenup_spikes.youtube_intake import caption_kind, error_reason, reject_reason


def test_public_video_within_limit_is_accepted() -> None:
    assert reject_reason({"availability": "public", "duration": 600}, 120) is None


def test_rejections() -> None:
    assert reject_reason({"availability": "private", "duration": 60}, 120) == "not public (private)"
    assert reject_reason({"age_limit": 18, "duration": 60}, 120) == "age-restricted"
    assert reject_reason({"live_status": "is_live", "duration": 60}, 120) == "live or upcoming"
    assert reject_reason({"duration": 3 * 3600}, 120) == "longer than 120 min"
    assert reject_reason({}, 120) == "unknown duration"


def test_caption_kind_prefers_creator_captions() -> None:
    assert caption_kind({"subtitles": {"en-GB": []}, "automatic_captions": {"en": []}}) == "creator"
    assert caption_kind({"automatic_captions": {"en": []}}) == "auto-only"
    assert caption_kind({}) == "none"


def test_error_reason_from_downloader_message() -> None:
    assert error_reason("ERROR: Private video. Sign in") == "not public (private)"
    assert error_reason("ERROR: Sign in to confirm your age") == "age-restricted"
