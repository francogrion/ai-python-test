"""Settings, overridable through an environment variable named like each field."""

import os
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class Settings:
    provider_url: str = "http://localhost:3001"
    provider_api_key: str = "test-dev-2026"

    extraction_workers: int = 32
    notification_workers: int = 5
    queue_max_size: int = 10_000
    max_finished_requests: int = 100_000

    # Every AI call counts in the scorecard ratio, failed ones included.
    ai_max_calls: int = 2
    ai_retry_delay: float = 0.5

    # The provider allows 50 notifications every 10 s.
    notify_rate_per_second: float = 4.5
    notify_max_attempts: int = 5
    notify_retry_base_delay: float = 0.5
    notify_retry_max_delay: float = 8.0
    rate_limit_pause: float = 2.0

    # Generous on purpose: under load the provider slows down because of its own
    # synchronous metrics writes, and giving up on it only causes duplicates.
    connect_timeout: float = 5.0
    ai_read_timeout: float = 30.0
    notify_read_timeout: float = 15.0

    @classmethod
    def from_env(cls) -> "Settings":
        values = {}
        for field in fields(cls):
            raw = os.getenv(field.name.upper())
            if raw is not None:
                values[field.name] = type(field.default)(raw)
        return cls(**values)
