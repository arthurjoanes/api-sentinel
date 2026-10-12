"""Sequential scans of this attempt's identified images, without finding exclusions."""

import json
from collections.abc import Callable
from pathlib import Path

TRIVY = (
    "aquasec/trivy:0.74.0@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969"
)


def scan_images(run: Callable, output: Path, runtime: str, proxy: str) -> dict:
    private = output.parents[2] / ".runtime" / "scans" / output.name
    private.mkdir(parents=True, exist_ok=True)
    summary = {}
    fields = (
        "VulnerabilityID",
        "PkgName",
        "InstalledVersion",
        "FixedVersion",
        "Severity",
        "PrimaryURL",
    )
    for name, image in (("runtime", runtime), ("proxy", proxy)):
        run(
            "scan-" + name,
            [
                "docker",
                "run",
                "--rm",
                "--label",
                "sentinel.review.attempt=" + output.name,
                "-v",
                "/var/run/docker.sock:/var/run/docker.sock:ro",
                "-v",
                str(private) + ":/reports",
                TRIVY,
                "image",
                "--scanners",
                "vuln",
                "--ignorefile",
                "/dev/null",
                "--format",
                "json",
                "--output",
                "/reports/" + name + ".json",
                image,
            ],
            timeout=600,
        )
        report = json.loads((private / (name + ".json")).read_text())
        assert report["SchemaVersion"] == 2 and report["Metadata"]["ImageID"]
        required = {"os-pkgs", "lang-pkgs"} if name == "runtime" else {"os-pkgs"}
        assert required <= {item.get("Class") for item in report["Results"]}
        public = {
            "SchemaVersion": 2,
            "Metadata": {key: report["Metadata"][key] for key in ("ImageID", "OS")},
            "Results": [
                {
                    "Target": item["Target"],
                    "Class": item.get("Class"),
                    "Vulnerabilities": [
                        {key: finding.get(key) for key in fields}
                        for finding in (item.get("Vulnerabilities") or [])
                    ],
                }
                for item in report["Results"]
            ],
        }
        (output / (name + "-vulnerabilities.json")).write_text(json.dumps(public, indent=2))
        blocked = [
            finding
            for item in public["Results"]
            for finding in item["Vulnerabilities"]
            if finding["Severity"] in ("HIGH", "CRITICAL")
        ]
        summary[name] = {"image_id": report["Metadata"]["ImageID"], "high_critical": len(blocked)}
        if blocked:
            raise RuntimeError(f"{name}: {len(blocked)} HIGH/CRITICAL vulnerabilities.")
    return summary
