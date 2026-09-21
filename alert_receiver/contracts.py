from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class Alert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["firing", "resolved"]
    labels: dict[str, str]
    annotations: dict[str, str]
    startsAt: AwareDatetime
    endsAt: AwareDatetime
    generatorURL: str = Field(default="", max_length=2_048)
    fingerprint: str = Field(pattern=r"^[a-fA-F0-9]{8,64}$")

    @field_validator("labels", "annotations")
    @classmethod
    def bounded_mapping(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 32 or any(len(k) > 128 or len(v) > 4_096 for k, v in value.items()):
            raise ValueError("Metadados acima do limite.")
        return value

    @model_validator(mode="after")
    def validate_incident(self) -> "Alert":
        if not self.labels.get("alertname"):
            raise ValueError("O nome do alerta é obrigatório.")
        if not self.annotations.get("summary"):
            raise ValueError("O resumo do alerta é obrigatório.")
        if self.status == "resolved" and self.endsAt < self.startsAt:
            raise ValueError("A recuperação deve ser posterior ao início.")
        return self

    @property
    def start_key(self) -> str:
        return self.startsAt.astimezone(UTC).isoformat(timespec="microseconds")


class Webhook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["4"] = "4"
    groupKey: str = Field(default="", max_length=4_096)
    truncatedAlerts: int = Field(default=0, ge=0)
    status: Literal["firing", "resolved"]
    receiver: str = Field(default="local", max_length=128)
    groupLabels: dict[str, str] = Field(default_factory=dict)
    commonLabels: dict[str, str] = Field(default_factory=dict)
    commonAnnotations: dict[str, str] = Field(default_factory=dict)
    externalURL: str = Field(default="", max_length=2_048)
    alerts: list[Alert] = Field(min_length=1, max_length=100)


class Incident(BaseModel):
    id: int
    fingerprint: str
    starts_at: datetime
    status: Literal["firing", "resolved"]
    ends_at: datetime | None
    first_received_at: datetime
    last_received_at: datetime
    deliveries: int
    labels: dict[str, str]
    annotations: dict[str, str]


class IncidentEvent(BaseModel):
    received_at: datetime
    delivered_status: Literal["firing", "resolved"]
    transition: str


@dataclass(frozen=True)
class IncidentPage:
    records: list[Incident]
    counts: dict[str, int]
    generated_at: datetime
    cutoff_at: datetime
    retention_days: int
    limit: int

    @property
    def total(self) -> int:
        return sum(self.counts.values())
