"""Estado local, contratos de borda e ausência de tokens nos artefatos públicos."""

import json
from datetime import UTC, datetime

from operations import ARTIFACTS, LOCAL_URLS, PROJECT, healthy_targets, incidents, request


def main() -> None:
    output = {"executed_at": datetime.now(UTC).isoformat()}
    for name, path in (
        ("uri_limit", "/" + "a" * 6000),
        ("unauthorized", "/v1/stores"),
        ("readiness", "/health/ready"),
    ):
        status, body, headers = request(LOCAL_URLS["proxy"] + path)
        headers = {key.lower(): value for key, value in headers.items()}
        output[name] = {
            "status": status,
            "content_type": headers.get("content-type"),
            "challenge": headers.get("www-authenticate"),
            "body": body,
        }
    assert output["uri_limit"]["status"] == 414
    assert output["uri_limit"]["content_type"] == "application/problem+json"
    assert output["unauthorized"]["status"] == 401
    assert output["unauthorized"]["challenge"] == "Bearer"
    assert output["readiness"]["status"] == 200
    output["targets"] = healthy_targets()
    assert len(output["targets"]) == 2
    output["active_incidents"] = [item["id"] for item in incidents() if item["status"] == "firing"]
    tokens = json.loads((PROJECT / ".runtime/demo.json").read_text()).values()
    public_roots = [ARTIFACTS, PROJECT / "src", PROJECT / "tests", PROJECT / "docs"]
    leaked_files = []
    for root in public_roots:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in {".json", ".xml", ".log", ".md", ".py"}:
                content = path.read_text(encoding="utf-8", errors="replace")
                if any(token in content for token in tokens):
                    leaked_files.append(str(path.relative_to(PROJECT)))
    output["token_matches_in_public_files"] = leaked_files
    assert not leaked_files, "Token localizado em arquivo público; revisar sem imprimir seu valor."
    (ARTIFACTS / "final-state.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
