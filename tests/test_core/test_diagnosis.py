"""Failure classification — what the tool tells a person to go and look at.

The distinction these tests protect came out of a live run: a reused session
had been ended by the server for inactivity, AWT called it
"wrong credentials or expired session", and the account details were searched
through for a long time over a problem that was never there.
"""

from __future__ import annotations

import pytest

from aat.core.diagnosis import _INVESTIGATION_CHECKLISTS, classify_failure


class TestSessionExpiryIsNotAnAuthError:
    """A dead session and a rejected password send people to different places."""

    @pytest.mark.parametrize(
        "message",
        [
            "saved session 'haneul' is too old: saved 40 minutes ago, max_age_min=15",
            "the session expired",
            "session is no longer accepted by the server",
        ],
    )
    def test_session_messages_classify_as_session_expired(self, message: str) -> None:
        assert classify_failure(message) == "session_expired"

    @pytest.mark.parametrize(
        "message",
        [
            "401 Unauthorized",
            "auth rejected: password incorrect",
            "403 Forbidden",
        ],
    )
    def test_credential_messages_still_classify_as_auth_error(self, message: str) -> None:
        assert classify_failure(message) == "auth_error"

    def test_the_two_checklists_do_not_say_the_same_thing(self) -> None:
        session = " ".join(_INVESTIGATION_CHECKLISTS["session_expired"]).lower()
        auth = " ".join(_INVESTIGATION_CHECKLISTS["auth_error"]).lower()

        assert "credentials are not in question" in session
        assert "saved session" in session
        assert session != auth
