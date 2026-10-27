"""Pure parts of the B5 load-test runner (#94): percentiles, grouping, CPU, statements."""

import json
import os
import stat

import pytest

from listenup_spikes.b5_load import (
    LOCAL_LABEL,
    Request,
    achieved_rates,
    measured_window,
    parse_args,
    parse_k6_points,
    parse_stats_line,
    percentile,
    private_manifest,
    rank_statements,
    render_markdown,
    summarise_attempts,
    summarise_cpu,
    summarise_requests,
    verdict,
)


def point(metric: str, value: float, **tags: str) -> str:
    data = {"time": "2026-10-25T18:00:00Z", "value": value, "tags": tags}
    return json.dumps({"type": "Point", "metric": metric, "data": data})


def req(kind: str, ms: float, status: int = 200, phase: str = "measure") -> Request:
    return Request(phase=phase, kind=kind, name=f"GET /{kind}", status=status, duration_ms=ms)


def test_a_request_without_a_response_keeps_k6s_error_code() -> None:
    lines = [
        point(
            "http_req_duration",
            0.5,
            kind="heartbeat",
            name="POST heartbeat",
            status="0",
            phase="measure",
            error_code="1220",
        ),
    ]
    requests, _ = parse_k6_points(lines)
    assert requests == [Request("measure", "heartbeat", "POST heartbeat", 0, 0.5, "1220")]
    summary = summarise_requests(requests)
    assert summary["errors_by_endpoint"] == {"POST heartbeat 0 (k6 error 1220)": 1}


# Percentiles: nearest rank over every request, so the method is stated and repeatable.


def test_percentile_is_the_nearest_rank() -> None:
    values = list(range(1, 101))  # 1..100
    assert percentile(values, 0.95) == 95
    assert percentile(values, 0.50) == 50
    assert percentile(values, 1.0) == 100


def test_percentile_rounds_the_rank_up() -> None:
    # 10 values: rank ceil(9.5) = 10, the largest; a floor would give the 9th.
    assert percentile([5, 1, 9, 3, 7, 2, 8, 4, 6, 10], 0.95) == 10


def test_percentile_of_one_value_and_of_none() -> None:
    assert percentile([42.0], 0.95) == 42.0
    assert percentile([], 0.95) is None


def test_percentile_refuses_a_quantile_outside_zero_to_one() -> None:
    with pytest.raises(ValueError):
        percentile([1, 2], 0)
    with pytest.raises(ValueError):
        percentile([1, 2], 1.5)


# k6 output: one JSON point per metric sample; only request durations and Blind stops count.


def test_parse_k6_points_keeps_request_durations_with_their_tags() -> None:
    lines = [
        json.dumps({"type": "Metric", "metric": "http_req_duration", "data": {}}),
        point(
            "http_req_duration",
            12.5,
            kind="read",
            name="GET /sessions",
            status="200",
            phase="measure",
        ),
        point(
            "http_req_waiting",
            11.0,
            kind="read",
            name="GET /sessions",
            status="200",
            phase="measure",
        ),
        point(
            "http_req_duration",
            30.0,
            kind="heartbeat",
            name="POST heartbeat",
            status="0",
            phase="warmup",
        ),
        "",
    ]
    requests, stops = parse_k6_points(lines)
    assert requests == [
        Request("measure", "read", "GET /sessions", 200, 12.5),
        Request("warmup", "heartbeat", "POST heartbeat", 0, 30.0),
    ]
    assert stops == {}


def test_parse_k6_points_counts_blind_stops_in_the_measured_window_by_reason() -> None:
    lines = [
        point("blind_stops", 1, reason="missed_heartbeat", phase="measure"),
        point("blind_stops", 1, reason="missed_heartbeat", phase="measure"),
        point("blind_stops", 1, reason="too_fast", phase="warmup"),
    ]
    _, stops = parse_k6_points(lines)
    assert stops == {"missed_heartbeat": 2}


# Grouping: reads and writes against their targets; heartbeats are writes and also shown alone.


def test_summary_uses_only_the_measured_window() -> None:
    summary = summarise_requests([req("read", 10), req("read", 999, phase="warmup")])
    assert summary["read"]["count"] == 1
    assert summary["read"]["p95_ms"] == 10


def test_heartbeats_count_as_writes_and_have_their_own_group() -> None:
    summary = summarise_requests([req("write", 100), req("heartbeat", 20), req("read", 5)])
    assert summary["write"]["count"] == 2
    assert summary["heartbeat"]["count"] == 1
    assert summary["read"]["count"] == 1
    assert summary["all"]["count"] == 3


