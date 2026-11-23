from django.db import connection


def next_number(name: str, period: str = "") -> int:
    """Atomically increment and return the counter for (name, period). Safe under concurrency."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO core_counter (name, period, value) VALUES (%s, %s, 1)
            ON CONFLICT (name, period) DO UPDATE SET value = core_counter.value + 1
            RETURNING value
            """,
            [name, period],
        )
        return cursor.fetchone()[0]
