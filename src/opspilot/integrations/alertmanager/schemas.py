from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AlertmanagerAlert(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: str
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    starts_at: datetime = Field(alias="startsAt")
    ends_at: datetime | None = Field(default=None, alias="endsAt")
    generator_url: str = Field(default="", alias="generatorURL")
    fingerprint: str = ""


class AlertmanagerWebhook(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    receiver: str = ""
    status: str
    alerts: list[AlertmanagerAlert]
    group_labels: dict[str, str] = Field(default_factory=dict, alias="groupLabels")
    common_labels: dict[str, str] = Field(default_factory=dict, alias="commonLabels")
    common_annotations: dict[str, str] = Field(default_factory=dict, alias="commonAnnotations")
    external_url: str = Field(default="", alias="externalURL")
    version: str = "4"
    group_key: str = Field(default="", alias="groupKey")
    truncated_alerts: int = Field(default=0, alias="truncatedAlerts")
    extra: dict[str, Any] = Field(default_factory=dict)


class AlertIngestResult(BaseModel):
    accepted: int
    created: int
    merged: int
    duplicate_events: int
    incident_ids: list[str]
