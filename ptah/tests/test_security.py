import unittest

from ptah.security import (DESTRUCTIVE, DENIED, ELEVATED, SAFE, GRANT_CLASS,
                           ConfirmationPolicy, POLICY_AUTO,
                           POLICY_CONFIRM_ALL, RiskAnalyzer)

ANALYZER = RiskAnalyzer()


def verdict(tool, args):
    return ANALYZER.classify(tool, args)


class TestRiskClassification(unittest.TestCase):
    def test_safe_default(self):
        v = verdict("terminal", {"command": "echo hello"})
        self.assertEqual(v.risk, SAFE)
        self.assertTrue(v.allowed)
        self.assertFalse(v.needs_confirmation)

    def test_deny_root_rm(self):
        v = verdict("terminal", {"command": "rm -rf /"})
        self.assertEqual(v.risk, DENIED)
        self.assertFalse(v.allowed)
        self.assertEqual(GRANT_CLASS[DENIED], "DENY")

    def test_deny_forkbomb_and_mkfs(self):
        for cmd in (":(){ :|:& };:", "mkfs.ext4 /dev/sda1",
                    "shutdown /s /t 0", "reg delete HKLM\\SOFTWARE"):
            with self.subTest(cmd=cmd):
                self.assertEqual(verdict("terminal",
                                         {"command": cmd}).risk, DENIED)

    def test_deny_survives_confirmation_flag_semantics(self):
        v = verdict("terminal", {"command": "format C:"})
        self.assertFalse(v.allowed)

    def test_destructive_recursive_delete(self):
        for cmd in ("rm -rf build/", "del /s /q *.tmp", "rmdir /s folder",
                    "git reset --hard HEAD~3", "git push --force origin main",
                    "DROP TABLE users"):
            with self.subTest(cmd=cmd):
                self.assertEqual(verdict("terminal",
                                         {"command": cmd}).risk, DESTRUCTIVE)

    def test_elevated_network_and_installs(self):
        for cmd in ("curl https://example.com", "pip install requests",
                    "npm install left-pad", "git clone https://x/y"):
            with self.subTest(cmd=cmd):
                self.assertEqual(verdict("terminal",
                                         {"command": cmd}).risk, ELEVATED)

    def test_grant_ladder_mapping(self):
        self.assertEqual(GRANT_CLASS[SAFE], "L0")
        self.assertEqual(GRANT_CLASS[ELEVATED], "L1")
        self.assertEqual(GRANT_CLASS[DESTRUCTIVE], "L2")

    def test_case_insensitive(self):
        self.assertEqual(verdict("terminal",
                                 {"command": "RM -RF /"}).risk, DENIED)


class TestConfirmationPolicy(unittest.TestCase):
    def test_every_policy_gates_destructive(self):
        for name in (POLICY_AUTO, "confirm-risky", POLICY_CONFIRM_ALL):
            policy = ConfirmationPolicy(name)
            v = verdict("terminal", {"command": "rm -rf build/"})
            self.assertTrue(policy.apply(v), name)

    def test_auto_runs_elevated(self):
        policy = ConfirmationPolicy(POLICY_AUTO)
        v = verdict("terminal", {"command": "curl example.com"})
        self.assertFalse(policy.apply(v))

    def test_confirm_all_gates_elevated(self):
        policy = ConfirmationPolicy(POLICY_CONFIRM_ALL)
        v = verdict("terminal", {"command": "curl example.com"})
        self.assertTrue(policy.apply(v))

    def test_denied_never_passes_any_policy(self):
        for name in (POLICY_AUTO, "confirm-risky", POLICY_CONFIRM_ALL):
            policy = ConfirmationPolicy(name)
            v = verdict("terminal", {"command": "mkfs /dev/sda"})
            self.assertFalse(policy.apply(v), name)

    def test_unknown_policy_rejected(self):
        with self.assertRaises(ValueError):
            ConfirmationPolicy("yolo")


if __name__ == "__main__":
    unittest.main()
