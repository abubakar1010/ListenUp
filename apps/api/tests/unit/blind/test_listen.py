"""The heartbeat rules of a Blind listen (#63; System Design 9.2; D13, D18)."""

from datetime import UTC, datetime, timedelta

import pytest

from listenup.modules.blind.domain import (
    Action,
    Beat,
    Interruption,
    Listen,
    PlayerState,
    VoidReason,
    client_void,
    heard_whole_passage,
    judge,
)
from listenup.modules.blind.domain.listen import (
    BUFFERING_BUDGET_MS,
    MEDIA_GRACE_MS,
    resume,
)

T0 = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
START, END = 130_000, 280_000  # passage 02:10 to 04:40
PLAYING = PlayerState.PLAYING


def at(ms: int) -> datetime:
    return T0 + timedelta(milliseconds=ms)


def listen() -> Listen:
    return Listen.start(START, END, T0)


def play(state: Listen, *beats: tuple[int, int]) -> Listen:
    """Send (seconds after T0, position after the passage start) beats that must pass."""
    for when, position in beats:
        verdict = judge(state, Beat(START + position, PLAYING), at(when))
        assert verdict.action is Action.CONTINUE, verdict
        state = verdict.listen
    return state


def test_beats_in_step_with_the_clock_are_accepted() -> None:
    state = play(listen(), (5_000, 5_000), (10_000, 10_000), (15_000, 15_000))

    assert state.last_position_ms == START + 15_000
    assert state.last_heartbeat_at == at(15_000)
    assert not state.complete


def test_a_player_slower_than_the_clock_is_fine() -> None:
    # Loading took 2 s; the position lags the clock, which no rule refuses.
    state = play(listen(), (5_000, 3_000), (10_000, 8_000))

    assert state.last_position_ms == START + 8_000


def test_a_hidden_page_voids_the_attempt() -> None:
    verdict = judge(listen(), Beat(START + 5_000, PLAYING, visible=False), at(5_000))

    assert verdict.action is Action.STOP
    assert verdict.void_reason is VoidReason.LEFT_PAGE


def test_a_jump_backwards_is_a_seek() -> None:
    state = play(listen(), (5_000, 5_000), (10_000, 10_000))

    verdict = judge(state, Beat(START + 6_000, PLAYING), at(15_000))

    assert verdict.void_reason is VoidReason.SEEK


def test_small_rounding_backwards_is_not_a_seek() -> None:
    state = play(listen(), (5_000, 5_000))

    verdict = judge(state, Beat(START + 4_800, PLAYING), at(10_000))

    assert verdict.action is Action.CONTINUE
    assert verdict.listen.last_position_ms == START + 5_000  # never moves back


@pytest.mark.parametrize("position", [START - 5_000, END + 5_000])
def test_a_position_outside_the_passage_is_a_seek(position: int) -> None:
    verdict = judge(listen(), Beat(position, PLAYING), at(400_000))

    assert verdict.void_reason is VoidReason.SEEK


def test_running_ahead_of_the_clock_is_too_fast() -> None:
    verdict = judge(listen(), Beat(START + 7_000, PLAYING), at(5_000))

    assert verdict.void_reason is VoidReason.TOO_FAST


def test_up_to_one_and_a_half_seconds_ahead_is_tolerated() -> None:
    verdict = judge(listen(), Beat(START + 6_500, PLAYING), at(5_000))

    assert verdict.action is Action.CONTINUE


def test_the_tolerance_does_not_add_up_over_many_beats() -> None:
    """Faked beats sent quickly, each 1.4 s ahead, are caught once the total passes 1.5 s."""
    state = listen()
    verdict = None
    for n in range(1, 10):
        verdict = judge(state, Beat(START + n * 1_400, PLAYING), at(n * 10))
        if verdict.voided:
            break
        state = verdict.listen
    assert verdict is not None
    assert verdict.void_reason is VoidReason.TOO_FAST


def test_a_silence_of_more_than_15_seconds_is_a_missed_heartbeat() -> None:
    state = play(listen(), (5_000, 5_000))

    verdict = judge(state, Beat(START + 21_000, PLAYING), at(21_000))

    assert verdict.void_reason is VoidReason.MISSED_HEARTBEAT


def test_a_silence_of_15_seconds_is_still_accepted() -> None:
    state = play(listen(), (5_000, 5_000))

    assert judge(state, Beat(START + 20_000, PLAYING), at(20_000)).action is Action.CONTINUE


def test_buffering_under_20_seconds_in_total_is_allowed() -> None:
    state = listen()
    for n in range(1, 4):  # 3 beats of 5 s waiting for data
        verdict = judge(
            state, Beat(START, PlayerState.BUFFERING, buffering_ms=5_000), at(n * 5_000)
        )
        assert verdict.action is Action.CONTINUE
        state = verdict.listen

    assert state.buffering_ms == 15_000
    assert state.resume_count == 0


