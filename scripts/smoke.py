from __future__ import annotations

import argparse

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test a running OpsPilot API")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url, timeout=10) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")
        workspace = client.get("/")
        schema = client.get("/openapi.json")
        evaluation = client.get("/api/v1/evaluations/latest")
    live.raise_for_status()
    ready.raise_for_status()
    workspace.raise_for_status()
    schema.raise_for_status()
    evaluation.raise_for_status()
    assert live.json()["status"] == "ok"
    assert ready.json()["status"] in {"ready", "degraded"}
    assert "OpsPilot" in workspace.text
    assert "/api/v1/incidents/{incident_id}/investigate" in schema.json()["paths"]
    assert evaluation.json()["candidate"]["metrics"]["case_count"] >= 80
    print("OpsPilot smoke test passed")


if __name__ == "__main__":
    main()
