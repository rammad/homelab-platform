"""Regression coverage for Kubernetes service environment variables."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

class RuntimeTests(unittest.TestCase):
    def check_port(self, override, expected):
        env = dict(os.environ, TIASTUBE_PORT="tcp://10.43.0.100:8765")
        env.pop("TIASTUBE_HTTP_PORT", None)
        if override is not None:
            env["TIASTUBE_HTTP_PORT"] = override
        result = subprocess.run(
            [sys.executable, "-c", "import app; print(app.PORT)"],
            cwd=Path(__file__).parent, env=env,
            capture_output=True, text=True, check=True,
        )
        self.assertEqual(result.stdout.strip(), str(expected))

    def test_service_url_does_not_override_default_listen_port(self):
        self.check_port(None, 8765)

    def test_explicit_http_port_with_service_url_present(self):
        self.check_port("9876", 9876)
