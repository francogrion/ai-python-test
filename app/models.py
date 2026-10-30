from typing import Literal

from pydantic import BaseModel


class Notification(BaseModel):
    to: str
    message: str
    type: Literal["email", "sms"]
