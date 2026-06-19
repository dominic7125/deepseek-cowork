from __future__ import annotations

import importlib.util
import json
import math
import sys
import tempfile
import re
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "skill"
    / "scripts"
    / "deepseek_cowork.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("deepseek_cowork", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_config(directory: Path, **overrides) -> Path:
    data = {
        "api_key": "sk-test-secret",
        "base_url": "https://api.deepseek.com/",
        "fast_model": "deepseek-v4-flash",
        "reasoning_model": "deepseek-v4-pro",
        "max_revision_rounds": 3,
        "timeout_seconds": 180,
        "transient_retries": 2,
        "verification_commands": ["python -m unittest tests.test_protocol -v"],
    }
    data.update(overrides)
    content = "\n".join(
        [
            f'api_key = {json.dumps(data["api_key"])}',
            f'base_url = {json.dumps(data["base_url"])}',
            "",
            "[models]",
            f'fast = {json.dumps(data["fast_model"])}',
            f'reasoning = {json.dumps(data["reasoning_model"])}',
            "",
            "[runtime]",
            f'max_revision_rounds = {data["max_revision_rounds"]}',
            f'timeout_seconds = {data["timeout_seconds"]}',
            f'transient_retries = {data["transient_retries"]}',
            "",
            "[verification]",
            f'commands = {json.dumps(data["verification_commands"])}',
            "",
        ]
    )
    path = directory / "config.toml"
    path.write_text(content, encoding="utf-8")
    return path


def write_raw_config(directory: Path, content: str) -> Path:
    path = directory / "config.toml"
    path.write_text(content, encoding="utf-8")
    return path


class ConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dc = load_module()

    def test_valid_config_loads_immutable_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_config(Path(tmp))
            config = self.dc.load_config(path)

        self.assertEqual(config.api_key, "sk-test-secret")
        self.assertEqual(config.base_url, "https://api.deepseek.com")
        self.assertEqual(config.fast_model, "deepseek-v4-flash")
        self.assertEqual(config.reasoning_model, "deepseek-v4-pro")
        self.assertEqual(config.max_revision_rounds, 3)
        self.assertEqual(config.timeout_seconds, 180)
        self.assertEqual(config.transient_retries, 2)
        self.assertEqual(config.verification_commands, ("python -m unittest tests.test_protocol -v",))
        self.assertNotIn("sk-test-secret", repr(config))
        with self.assertRaises(FrozenInstanceError):
            config.base_url = "https://example.com"

    def test_missing_config_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.toml"
            with self.assertRaisesRegex(self.dc.ConfigError, re.escape(str(path))):
                self.dc.load_config(path)

    def test_directory_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            with self.assertRaisesRegex(self.dc.ConfigError, re.escape(str(path))):
                self.dc.load_config(path)

    def test_malformed_toml_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_raw_config(Path(tmp), "api_key = 'sk-test-secret'\n[models\n")
            with self.assertRaisesRegex(self.dc.ConfigError, "configuration file"):
                self.dc.load_config(path)

    def test_permission_error_is_wrapped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_config(Path(tmp))
            with patch.object(self.dc.Path, "open", side_effect=PermissionError("denied")):
                with self.assertRaisesRegex(self.dc.ConfigError, re.escape(str(path))):
                    self.dc.load_config(path)

    def test_missing_api_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_raw_config(
                Path(tmp),
                """
base_url = "https://api.deepseek.com"

[models]
fast = "deepseek-v4-flash"
reasoning = "deepseek-v4-pro"

[runtime]
max_revision_rounds = 3
timeout_seconds = 180
transient_retries = 2

[verification]
commands = ["python -m unittest tests.test_protocol -v"]
""".strip(),
            )
            with self.assertRaisesRegex(self.dc.ConfigError, "api_key"):
                self.dc.load_config(path)

    def test_invalid_https_base_url_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_config(Path(tmp), base_url="http://api.deepseek.com")
            with self.assertRaisesRegex(self.dc.ConfigError, "HTTPS"):
                self.dc.load_config(path)

    def test_base_url_with_prefix_path_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_config(Path(tmp), base_url="https://api.deepseek.com/v1/")
            config = self.dc.load_config(path)

        self.assertEqual(config.base_url, "https://api.deepseek.com/v1")

    def test_base_url_rejects_missing_hostname(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_config(Path(tmp), base_url="https://:443")
            with self.assertRaisesRegex(self.dc.ConfigError, "base_url"):
                self.dc.load_config(path)

    def test_base_url_rejects_bad_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_config(Path(tmp), base_url="https://api.deepseek.com:abc")
            with self.assertRaisesRegex(self.dc.ConfigError, "base_url"):
                self.dc.load_config(path)

    def test_base_url_rejects_malformed_ipv6_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_config(Path(tmp), base_url="https://[::1")
            with self.assertRaisesRegex(self.dc.ConfigError, "base_url"):
                self.dc.load_config(path)

    def test_base_url_rejects_credentials_query_fragment_and_whitespace(self):
        cases = [
            "https://user:pass@api.deepseek.com",
            "https://api.deepseek.com?x=1",
            "https://api.deepseek.com#frag",
            " https://api.deepseek.com",
            "https://api.deepseek.com ",
            "https://api.deepseek.com/v 1",
        ]
        for base_url in cases:
            with self.subTest(base_url=base_url):
                with tempfile.TemporaryDirectory() as tmp:
                    path = write_config(Path(tmp), base_url=base_url)
                    with self.assertRaisesRegex(self.dc.ConfigError, "base_url"):
                        self.dc.load_config(path)

    def test_unknown_top_level_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_raw_config(
                Path(tmp),
                """
api_key = "sk-test-secret"
base_url = "https://api.deepseek.com"
extra = true

[models]
fast = "deepseek-v4-flash"
reasoning = "deepseek-v4-pro"

[runtime]
max_revision_rounds = 3
timeout_seconds = 180
transient_retries = 2

[verification]
commands = ["python -m unittest tests.test_protocol -v"]
""".strip(),
            )
            with self.assertRaisesRegex(self.dc.ConfigError, "config"):
                self.dc.load_config(path)

    def test_unknown_nested_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_raw_config(
                Path(tmp),
                """
api_key = "sk-test-secret"
base_url = "https://api.deepseek.com"

[models]
fast = "deepseek-v4-flash"
reasoning = "deepseek-v4-pro"
extra = "unexpected"

[runtime]
max_revision_rounds = 3
timeout_seconds = 180
transient_retries = 2

[verification]
commands = ["python -m unittest tests.test_protocol -v"]
""".strip(),
            )
            with self.assertRaisesRegex(self.dc.ConfigError, "models"):
                self.dc.load_config(path)

    def test_invalid_revision_rounds_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_config(Path(tmp), max_revision_rounds=2)
            with self.assertRaisesRegex(self.dc.ConfigError, "max_revision_rounds"):
                self.dc.load_config(path)

    def test_invalid_timeout_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_config(Path(tmp), timeout_seconds=0)
            with self.assertRaisesRegex(self.dc.ConfigError, "timeout_seconds"):
                self.dc.load_config(path)

    def test_nonfinite_timeout_is_rejected(self):
        for timeout in (math.nan, math.inf, -math.inf):
            with self.subTest(timeout=timeout):
                with tempfile.TemporaryDirectory() as tmp:
                    path = write_config(Path(tmp), timeout_seconds=timeout)
                    with self.assertRaisesRegex(self.dc.ConfigError, "timeout_seconds"):
                        self.dc.load_config(path)

    def test_invalid_transient_retries_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_config(Path(tmp), transient_retries=-1)
            with self.assertRaisesRegex(self.dc.ConfigError, "transient_retries"):
                self.dc.load_config(path)

    def test_verification_command_must_be_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_config(Path(tmp), verification_commands=[123])
            with self.assertRaisesRegex(self.dc.ConfigError, "verification"):
                self.dc.load_config(path)

    def test_verification_command_must_be_nonempty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_config(Path(tmp), verification_commands=[""])
            with self.assertRaisesRegex(self.dc.ConfigError, "verification"):
                self.dc.load_config(path)

    def test_default_config_location_uses_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            config_path = home / ".codex" / "deepseek-cowork" / "config.toml"
            config_path.parent.mkdir(parents=True)
            write_config(config_path.parent)
            with patch.object(self.dc.Path, "home", return_value=home):
                self.assertEqual(
                    self.dc.default_config_path(),
                    config_path,
                )
                config = self.dc.load_config()

        self.assertEqual(config.api_key, "sk-test-secret")
        self.assertEqual(config.base_url, "https://api.deepseek.com")

    def test_error_messages_do_not_leak_api_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_config(Path(tmp), timeout_seconds=0)
            with self.assertRaises(self.dc.ConfigError) as cm:
                self.dc.load_config(path)

        self.assertNotIn("sk-test-secret", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
