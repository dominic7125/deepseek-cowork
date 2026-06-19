from __future__ import annotations

import importlib.util
from pathlib import Path
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
    spec.loader.exec_module(module)
    return module


def valid_request():
    return {
        "protocol_version": "1.0",
        "task": {
            "summary": "Implement cowork protocol validation",
            "acceptance_criteria": [
                "Protocol request accepts valid input",
                "Protocol response validates exact fields",
            ],
        },
        "mode": "implementation",
        "complexity": "standard",
        "revision_round": 0,
        "authorized_files": {
            "modify": ["skill/scripts/deepseek_cowork.py"],
            "create": ["skill/references/protocol.md"],
        },
        "files": [
            {
                "path": "skill/scripts/deepseek_cowork.py",
                "content": "print('hello')\n",
            }
        ],
        "project_rules": [
            "Use only stdlib",
            "Keep protocol version fixed at 1.0",
        ],
        "verification_commands": ["python -m unittest tests.test_protocol -v"],
        "review_feedback": [],
        "verification_failure": None,
    }


def valid_patch_response():
    return {
        "protocol_version": "1.0",
        "status": "patch",
        "summary": "Implemented change",
        "changed_files": ["skill/scripts/deepseek_cowork.py"],
        "patch": "--- a/skill/scripts/deepseek_cowork.py\n+++ b/skill/scripts/deepseek_cowork.py\n@@ -1 +1 @@\n-print('hello')\n+print('world')\n",
        "assumptions": [],
        "verification_notes": [],
    }


class ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dc = load_module()

    def test_valid_request_is_accepted(self):
        self.dc.validate_request(valid_request())

    def test_revision_round_above_three_is_rejected(self):
        request = valid_request()
        request["revision_round"] = 4
        with self.assertRaisesRegex(self.dc.ProtocolError, "revision_round"):
            self.dc.validate_request(request)

    def test_implementation_mode_requires_revision_round_zero(self):
        request = valid_request()
        request["revision_round"] = 1
        with self.assertRaisesRegex(self.dc.ProtocolError, "implementation"):
            self.dc.validate_request(request)

    def test_revision_mode_requires_revision_round_above_zero(self):
        request = valid_request()
        request["mode"] = "revision"
        with self.assertRaisesRegex(self.dc.ProtocolError, "revision"):
            self.dc.validate_request(request)

    def test_request_with_extra_field_is_rejected(self):
        request = valid_request()
        request["unexpected"] = True
        with self.assertRaisesRegex(self.dc.ProtocolError, "fields"):
            self.dc.validate_request(request)

    def test_patch_response_is_accepted(self):
        self.dc.validate_response(valid_patch_response())

    def test_blocked_response_must_not_contain_patch(self):
        response = {
            "protocol_version": "1.0",
            "status": "blocked",
            "summary": "Need context",
            "missing_context": ["skill/scripts/deepseek_cowork.py"],
            "patch": "unexpected",
        }
        with self.assertRaisesRegex(self.dc.ProtocolError, "blocked"):
            self.dc.validate_response(response)

    def test_blocked_response_requires_exact_fields(self):
        response = {
            "protocol_version": "1.0",
            "status": "blocked",
            "summary": "Need context",
            "missing_context": ["skill/scripts/deepseek_cowork.py"],
            "changed_files": [],
        }
        with self.assertRaisesRegex(self.dc.ProtocolError, "blocked"):
            self.dc.validate_response(response)


if __name__ == "__main__":
    unittest.main()

