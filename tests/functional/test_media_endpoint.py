"""The real server process exposes the media endpoint over TLS, and nothing else on that port."""

from __future__ import annotations

import httpx
import pytest

from .harness import GroundZero

pytestmark = pytest.mark.functional


def test_media_listener_runs_over_tls_and_hides_the_api(simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    with httpx.Client(verify=False, timeout=10) as media:
        assert media.get(f"{gz.media_url}/media/unknown/x.iso").status_code == 404
        assert media.get(f"{gz.media_url}/api/v1/hosts").status_code == 404
        assert media.get(f"{gz.media_url}/healthz").status_code == 404
    with pytest.raises(httpx.HTTPError):  # plain HTTP is not served on the media port
        httpx.get(f"http://127.0.0.1:{gz.media_port}/media/unknown/x.iso", timeout=5)
    assert (gz.home / "tls" / "media.key").stat().st_mode & 0o777 == 0o600
