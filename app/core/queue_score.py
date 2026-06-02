from datetime import datetime


def calculate_queue_score(priority: int, created_at: datetime) -> float:
    """
    Higher priority = higher score = processed first.
    Within same priority, older jobs win (FIFO).
    Millisecond precision for tie-breaking.
    """
    return priority * 1_000_000_000_000 - int(created_at.timestamp() * 1000)
