from dataclasses import dataclass
from enum import Enum
from typing import Literal

from pydantic import BaseModel


class Status(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"


class Notification(BaseModel):
    to: str
    message: str
    type: Literal["email", "sms"]


@dataclass
class RequestRecord:
    id: str
    user_input: str
    status: Status = Status.QUEUED
    submitted: bool = False
    notification: Notification | None = None
    provider_id: str | None = None
    failure_reason: str | None = None
