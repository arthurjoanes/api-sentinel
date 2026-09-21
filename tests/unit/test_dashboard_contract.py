import json
from pathlib import Path


def test_current_state_panels_do_not_reuse_a_historical_non_null_success() -> None:
    dashboard_path = (
        Path(__file__).parents[2] / "monitoring" / "grafana" / "dashboards" / "sentinel.json"
    )
    panels = json.loads(dashboard_path.read_text(encoding="utf-8"))["panels"]
    for panel in panels:
        if panel["type"] == "stat":
            assert panel["options"]["reduceOptions"]["calcs"] == ["last"]
            for target in panel["targets"]:
                assert target["instant"] is True
                assert target["range"] is False
            assert panel["fieldConfig"]["defaults"]["noValue"]


def test_quota_indicator_describes_rejections_not_the_contracted_limit() -> None:
    dashboard_path = (
        Path(__file__).parents[2] / "monitoring" / "grafana" / "dashboards" / "sentinel.json"
    )
    panels = json.loads(dashboard_path.read_text(encoding="utf-8"))["panels"]
    quota = next(panel for panel in panels if panel["id"] == 7)
    assert "Rejeições" in quota["title"]
    assert 'outcome="quota"' in quota["targets"][0]["expr"]
    assert "429" in quota["description"]