def test_buffering_counts_no_more_than_the_time_between_beats() -> None:
    verdict = judge(listen(), Beat(START, PlayerState.BUFFERING, buffering_ms=60_000), at(4_000))

    assert verdict.listen.buffering_ms == 4_000


def test_buffering_over_20_seconds_is_a_stall_that_uses_the_resume() -> None:
    state = play(listen(), (5_000, 5_000))
    for n in range(2, 6):
        verdict = judge(
            state, Beat(START + 5_000, PlayerState.BUFFERING, buffering_ms=5_000), at(n * 5_000)
        )
        assert verdict.action is Action.CONTINUE
        state = verdict.listen

    verdict = judge(
        state, Beat(START + 5_000, PlayerState.BUFFERING, buffering_ms=5_000), at(30_000)
    )

    assert verdict.action is Action.RESUME
    assert verdict.resume_from_ms == START + 2_000
    assert verdict.listen.buffering_ms == 0  # the resumed listen gets a fresh allowance


def test_a_network_stall_resumes_once_from_three_seconds_before_the_stop() -> None:
    """D13, D18: the beats failed for 40 s; the player reports the stop when it is back."""
    state = play(listen(), (5_000, 5_000), (10_000, 10_000))

    verdict = judge(
        state,
        Beat(START + 12_000, PlayerState.INTERRUPTED, interruption=Interruption.NETWORK),
        at(50_000),
    )

    assert verdict.action is Action.RESUME
    assert verdict.resume_from_ms == START + 9_000
    resumed = verdict.listen
    assert resumed.resume_count == 1
    assert resumed.resume_stop_ms == START + 12_000
    assert resumed.last_position_ms == START + 9_000
    assert (resumed.anchor_position_ms, resumed.anchor_at) == (START + 9_000, at(50_000))


def test_the_resume_restarts_at_the_passage_start_in_the_first_three_seconds() -> None:
    verdict = judge(
        listen(),
        Beat(START + 2_000, PlayerState.INTERRUPTED, interruption=Interruption.NETWORK),
        at(2_500),
    )

    assert verdict.resume_from_ms == START


def test_the_backward_step_of_the_resume_is_not_a_seek() -> None:
    state = play(listen(), (5_000, 5_000), (10_000, 10_000))
    resumed = judge(
        state, Beat(START + 10_000, PlayerState.INTERRUPTED), at(12_000)
    ).listen  # resume from START + 7_000

    # Waiting for the audio and the 3 s count, then playing from the resume point.
    state = judge(resumed, Beat(START + 7_000, PlayerState.RESUMING), at(14_000)).listen
    verdict = judge(state, Beat(START + 9_000, PLAYING), at(17_000))

    assert verdict.action is Action.CONTINUE
    assert verdict.listen.last_position_ms == START + 9_000


def test_carrying_on_before_the_count_ends_is_not_too_fast() -> None:
    """ "Carry on now" (final UI D07) skips the count; the clock restarts at the grant."""
    state = play(listen(), (5_000, 5_000))
    resumed = judge(state, Beat(START + 6_000, PlayerState.INTERRUPTED), at(6_000)).listen

    verdict = judge(resumed, Beat(START + 3_000 + 5_000, PLAYING), at(11_000))

    assert verdict.action is Action.CONTINUE


def test_a_second_interruption_voids_the_attempt() -> None:
    state = play(listen(), (5_000, 5_000))
    resumed = judge(state, Beat(START + 6_000, PlayerState.INTERRUPTED), at(6_000)).listen
    state = judge(resumed, Beat(START + 8_000, PLAYING), at(11_000)).listen

    verdict = judge(state, Beat(START + 9_000, PlayerState.INTERRUPTED), at(13_000))

    assert verdict.action is Action.STOP
    assert verdict.void_reason is VoidReason.INTERRUPTED


def test_a_stall_after_the_resume_voids_the_attempt() -> None:
    resumed = resume(listen(), START + 6_000, at(6_000)).listen
    state = resumed
    verdict = None
    for n in range(1, 6):  # 25 s of waiting for data after the resume
        verdict = judge(
            state,
            Beat(START + 3_000, PlayerState.BUFFERING, buffering_ms=5_000),
            at(6_000 + n * 5_000),
        )
        if verdict.voided:
            break
        assert verdict.action is Action.CONTINUE  # up to 20 s is still allowed
        state = verdict.listen

    assert verdict is not None
    assert verdict.void_reason is VoidReason.INTERRUPTED


def test_a_device_pause_under_5_seconds_resumes() -> None:
    state = play(listen(), (5_000, 5_000))

    verdict = judge(
        state,
        Beat(
            START + 7_000,
            PlayerState.INTERRUPTED,
            interruption=Interruption.DEVICE,
            interruption_ms=2_000,
        ),
        at(9_000),
    )

    assert verdict.action is Action.RESUME
    assert verdict.resume_from_ms == START + 4_000


