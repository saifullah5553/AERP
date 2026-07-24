from __future__ import annotations

from app.core.ratelimit import check_rate_limit


class FakeRedis:
    """Minimal INCR/EXPIRE/TTL stub for testing the limiter logic."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key: str, seconds: int) -> None:
        self.ttls[key] = seconds

    def ttl(self, key: str) -> int:
        return self.ttls.get(key, -1)


def test_allows_under_limit() -> None:
    r = FakeRedis()
    for i in range(1, 4):
        allowed, remaining, retry = check_rate_limit(r, "k", limit=3, window=60)
        assert allowed is True
        assert remaining == 3 - i
        assert retry == 0


def test_blocks_over_limit() -> None:
    r = FakeRedis()
    for _ in range(3):
        check_rate_limit(r, "k", limit=3, window=60)
    allowed, remaining, retry = check_rate_limit(r, "k", limit=3, window=60)
    assert allowed is False
    assert remaining == 0
    assert retry == 60


def test_expire_set_on_first_hit() -> None:
    r = FakeRedis()
    check_rate_limit(r, "k", limit=10, window=45)
    assert r.ttls["k"] == 45
