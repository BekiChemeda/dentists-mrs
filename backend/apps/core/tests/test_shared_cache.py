from django.core.cache import cache
from django.db import connection


def test_request_limits_use_a_cache_shared_by_all_workers(db):
    # An in-memory cache would give each Gunicorn worker its own count, multiplying the sign-in limit.
    from django.core.cache import caches

    assert type(caches["default"]).__name__ == "DatabaseCache"
    cache.set("probe", 1, 30)
    with connection.cursor() as cur:
        cur.execute("SELECT count(*) FROM core_cache")
        assert cur.fetchone()[0] >= 1
