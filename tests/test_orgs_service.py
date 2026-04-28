import unittest
import uuid
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.orgs import (
    accept_invite,
    add_member,
    create_invite,
    create_org,
    delete_org,
    get_org,
    get_user_orgs,
    list_members,
    require_org_membership,
)


class TestOrgService(unittest.TestCase):
    def _new_org_name(self, suffix: str) -> str:
        return f"org-{suffix}-{uuid.uuid4().hex[:8]}"

    def test_create_org_persists_and_enforces_membership_roles(self):
        owner = f"owner-{uuid.uuid4().hex[:6]}"
        viewer = f"viewer-{uuid.uuid4().hex[:6]}"
        org = create_org(self._new_org_name("roles"), owner, plan="free")

        try:
            self.assertTrue(org.get("id"))
            self.assertEqual(org.get("owner"), owner)
            self.assertIsNotNone(get_org(org["id"]))

            add_member(org["id"], viewer, role="viewer")
            members = list_members(org["id"])
            usernames = {m.get("username") for m in members}
            self.assertIn(owner, usernames)
            self.assertIn(viewer, usernames)

            user_orgs = get_user_orgs(owner)
            self.assertTrue(any(o.get("org_id") == org["id"] for o in user_orgs))

            require_org_membership(org["id"], viewer, min_role="viewer")
            with self.assertRaises(PermissionError):
                require_org_membership(org["id"], viewer, min_role="editor")
            require_org_membership(org["id"], owner, min_role="admin")
        finally:
            delete_org(org["id"])

    def test_invite_accept_flow_is_single_use(self):
        owner = f"owner-{uuid.uuid4().hex[:6]}"
        invited_user = f"member-{uuid.uuid4().hex[:6]}"
        org = create_org(self._new_org_name("invite"), owner, plan="free")

        try:
            invite = create_invite(org["id"], invited_by=owner, email="test@example.com", role="editor")
            self.assertTrue(invite.get("token"))

            accepted = accept_invite(invite["token"], invited_user)
            self.assertEqual(accepted.get("status"), "accepted")
            self.assertEqual(accepted.get("role"), "editor")

            members = list_members(org["id"])
            invited_member = next((m for m in members if m.get("username") == invited_user), None)
            self.assertIsNotNone(invited_member)
            self.assertEqual(invited_member.get("role"), "editor")

            with self.assertRaises(ValueError):
                accept_invite(invite["token"], f"member2-{uuid.uuid4().hex[:6]}")
        finally:
            delete_org(org["id"])


if __name__ == "__main__":
    unittest.main()