def test_failed_requests_are_errors_and_stay_in_the_latency() -> None:
    summary = summarise_requests(
        [req("read", 10), req("read", 20), req("read", 5000, status=0), req("read", 30, 500)]
    )
    read = summary["read"]
    assert read["errors"] == 2
    assert read["error_rate"] == 0.5
    assert read["max_ms"] == 5000  # the timed-out request is not dropped
    assert read["by_status"] == {"200": 2, "0": 1, "500": 1}


def test_a_refusal_is_an_error_but_a_redirect_is_not() -> None:
    summary = summarise_requests([req("read", 1, 302), req("write", 1, 409), req("write", 1, 201)])
    assert summary["read"]["errors"] == 0
    assert summary["write"]["errors"] == 1


def test_errors_are_listed_by_endpoint_and_status() -> None:
    summary = summarise_requests(
        [
            Request("measure", "write", "PUT draft", 409, 3),
            Request("measure", "write", "PUT draft", 409, 4),
        ]
    )
    assert summary["errors_by_endpoint"] == {"PUT draft 409": 2}


def test_a_group_without_requests_has_no_percentile() -> None:
    summary = summarise_requests([req("read", 10)])
    assert summary["heartbeat"] == {
        "count": 0,
        "p50_ms": None,
        "p95_ms": None,
        "p99_ms": None,
        "max_ms": None,
        "p50_answered_ms": None,
        "p95_answered_ms": None,
        "errors": 0,
        "error_rate": 0.0,
        "by_status": {},
    }


# CPU from `docker stats`: percent of one core per container, reported as a share of the host.


def test_parse_stats_line_reads_name_and_cpu_and_ignores_terminal_codes() -> None:
    line = '\x1b[2J\x1b[H{"Name":"listenup-b5-api-1","CPUPerc":"57.25%","MemUsage":"1GiB"}'
    assert parse_stats_line(line) == ("listenup-b5-api-1", 57.25)


def test_parse_stats_line_skips_lines_without_a_sample() -> None:
    assert parse_stats_line("") is None
    assert parse_stats_line("\x1b[2J\x1b[H") is None
    assert parse_stats_line('{"Name":"x","CPUPerc":"--"}') is None


def test_cpu_is_a_share_of_all_host_cores_per_role_and_for_the_server() -> None:
    roles = {"b5-api-1": "api", "b5-postgres-1": "db", "b5-worker-1": "worker", "k6": "load"}
    samples = [
        ("b5-api-1", 40.0),
        ("b5-postgres-1", 20.0),
        ("b5-worker-1", 4.0),
        ("k6", 80.0),
        ("b5-api-1", 80.0),
        ("b5-postgres-1", 40.0),
        ("b5-worker-1", 4.0),
        ("k6", 80.0),
        ("other", 100.0),
    ]
    cpu = summarise_cpu(samples, cores=4, roles=roles)
    assert cpu["api"]["mean_pct"] == 15.0  # (40 + 80) / 2 / 4 cores
    assert cpu["api"]["max_pct"] == 20.0
    assert cpu["db"]["mean_pct"] == 7.5
    # The server is the API, database and worker together, sample by sample; the load
    # generator is reported but is not the server.
    assert cpu["server"]["mean_pct"] == pytest.approx((64 + 124) / 2 / 4)
    assert cpu["server"]["max_pct"] == 31.0
    assert cpu["load"]["mean_pct"] == 20.0
    assert "other" not in cpu


def test_cpu_without_samples_is_unknown() -> None:
    cpu = summarise_cpu([], cores=4, roles={"a": "api"})
    assert cpu["api"] == {"mean_pct": None, "p95_pct": None, "max_pct": None, "samples": 0}
    assert cpu["server"]["samples"] == 0


# pg_stat_statements: the heaviest statements, with the slow ones flagged for follow-up.


def statement(query: str, calls: int, total: float) -> dict[str, object]:
    return {
        "query": query,
        "calls": calls,
        "total_ms": total,
        "mean_ms": total / calls,
        "max_ms": total,
        "rows": calls,
        "shared_blks_hit": 0,
        "shared_blks_read": 0,
    }


def test_rank_statements_by_total_and_by_mean_and_flags_slow_ones() -> None:
    rows = [
        statement("SELECT a", 1000, 2000.0),  # mean 2 ms, most total
        statement("SELECT b", 2, 60.0),  # mean 30 ms: slow
        statement("SELECT c", 10, 50.0),  # mean 5 ms
    ]
    ranked = rank_statements(rows, top=2, slow_mean_ms=10.0)
    assert [r["query"] for r in ranked["by_total"]] == ["SELECT a", "SELECT b"]
    assert [r["query"] for r in ranked["by_mean"]] == ["SELECT b", "SELECT c"]
    assert [r["query"] for r in ranked["slow"]] == ["SELECT b"]


