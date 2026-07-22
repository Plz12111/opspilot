async def test_latest_evaluation_exposes_comparison_report(client) -> None:
    app = client._transport.app
    app.state.settings.evaluation_report_path = "evals/reports/incident-comparison.json"

    response = await client.get("/api/v1/evaluations/latest")

    assert response.status_code == 200
    report = response.json()
    assert report["candidate"]["metrics"]["case_count"] == 80
    assert report["candidate"]["baseline_name"] == "source-weighted-v2"
    assert report["top1_delta"] >= 0.20
    assert report["stability"]["top1_agreement"] == 1.0


async def test_latest_evaluation_returns_404_when_report_is_missing(client, tmp_path) -> None:
    app = client._transport.app
    app.state.settings.evaluation_report_path = str(tmp_path / "missing.json")

    response = await client.get("/api/v1/evaluations/latest")

    assert response.status_code == 404
    assert "run make eval" in response.json()["detail"]
