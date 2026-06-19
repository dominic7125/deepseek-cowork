from __future__ import annotations

import importlib.util
import json
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


def load_json_schema(relative_path: str):
    return json.loads((Path(__file__).resolve().parents[1] / relative_path).read_text(encoding="utf-8"))


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

    def test_request_schema_encodes_round_semantics(self):
        schema = load_json_schema("skill/references/request.schema.json")
        self.assertIn("allOf", schema)
        self.assertGreaterEqual(len(schema["allOf"]), 2)

        implementation_rule = next(
            rule
            for rule in schema["allOf"]
            if rule["if"]["properties"]["mode"]["const"] == "implementation"
        )
        revision_rule = next(
            rule
            for rule in schema["allOf"]
            if rule["if"]["properties"]["mode"]["const"] == "revision"
        )

        self.assertEqual(
            implementation_rule["then"]["properties"]["revision_round"]["const"],
            0,
        )
        self.assertEqual(
            revision_rule["then"]["properties"]["revision_round"]["minimum"],
            1,
        )
        self.assertEqual(
            revision_rule["then"]["properties"]["revision_round"]["maximum"],
            3,
        )

    def test_response_schema_uses_exact_status_specific_fields(self):
        schema = load_json_schema("skill/references/response.schema.json")
        self.assertEqual(len(schema["oneOf"]), 2)

        patch_rule = next(rule for rule in schema["oneOf"] if rule["properties"]["status"]["const"] == "patch")
        blocked_rule = next(rule for rule in schema["oneOf"] if rule["properties"]["status"]["const"] == "blocked")

        self.assertFalse(patch_rule["additionalProperties"])
        self.assertFalse(blocked_rule["additionalProperties"])
        self.assertEqual(
            set(patch_rule["required"]),
            {
                "protocol_version",
                "status",
                "summary",
                "changed_files",
                "patch",
                "assumptions",
                "verification_notes",
            },
        )
        self.assertEqual(
            set(blocked_rule["required"]),
            {"protocol_version", "status", "summary", "missing_context"},
        )
        self.assertNotIn("missing_context", patch_rule["properties"])
        self.assertNotIn("patch", blocked_rule["properties"])
        self.assertNotIn("changed_files", blocked_rule["properties"])

    def test_duplicate_non_path_string_arrays_are_allowed(self):
        request = valid_request()
        request["task"]["acceptance_criteria"] = ["same", "same"]
        request["project_rules"] = ["same", "same"]
        request["verification_commands"] = ["same", "same"]
        self.dc.validate_request(request)

    def test_duplicate_response_string_arrays_are_allowed(self):
        response = valid_patch_response()
        response["assumptions"] = ["same", "same"]
        response["verification_notes"] = ["same", "same"]
        self.dc.validate_response(response)

    def test_protocol_document_lists_nested_constraints(self):
        protocol = (Path(__file__).resolve().parents[1] / "skill" / "references" / "protocol.md").read_text(
            encoding="utf-8"
        )
        for phrase in [
            "task contains exactly `summary` and `acceptance_criteria`",
            "files is an array of `{ \"path\", \"content\" }` objects with unique paths",
            "review_feedback items must contain `severity`, `file`, `problem`, and `required_change`",
            "review_feedback items may include `line`",
            "verification_failure is either `null` or an object with `command`, `exit_code`, and `summary`",
            "Patch responses contain exactly `changed_files`, `patch`, `assumptions`, and `verification_notes`",
            "Blocked responses contain exactly `missing_context`",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, protocol)


if __name__ == "__main__":
    unittest.main()
