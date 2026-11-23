"""A database outage gives a clear JSON 503, not an HTML error page. The full kill-the-database test is
deploy/scripts/test-resilience.py; these check the error mapping without stopping PostgreSQL."""
from unittest import mock

from django.db import OperationalError

from apps.core.exceptions import api_exception_handler, database_is_down


def test_unreachable_database_is_reported_as_down():
    assert database_is_down(OperationalError("connection failed: FATAL: the database system is starting up"))
    assert database_is_down(OperationalError("connection to server failed: Connection refused"))
    assert not database_is_down(ValueError("not a database error"))


def test_other_database_errors_are_not_called_an_outage(db):
    # A lock timeout while the server is up is an ordinary error: the reconnect succeeds.
    assert not database_is_down(OperationalError("canceling statement due to lock timeout"))


def test_handler_returns_503_json_without_writing_to_the_database(db):
    with mock.patch("apps.core.exceptions.record_error") as record:
        response = api_exception_handler(OperationalError("could not connect to server"), {"request": None})
    assert response.status_code == 503
    assert response.data["error"]["code"] == "database_unavailable"
    assert response["Retry-After"] == "30"
    record.assert_not_called()


def test_errors_outside_views_come_back_as_json(db):
    from django.test import Client

    client = Client(raise_request_exception=False)
    # Simulate the database failing while the session middleware loads the session.
    with mock.patch("django.contrib.sessions.backends.db.SessionStore.load",
                    side_effect=OperationalError("could not connect to server: Connection refused")):
        client.cookies["mrs_session"] = "x" * 32
        response = client.get("/api/v1/auth/me/")
    assert response.status_code == 503
    assert response["Content-Type"].startswith("application/json")
    assert response.json()["error"]["code"] == "database_unavailable"
