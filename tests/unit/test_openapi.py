import pytest
from pydantic import ValidationError

from api_sentinel.app import app
from api_sentinel.contracts import StoreSummary


def test_openapi_exposes_usable_bearer_auth_and_concrete_responses() -> None:
    schema = app.openapi()
    assert schema["components"]["securitySchemes"]["SentinelCredential"]["scheme"] == "bearer"
    expected = {
        "/v1/stores": "StoreList",
        "/v1/stores/{store_id}/summary": "StoreSummary",
        "/v1/stores/{store_id}/sales": "SalesPage",
        "/v1/stores/{store_id}/availability/{sku}": "Availability",
    }
    for path, response_name in expected.items():
        operation = schema["paths"][path]["get"]
        assert operation["security"] == [{"SentinelCredential": []}]
        assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
            "$ref": f"#/components/schemas/{response_name}"
        }
        errors = operation["responses"]["401"]["content"]
        assert "application/problem+json" in errors
        assert "request_id" in errors["application/problem+json"]["schema"]["properties"]
    assert "security" not in schema["paths"]["/health/live"]["get"]


@pytest.mark.parametrize("invalid_cents", [12.5, "12500", -1, True])
def test_public_summary_never_coerces_invalid_money(invalid_cents: object) -> None:
    with pytest.raises(ValidationError) as error:
        StoreSummary.model_validate(
            {
                "store_id": 7,
                "start": "2026-01-01",
                "end": "2026-01-01",
                "currency": "BRL",
                "revenue_cents": invalid_cents,
                "order_count": 2,
                "average_ticket_cents": 6250,
                "data_updated_at": "2026-01-02T03:00:00+00:00",
                "observed_at": "2026-01-02T03:00:00+00:00",
                "dataset_version": "fixture-v1",
                "coverage": {"complete": True, "starts_on": "2026-01-01", "ends_on": "2026-01-01"},
                "cache_age_seconds": 0,
            }
        )
    assert error.value.errors()[0]["loc"] == ("revenue_cents",)