def test_a_statement_exactly_at_the_slow_limit_is_flagged() -> None:
    ranked = rank_statements([statement("SELECT d", 1, 10.0)], top=5, slow_mean_ms=10.0)
    assert [r["query"] for r in ranked["slow"]] == ["SELECT d"]


def test_rank_statements_ignores_the_extension_and_the_runners_own_queries() -> None:
    rows = [statement("SELECT pg_stat_statements_reset()", 1, 50.0), statement("SELECT a", 1, 1.0)]
    ranked = rank_statements(rows, top=5, slow_mean_ms=10.0)
    assert [r["query"] for r in ranked["by_total"]] == ["SELECT a"]


# Verdict: System Design 1.1 and 12.1 targets; a local run is never stage-0 evidence.


def summary_with(
    read_p95: float | None, write_p95: float | None, write_errors: float = 0.0
) -> dict[str, dict]:
    return {
        "read": {"p95_ms": read_p95, "error_rate": 0.0},
        "write": {"p95_ms": write_p95, "error_rate": write_errors},
    }


def cpu_with(server: float | None) -> dict[str, dict]:
    return {"server": {"mean_pct": server}}


PLANNED = {"mixed_rps": 15.0, "heartbeat_rps": 4.0}


def judge(summary, cpu, achieved=PLANNED, *, stage0=False):
    return verdict(summary, cpu, achieved, PLANNED, stage0=stage0)


def test_verdict_passes_within_every_target_but_says_it_is_local() -> None:
    result = judge(summary_with(199.9, 299.9), cpu_with(29.9))
    assert result["meets_targets"] is True
    assert result["label"] == LOCAL_LABEL
    assert result["stage0_evidence"] is False


@pytest.mark.parametrize(
    ("read", "write", "cpu", "failed"),
    [
        (200.0, 100.0, 10.0, "read_p95"),  # "under 200 ms": 200 itself misses
        (100.0, 300.0, 10.0, "write_p95"),
        (100.0, 100.0, 30.0, "cpu"),
        (None, 100.0, 10.0, "read_p95"),  # nothing measured is not a pass
        (100.0, 100.0, None, "cpu"),
    ],
)
def test_verdict_fails_at_or_over_a_target_or_without_a_measurement(read, write, cpu, failed):
    result = judge(summary_with(read, write), cpu_with(cpu))
    assert result["meets_targets"] is False
    assert result["checks"][failed] is False


def test_a_stage0_run_is_labelled_as_such() -> None:
    result = judge(summary_with(10, 10), cpu_with(1), stage0=True)
    assert result["stage0_evidence"] is True
    assert result["label"] != LOCAL_LABEL


# The Markdown report shows the label first, the targets and the slow statements.


def test_render_markdown_leads_with_the_host_label_and_lists_slow_statements() -> None:
    report = {
        "environment": {"host": "local", "git_sha": "abc123", "cores": 4},
        "load": {"mixed_rps": 15, "blind_learners": 20, "warmup_s": 60, "duration_s": 600},
        "requests": summarise_requests([req("read", 10), req("write", 20), req("heartbeat", 5)]),
        "blind_stops": {"too_fast": 1},
        "cpu": summarise_cpu([("api", 8.0)], cores=4, roles={"api": "api"}),
        "statements": rank_statements([statement("SELECT b", 2, 60.0)], top=5, slow_mean_ms=10.0),
        "blind_attempts": summarise_attempts([("voided", "missed_heartbeat", 2)]),
        "verdict": judge(summary_with(10, 20), cpu_with(2)),
    }
    text = render_markdown(report)
    first = text.splitlines()[0]
    assert first.startswith("# B5 load test") and "local" in first.lower()
    assert LOCAL_LABEL in text
    assert "| read | 1 |" in text
    assert "SELECT b" in text
    assert "too_fast" in text
    assert "missed_heartbeat x2" in text


# The report says what load was actually delivered, so a short-changed run is visible.


def test_achieved_rates_are_requests_per_second_of_the_measured_window() -> None:
    requests = [req("read", 1)] * 30 + [req("write", 1)] * 6 + [req("heartbeat", 1)] * 8
    requests += [req("read", 1, phase="warmup")] * 100
    rates = achieved_rates(summarise_requests(requests), duration_s=2)
    assert rates == {"mixed_rps": 18.0, "heartbeat_rps": 4.0}


def test_achieved_rates_without_a_window_are_unknown() -> None:
    assert achieved_rates(summarise_requests([]), duration_s=0) == {
        "mixed_rps": None,
        "heartbeat_rps": None,
    }


# A run whose requests fail, or that sends less than planned, is not a pass however fast
# its responses were (#155: failures stay in the outcome).


