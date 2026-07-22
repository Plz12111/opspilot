import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, model_validator

from opspilot.agent.models import Evidence
from opspilot.services.incidents import new_id


class TimeRangeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: datetime
    end: datetime

    @model_validator(mode="after")
    def validate_time_range(self) -> Self:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("start and end must include a timezone")
        if self.end <= self.start:
            raise ValueError("end must be later than start")
        if self.end - self.start > timedelta(hours=6):
            raise ValueError("query time range cannot exceed 6 hours")
        return self


def make_evidence(
    source_type: str,
    source_uri: str,
    payload: Any,
    attributes: dict[str, Any] | None = None,
) -> Evidence:
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return Evidence(
        id=new_id("evd"),
        source_type=source_type,
        source_uri=source_uri,
        content=content,
        attributes={**(attributes or {}), "checksum": hashlib.sha256(content.encode()).hexdigest()},
    )
