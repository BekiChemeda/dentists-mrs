"""Sign-in limits count each clinic computer separately, even though every request arrives through nginx."""
from rest_framework.test import APIClient


def _attempt(ip):
    client = APIClient(REMOTE_ADDR="172.18.0.5")  # nginx's container address, the same for everyone
    return client.post("/api/v1/auth/login/", {"username": "nobody", "password": "wrong"}, format="json",
                       HTTP_X_REAL_IP=ip).status_code


def test_one_busy_computer_does_not_lock_out_the_others(db, monkeypatch):
    from apps.core.throttling import ClientScopedRateThrottle

    # DRF reads the rates when the class is defined, so lower the sign-in limit on the class itself.
    monkeypatch.setattr(ClientScopedRateThrottle, "THROTTLE_RATES",
                        {**ClientScopedRateThrottle.THROTTLE_RATES, "login": "3/min"})
    codes = [_attempt("192.168.1.21") for _ in range(4)]
    assert codes[-1] == 429  # this computer reached its limit
    assert _attempt("192.168.1.22") != 429  # the reception computer next to it can still sign in
