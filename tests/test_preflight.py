"""Smoke tests for preflight checks.

These tests assert structural invariants — they don't make claims
about whether Docker is actually installed on the test machine, since
that varies. Functional integration tests would go in a separate
suite that the dev runs locally with Docker up.
"""

from __future__ import annotations

from mediahub_setup import preflight


def test_run_all_returns_results_for_every_check():
    results = preflight.run_all()
    assert len(results) >= 5
    names = {r.name for r in results}
    assert "Docker installed" in names
    assert "Docker daemon running" in names
    assert "Compose plugin" in names
    assert "Required ports" in names


def test_every_result_has_required_fields():
    for r in preflight.run_all():
        assert r.name
        assert r.status in {"pass", "warn", "fail"}
        assert r.message


def test_overall_status_is_worst_of_results():
    pass_r = preflight.CheckResult("x", "pass", "ok")
    warn_r = preflight.CheckResult("x", "warn", "meh")
    fail_r = preflight.CheckResult("x", "fail", "no")

    assert preflight.overall_status([pass_r, pass_r]) == "pass"
    assert preflight.overall_status([pass_r, warn_r]) == "warn"
    assert preflight.overall_status([pass_r, warn_r, fail_r]) == "fail"
    assert preflight.overall_status([fail_r]) == "fail"
