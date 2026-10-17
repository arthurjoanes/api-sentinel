import os
import subprocess
import sys
from pathlib import Path


def test_business_timezone_works_without_system_timezone_database() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from datetime import date; "
            "from api_sentinel.queries import period_bounds; "
            "print(period_bounds(date(2026, 1, 1), date(2026, 1, 1))[0].isoformat())",
        ],
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src"),
            "PYTHONTZPATH": "",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "2026-01-01T03:00:00+00:00"
