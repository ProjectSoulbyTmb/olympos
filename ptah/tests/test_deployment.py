import unittest

from ptah.deployment import validate_deployment


class TestDeploymentReadiness(unittest.TestCase):
    def test_loopback_http_without_auth_is_allowed(self):
        report = validate_deployment("127.0.0.1")
        self.assertTrue(report["ready"])
        self.assertFalse(report["auth"]["required"])
        self.assertFalse(report["tls"]["supported_by_ptah"])

    def test_non_local_requires_auth_and_external_tls(self):
        report = validate_deployment("0.0.0.0")
        self.assertFalse(report["ready"])
        kinds = {item["kind"] for item in report["errors"]}
        self.assertIn("auth_required", kinds)
        self.assertIn("tls_termination_required", kinds)

    def test_external_tls_declaration_makes_authenticated_bind_ready(self):
        report = validate_deployment("192.0.2.10", token="secret",
                                     tls_terminated=True)
        self.assertTrue(report["ready"])
        self.assertTrue(report["tls"]["termination_declared"])

    def test_insecure_override_is_explicit(self):
        report = validate_deployment("192.0.2.10", token="secret",
                                     allow_insecure=True)
        self.assertTrue(report["ready"])
        self.assertIn("insecure_override",
                      {item["kind"] for item in report["warnings"]})


if __name__ == "__main__":
    unittest.main()