def test_a_device_pause_of_5_seconds_or_more_voids() -> None:
    state = play(listen(), (5_000, 5_000))

    verdict = judge(
        state,
        Beat(
            START + 7_000,
            PlayerState.INTERRUPTED,
            interruption=Interruption.DEVICE,
            interruption_ms=5_000,
        ),
        at(12_000),
    )

    assert verdict.void_reason is VoidReason.INTERRUPTED


def test_an_interruption_cannot_hide_a_jump_ahead() -> None:
    verdict = judge(listen(), Beat(START + 60_000, PlayerState.INTERRUPTED), at(10_000))

    assert verdict.void_reason is VoidReason.TOO_FAST


def test_resuming_without_a_granted_resume_voids() -> None:
    verdict = judge(listen(), Beat(START, PlayerState.RESUMING), at(5_000))

    assert verdict.void_reason is VoidReason.INTERRUPTED


def test_waiting_too_long_after_a_resume_is_a_second_interruption() -> None:
    state = resume(listen(), START + 6_000, at(6_000)).listen
    verdict = None
    for n in range(1, 6):
        verdict = judge(
            state,
            Beat(START + 3_000, PlayerState.RESUMING, buffering_ms=5_000),
            at(6_000 + n * 5_000),
        )
        if verdict.voided:
            break
        state = verdict.listen

    assert verdict is not None
    assert verdict.void_reason is VoidReason.INTERRUPTED


def test_reported_waiting_pauses_the_clock() -> None:
    state = listen()
    state = judge(state, Beat(START, PlayerState.BUFFERING, buffering_ms=4_000), at(4_000)).listen

    assert state.anchor_at == at(4_000)
    # 10 s after the start, 6 s of it playing: in step with the paused clock.
    assert judge(state, Beat(START + 6_000, PLAYING), at(10_000)).action is Action.CONTINUE


def test_claiming_to_wait_while_moving_on_is_too_fast() -> None:
    verdict = judge(
        listen(), Beat(START + 5_000, PlayerState.BUFFERING, buffering_ms=5_000), at(5_000)
    )

    assert verdict.void_reason is VoidReason.TOO_FAST


def test_a_pause_the_player_did_not_report_voids() -> None:
    """Beats that keep coming while the position stands still: an unreported pause."""
    state = play(listen(), (5_000, 5_000), (10_000, 5_000))

    verdict = judge(state, Beat(START + 5_000, PLAYING), at(15_000))

    assert verdict.void_reason is VoidReason.INTERRUPTED


def test_the_listen_is_complete_at_the_end_of_the_passage() -> None:
    state = listen()
    for second in range(5, 151, 5):
        state = play(state, (second * 1_000, second * 1_000))

    assert state.complete
    assert heard_whole_passage(state, at(150_000))
    # Late beats after the end change nothing.
    assert judge(state, Beat(END, PlayerState.ENDED), at(151_000)).listen == state


def test_the_gist_needs_the_server_time_of_the_whole_passage() -> None:
    # A forged record at the end without the time: the gist check refuses it.
    forged = Listen.start(START, END, T0).__class__(
        passage_start_ms=START,
        passage_end_ms=END,
        last_position_ms=END,
        last_heartbeat_at=at(10_000),
        anchor_position_ms=START,
        anchor_at=T0,
    )

    assert forged.complete
    assert not heard_whole_passage(forged, at(10_000))
    assert heard_whole_passage(forged, at(149_000))


def test_the_gist_is_refused_before_the_end() -> None:
    state = play(listen(), *[(s * 1_000, s * 1_000) for s in range(5, 101, 5)])

    assert not heard_whole_passage(state, at(300_000))


@pytest.mark.parametrize("reason", [VoidReason.LEFT_PAGE, VoidReason.RELOAD, VoidReason.SEEK])
def test_leaving_reloading_or_seeking_voids_during_the_listen(reason: VoidReason) -> None:
    assert client_void(listen(), reason) is reason


def test_leaving_after_the_whole_passage_does_not_void() -> None:
    done = Listen.start(START, END, T0).__class__(
        passage_start_ms=START,
        passage_end_ms=END,
        last_position_ms=END,
        last_heartbeat_at=at(150_000),
        anchor_position_ms=START,
        anchor_at=T0,
    )

    assert client_void(done, VoidReason.LEFT_PAGE) is None


def test_the_browser_cannot_report_server_reasons() -> None:
    with pytest.raises(ValueError):
        client_void(listen(), VoidReason.TOO_FAST)


def test_the_media_deadline_is_the_passage_plus_waiting_and_grace() -> None:
    assert listen().media_deadline() == at(END - START + BUFFERING_BUDGET_MS + MEDIA_GRACE_MS)


def test_a_resume_moves_the_media_deadline() -> None:
    resumed = resume(listen(), START + 100_000, at(120_000)).listen

    rest = END - (START + 97_000)
    assert resumed.media_deadline() == at(120_000 + rest + BUFFERING_BUDGET_MS + MEDIA_GRACE_MS)
