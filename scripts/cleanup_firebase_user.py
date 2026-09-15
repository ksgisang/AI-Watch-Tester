#!/usr/bin/env python3
"""Delete a Firebase Auth user by email.

Usage:
    python scripts/cleanup_firebase_user.py test+1234567890@ailooplab.com

Requirements (one of):
  A) GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
     pip install firebase-admin

  B) FIREBASE_API_KEY=<web-api-key>  (uses REST API — limited to sign-in/delete own account)

If neither is available the script exits 0 (no-op) so teardown is swallowed.
"""

from __future__ import annotations

import os
import sys


def _delete_via_admin_sdk(email: str) -> None:
    import firebase_admin  # type: ignore[import-untyped]
    from firebase_admin import auth, credentials  # type: ignore[import-untyped]

    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    project_id = os.environ.get("FIREBASE_PROJECT_ID", "clasring-dev")

    if not firebase_admin._apps:
        if cred_path and os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
        else:
            cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred, {"projectId": project_id})

    user = auth.get_user_by_email(email)
    auth.delete_user(user.uid)
    print(f"[cleanup] Deleted Firebase user: {email} (uid={user.uid})")


def _delete_via_rest_api(email: str) -> None:
    """Requires FIREBASE_ADMIN_TOKEN (OAuth2 token with Firebase Admin scope)."""
    import json
    import urllib.request

    token = os.environ["FIREBASE_ADMIN_TOKEN"]
    project_id = os.environ.get("FIREBASE_PROJECT_ID", "clasring-dev")

    # Look up UID first
    lookup_url = (
        f"https://identitytoolkit.googleapis.com/v1/projects/{project_id}"
        f"/accounts:lookup"
    )
    payload = json.dumps({"email": [email]}).encode()
    req = urllib.request.Request(
        lookup_url,
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())

    users = data.get("users", [])
    if not users:
        print(f"[cleanup] User not found (already deleted?): {email}")
        return

    uid = users[0]["localId"]

    # Delete
    delete_url = (
        f"https://identitytoolkit.googleapis.com/v1/projects/{project_id}"
        f"/accounts/{uid}"
    )
    req2 = urllib.request.Request(
        delete_url,
        method="DELETE",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req2):
        pass

    print(f"[cleanup] Deleted Firebase user via REST: {email} (uid={uid})")


def main() -> int:
    if len(sys.argv) < 2:
        print("[cleanup] Usage: cleanup_firebase_user.py <email>", file=sys.stderr)
        return 1

    email = sys.argv[1]
    print(f"[cleanup] Attempting to delete Firebase user: {email}")

    # Try Admin SDK first
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get(
        "FIREBASE_CREDENTIALS"
    ):
        try:
            import firebase_admin  # noqa: F401
            _delete_via_admin_sdk(email)
            return 0
        except ImportError:
            print("[cleanup] firebase-admin not installed, trying REST API...")
        except Exception as exc:
            print(f"[cleanup] Admin SDK error: {exc}", file=sys.stderr)
            return 1

    # Try REST API
    if os.environ.get("FIREBASE_ADMIN_TOKEN"):
        try:
            _delete_via_rest_api(email)
            return 0
        except Exception as exc:
            print(f"[cleanup] REST API error: {exc}", file=sys.stderr)
            return 1

    # No credentials → skip silently (teardown will swallow anyway)
    print(
        "[cleanup] No Firebase credentials configured "
        "(GOOGLE_APPLICATION_CREDENTIALS or FIREBASE_ADMIN_TOKEN). "
        "Skipping deletion — user left in Firebase."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
