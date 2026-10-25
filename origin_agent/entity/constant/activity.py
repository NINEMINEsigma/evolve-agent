"""Process activity event limits and transport constants."""

ACTIVITY_EVENT_BUFFER_SIZE: int = 256
ACTIVITY_EVENT_QUEUE_SIZE: int = 256
ACTIVITY_SSE_HEARTBEAT_SECONDS: float = 15.0
ACTIVITY_SSE_EVENT_NAME: str = "activity"
ACTIVITY_SSE_GAP_EVENT_NAME: str = "activity_gap"
