import pytest


@pytest.mark.django_db
def test_health_reports_database_ok(api):
    response = api.get("/api/v1/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
    assert response["X-Request-ID"]


@pytest.mark.django_db
def test_unauthenticated_request_gets_401_in_standard_error_format(api):
    response = api.get("/api/v1/auth/me/", HTTP_X_REQUEST_ID="test-request-0001")
    assert response.status_code == 401
    error = response.json()["error"]
    assert error["code"] == "not_authenticated"
    assert error["request_id"] == "test-request-0001"


@pytest.mark.django_db
def test_invalid_request_id_header_is_replaced(api):
    response = api.get("/api/v1/health/", HTTP_X_REQUEST_ID="bad id with spaces")
    assert response["X-Request-ID"] != "bad id with spaces"


@pytest.mark.django_db
def test_unknown_endpoint_is_404(api, make_user, login):
    login(make_user("doctor"))
    assert api.get("/api/v1/does-not-exist/").status_code == 404


@pytest.mark.django_db
def test_security_headers_present(api):
    response = api.get("/api/v1/health/")
    assert response["X-Frame-Options"] == "DENY"
    assert response["X-Content-Type-Options"] == "nosniff"
