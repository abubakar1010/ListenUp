"""What makes an upload usable, and its waveform peaks (#36; NFR-SEC-3, System Design 6.1)."""

import json
from array import array
from pathlib import Path

import pytest

from listenup.modules.content.domain.media import (
    FAILURE_MESSAGES,
    PEAKS_PER_SECOND,
    PEAKS_SAMPLE_RATE,
    PeakMeter,
    Probe,
    check_probe,
    failure_message,
    parse_probe,
    peaks_json,
    peaks_key,
    playback_key,
)
from listenup.modules.content.ffmpeg import convert_args


def ffprobe_output(
    format_name: str, streams: list[dict[str, object]], duration: str = "35.0"
) -> str:
    return json.dumps(
        {"format": {"format_name": format_name, "duration": duration}, "streams": streams}
    )


AUDIO = {"codec_type": "audio", "codec_name": "mp3", "duration": "35.04"}
VIDEO = {"codec_type": "video", "codec_name": "h264", "disposition": {"attached_pic": 0}}
COVER_ART = {"codec_type": "video", "codec_name": "mjpeg", "disposition": {"attached_pic": 1}}


def test_a_probe_reads_formats_streams_and_the_sound_tracks_length() -> None:
    probe = parse_probe(ffprobe_output("mov,mp4,m4a,3gp,3g2,mj2", [VIDEO, AUDIO], "36.5"))
    assert probe == Probe(frozenset({"mov", "mp4", "m4a", "3gp", "3g2", "mj2"}), 35_040, True, True)


def test_cover_art_in_an_mp3_is_not_a_video() -> None:
    probe = parse_probe(ffprobe_output("mp3", [AUDIO, COVER_ART]))
    assert probe.has_video is False


def test_the_files_length_is_used_when_the_stream_has_none() -> None:
    probe = parse_probe(ffprobe_output("wav", [{"codec_type": "audio"}], "31.25"))
    assert probe.duration_ms == 31_250


def test_output_that_is_not_ffprobe_json_is_refused() -> None:
    with pytest.raises(ValueError):
        parse_probe("[]")


@pytest.mark.parametrize(
    ("probe", "code"),
    [
        (Probe(frozenset({"mp3"}), 35_000, True, False), None),
        (Probe(frozenset({"matroska", "webm"}), 900_000, True, True), None),
        (Probe(frozenset({"mp3"}), 30_000, True, False), None),  # exactly 30 s
        (Probe(frozenset({"mp3"}), 4 * 3_600_000, True, False), None),  # long: pick a passage
        (Probe(frozenset({"tty"}), 35_000, False, False), "unsupported_media"),
        (Probe(frozenset({"png_pipe"}), None, False, True), "unsupported_media"),
        (Probe(frozenset({"mov", "mp4"}), 35_000, False, True), "no_audio_track"),
        (Probe(frozenset({"mp3"}), 29_999, True, False), "clip_too_short"),
        (Probe(frozenset({"wav"}), None, True, False), "unsupported_media"),
    ],
)
def test_only_accepted_audio_or_video_of_at_least_30_seconds_passes(
    probe: Probe, code: str | None
) -> None:
    problem = check_probe(probe)
    assert (problem.code if problem else None) == code
    if problem:
        assert problem.detail == FAILURE_MESSAGES[code]  # type: ignore[index]


def test_every_failure_has_a_message_and_unknown_codes_fall_back() -> None:
    assert failure_message(None) is None
    assert failure_message("clip_too_short") == FAILURE_MESSAGES["clip_too_short"]
    assert failure_message("something_new") == FAILURE_MESSAGES["processing_failed"]


def samples(*values: int, repeat: int = 1) -> bytes:
    return array("h", list(values) * repeat).tobytes()


def test_peaks_are_the_loudest_sample_of_each_tenth_of_a_second() -> None:
    per_peak = PEAKS_SAMPLE_RATE // PEAKS_PER_SECOND
    meter = PeakMeter()
    meter.feed(samples(0, repeat=per_peak))
    meter.feed(samples(100, -32767, repeat=per_peak // 2))
    meter.feed(samples(16384, repeat=per_peak))
    meter.feed(samples(-3277, repeat=10))  # a short tail

    assert meter.finish() == [0, 100, 50, 10]


def test_peaks_do_not_depend_on_how_the_stream_is_cut() -> None:
    data = b"".join(samples(v, repeat=37) for v in range(-30000, 30000, 997))
    whole = PeakMeter()
    whole.feed(data)
    pieces = PeakMeter()
    for start in range(0, len(data), 333):  # odd sizes split samples in half
        pieces.feed(data[start : start + 333])
    assert pieces.finish() == whole.finish()


def test_the_peaks_file_is_compact_json() -> None:
    peaks = [42] * (PEAKS_PER_SECOND * 60)
    encoded = peaks_json(peaks)
    assert len(encoded) < 2048  # System Design 6.1: about 2 KB a minute
    assert json.loads(encoded) == {"version": 1, "per_second": 10, "scale": 100, "peaks": peaks}


def test_files_live_under_the_learners_prefix() -> None:
    assert playback_key("u1", "m1") == "users/u1/media/m1/playback.mp4"
    assert peaks_key("u1", "m1") == "users/u1/media/m1/peaks.json"


def test_the_playback_file_is_aac_lc_mono_64k_mp4_with_faststart() -> None:
    args = convert_args(Path("in"), Path("out.mp4"), video=False)
    playback = args[: args.index("out.mp4") + 1]
    for flag, value in [("-c:a", "aac"), ("-profile:a", "aac_low"), ("-b:a", "64k"),
                        ("-ac", "1"), ("-movflags", "+faststart"), ("-f", "mp4")]:  # fmt: skip
        assert playback[playback.index(flag) + 1] == value
    assert "-c:v" not in args
    assert "libx264" in convert_args(Path("in"), Path("out.mp4"), video=True)
