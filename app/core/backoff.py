def get_backoff_delay(attempts: int, delays: list[int]) -> int:
    index = min(attempts - 1, len(delays) - 1)
    return delays[index]
