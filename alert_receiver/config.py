import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_path: Path = Path("/data/alerts.sqlite3")
    webhook_token_file: Path = Path("/secrets/webhook-token")
    probe_credentials_file: Path = Path("/secrets/demo.json")
    expected_replicas_file: Path = Path("/secrets/expected-replicas")
    probe_url: str = "http://proxy/v1/stores/7/summary?start=2026-01-01&end=2026-01-01"
    probe_interval_seconds: float = 3.0
    probe_timeout_seconds: float = 2.0
    probe_enabled: bool = True
    webhook_max_bytes: int = 65_536
    retention_days: int = 30
    runbooks_path: Path = Path(__file__).resolve().parent.parent / "docs" / "runbooks"
    public_urls_file: Path | None = None

    def __post_init__(self) -> None:
        if (
            not 0.1 <= self.probe_interval_seconds <= 60
            or not 0.1 <= self.probe_timeout_seconds <= 10
        ):
            raise ValueError("Intervalo ou deadline do probe fora dos limites.")
        if not 1 <= self.retention_days <= 365:
            raise ValueError("A retenção deve estar entre 1 e 365 dias.")
        if not 1 <= self.webhook_max_bytes <= 65_536:
            raise ValueError("O limite de webhook deve estar entre 1 e 65536 bytes.")

    @property
    def probe_stale_after_seconds(self) -> float:
        return max(15.0, 2 * max(self.probe_interval_seconds, self.probe_timeout_seconds))

    @classmethod
    def from_environment(cls) -> "Settings":
        defaults = cls()
        enabled = os.getenv("PROBE_ENABLED", "true").lower()
        if enabled not in ("true", "false"):
            raise ValueError("PROBE_ENABLED deve ser true ou false.")
        return cls(
            database_path=Path(os.getenv("ALERT_DATABASE_PATH", str(defaults.database_path))),
            webhook_token_file=Path(
                os.getenv("WEBHOOK_TOKEN_FILE", str(defaults.webhook_token_file))
            ),
            probe_credentials_file=Path(
                os.getenv("PROBE_CREDENTIALS_FILE", str(defaults.probe_credentials_file))
            ),
            expected_replicas_file=Path(
                os.getenv("EXPECTED_REPLICAS_FILE", str(defaults.expected_replicas_file))
            ),
            probe_url=os.getenv("PROBE_URL", defaults.probe_url),
            probe_interval_seconds=float(os.getenv("PROBE_INTERVAL_SECONDS", "3")),
            probe_timeout_seconds=float(os.getenv("PROBE_TIMEOUT_SECONDS", "2")),
            probe_enabled=enabled == "true",
            retention_days=int(os.getenv("ALERT_RETENTION_DAYS", "30")),
            runbooks_path=Path(os.getenv("RUNBOOKS_PATH", str(defaults.runbooks_path))),
            public_urls_file=Path(os.environ["PUBLIC_URLS_FILE"])
            if os.getenv("PUBLIC_URLS_FILE")
            else None,
        )