def test_verdict_fails_when_requests_fail_even_if_they_were_fast() -> None:
    # The default local run: 4.96% of writes (all heartbeats) got no response.
    result = judge(summary_with(22.4, 31.1, write_errors=0.0496), cpu_with(6.6))
    assert result["checks"]["errors"] is False
    assert result["meets_targets"] is False


def test_an_error_rate_exactly_at_the_limit_misses() -> None:
    assert judge(summary_with(10, 10, write_errors=0.01), cpu_with(1))["checks"]["errors"] is False
    assert judge(summary_with(10, 10, write_errors=0.0099), cpu_with(1))["checks"]["errors"]


@pytest.mark.parametrize(
    ("achieved", "delivered"),
    [
        ({"mixed_rps": 15.0, "heartbeat_rps": 1.8}, False),  # the discarded run: 45% of beats
        ({"mixed_rps": 14.2, "heartbeat_rps": 4.0}, False),
        ({"mixed_rps": 14.25, "heartbeat_rps": 3.8}, True),  # exactly 95% of the plan
        ({"mixed_rps": None, "heartbeat_rps": 4.0}, False),
    ],
)
def test_verdict_fails_when_less_than_95_percent_of_the_plan_was_sent(achieved, delivered) -> None:
    result = judge(summary_with(10, 10), cpu_with(1), achieved)
    assert result["checks"]["delivered"] is delivered
    assert result["meets_targets"] is delivered


# Fast failures can pull a percentile down, so each group also has p95 over the requests
# that got a response.


def test_each_group_also_has_a_p95_of_the_answered_requests() -> None:
    requests = [req("heartbeat", 1.0, status=0)] * 10 + [req("heartbeat", 50.0)] * 10
    summary = summarise_requests(requests)
    assert summary["heartbeat"]["p95_ms"] == 50.0
    assert summary["heartbeat"]["p50_ms"] == 1.0
    assert summary["heartbeat"]["p95_answered_ms"] == 50.0
    assert summary["heartbeat"]["p50_answered_ms"] == 50.0


def test_a_group_with_no_answered_request_has_no_answered_p95() -> None:
    summary = summarise_requests([req("read", 2.0, status=0)])
    assert summary["read"]["p95_answered_ms"] is None


# CPU: a sampling round that misses a server container would understate the server.


def test_a_cpu_round_missing_a_server_container_is_left_out_of_the_server_figure() -> None:
    roles = {"api": "api", "db": "db", "worker": "worker", "k6": "load"}
    samples = [
        ("api", 40.0),
        ("worker", 4.0),  # no db sample in this round
        ("api", 80.0),
        ("db", 40.0),
        ("worker", 4.0),
        ("k6", 8.0),
    ]
    cpu = summarise_cpu(samples, cores=4, roles=roles)
    assert cpu["server"]["samples"] == 1
    assert cpu["server"]["mean_pct"] == 31.0  # (80 + 40 + 4) / 4 cores
    assert cpu["server"]["incomplete_rounds"] == 1
    assert cpu["api"]["samples"] == 2  # per-role figures keep every sample


# The measured window, the statement reset and the CPU window all follow one start time
# that k6 waits for, rather than a guess at when k6's clock started.


def test_the_measured_window_follows_the_agreed_start_and_the_warmup() -> None:
    assert measured_window(start_at=1000.0, warmup_s=60, duration_s=600) == (1060.0, 1660.0)


# Blind attempts at the end of the run, by outcome: a listen whose `ended` beat got no
# answer stays unfinished, and the expiry worker voids it where k6 cannot see.


def test_summarise_attempts_counts_outcomes_and_void_reasons() -> None:
    rows = [("listened", None, 90), ("voided", "missed_heartbeat", 3), ("unfinished", None, 7)]
    assert summarise_attempts(rows) == {
        "listened": 90,
        "unfinished": 7,
        "voided": {"missed_heartbeat": 3},
    }


# The seed manifest holds session tokens: private while it exists, gone afterwards.


def test_the_private_manifest_is_owner_only_and_removed_even_after_a_failure() -> None:
    with pytest.raises(RuntimeError), private_manifest() as path:
        path.write_text("tokens")
        folder = path.parent
        assert stat.S_IMODE(os.stat(folder).st_mode) == 0o700
        raise RuntimeError("k6 failed")
    assert not folder.exists()


# --stage0 is a claim about where the run happened: refuse it with the local stack.


def test_stage0_is_refused_against_the_local_compose_stack() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--out", "x", "--stage0"])
    with pytest.raises(SystemExit):
        parse_args(["--out", "x", "--stage0", "--base-url", "https://stage0.example"])


def test_stage0_is_accepted_against_a_deployment_that_is_already_running() -> None:
    args = parse_args(
        ["--out", "x", "--stage0", "--skip-up", "--base-url", "https://stage0.example"]
    )
    assert args.stage0 is True
