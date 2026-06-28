from gateway_enhancement_agent.capability_coverage import CapabilityCoverage


def test_capability_coverage_builds_rows(mock_target_repo):
    rows = CapabilityCoverage().build()
    assert len(rows) >= 4
    statuses = {r.status for r in rows}
    assert statuses & {"partial", "gap", "full", "unknown"}
