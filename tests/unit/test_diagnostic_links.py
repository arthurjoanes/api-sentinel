import json
import tempfile
import unittest
from pathlib import Path

from alert_receiver.diagnostics import tool_url


class DiagnosticLinks(unittest.TestCase):
    def test_defaults_and_configured_ports_keep_path_and_query(self) -> None:
        self.assertEqual(
            tool_url("grafana", "d/sentinel", "from=now-5m", None),
            "http://localhost:3104/d/sentinel?from=now-5m",
        )
        with tempfile.TemporaryDirectory() as folder:
            configuration = Path(folder) / "links.json"
            configuration.write_text(json.dumps({"grafana": "http://127.0.0.1:45678"}))
            self.assertEqual(
                tool_url("grafana", "d/sentinel", "", configuration),
                "http://127.0.0.1:45678/d/sentinel",
            )

    def test_unavailable_configuration_never_falls_back_to_demo(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            configuration = Path(folder) / "links.json"
            with self.assertRaises(FileNotFoundError):
                tool_url("grafana", "", "", configuration)
            for payload in ({}, [], {"grafana": 12}):
                configuration.write_text(json.dumps(payload))
                with self.assertRaises(ValueError):
                    tool_url("grafana", "", "", configuration)

    def test_untrusted_origin_and_unknown_tool_are_rejected(self) -> None:
        with self.assertRaises(KeyError):
            tool_url("other", "", "", None)
        invalid = [
            "https://example.com:443",
            "http://127.0.0.1:45678@evil.invalid:80",
            "http://localhost",
            "http://localhost:70000",
            "javascript:alert(1)",
            "http://localhost:45678/path",
            "http://localhost:45678?target=evil",
            "http://localhost:45678#x",
            "http://user:password@localhost:45678",
        ]
        with tempfile.TemporaryDirectory() as folder:
            configuration = Path(folder) / "links.json"
            for value in invalid:
                with self.subTest(value=value):
                    configuration.write_text(json.dumps({"grafana": value}))
                    with self.assertRaises(ValueError):
                        tool_url("grafana", "", "", configuration)


if __name__ == "__main__":
    unittest.main()
