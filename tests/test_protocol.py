from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "deepseek_cowork_protocol", ROOT / "skill" / "scripts" / "deepseek_cowork.py"
)
dc = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dc
SPEC.loader.exec_module(dc)


def valid_request():
    return {
        "protocol_version": "2.0",
        "task": {"summary": "change", "acceptance_criteria": ["works"]},
        "mode": "implementation",
        "complexity": "standard",
        "revision_round": 0,
        "authorized_files": {"modify": ["a.txt"], "create": ["b.txt"]},
        "files": [{"path": "a.txt", "content": "old\n"}],
        "project_rules": [],
        "verification_commands": [],
        "review_feedback": [],
        "verification_failure": None,
    }


def valid_files_response():
    return {
        "protocol_version": "2.0",
        "status": "files",
        "summary": "done",
        "files": [{"path": "a.txt", "content": "new\n"}],
        "assumptions": [],
        "verification_notes": [],
    }


class ProtocolTests(unittest.TestCase):
    def test_valid_request_and_files_response(self):
        dc.validate_request(valid_request())
        dc.validate_response(valid_files_response())

    def test_old_protocol_and_patch_response_are_rejected(self):
        request = valid_request()
        request["protocol_version"] = "1.0"
        with self.assertRaises(dc.ProtocolError):
            dc.validate_request(request)
        response = valid_files_response()
        response.update({"status": "patch", "changed_files": ["a.txt"], "patch": "x"})
        response.pop("files")
        with self.assertRaises(dc.ProtocolError):
            dc.validate_response(response)

    def test_duplicate_or_unsafe_response_paths_are_rejected(self):
        response = valid_files_response()
        response["files"].append({"path": "a.txt", "content": "again"})
        with self.assertRaisesRegex(dc.ProtocolError, "duplicate"):
            dc.validate_response(response)
        response = valid_files_response()
        response["files"][0]["path"] = "../outside"
        with self.assertRaises(dc.ProtocolError):
            dc.validate_response(response)

    def test_blocked_shape_is_exact(self):
        dc.validate_response(
            {
                "protocol_version": "2.0",
                "status": "blocked",
                "summary": "need context",
                "missing_context": ["model.py"],
            }
        )

    def test_schemas_are_protocol_2_files_based(self):
        request_schema = json.loads(
            (ROOT / "skill" / "references" / "request.schema.json").read_text()
        )
        response_schema = json.loads(
            (ROOT / "skill" / "references" / "response.schema.json").read_text()
        )
        self.assertEqual(
            request_schema["properties"]["protocol_version"]["const"], "2.0"
        )
        files_rule = next(
            rule
            for rule in response_schema["oneOf"]
            if rule["properties"]["status"]["const"] == "files"
        )
        self.assertIn("files", files_rule["required"])
        self.assertNotIn("patch", files_rule["properties"])

    def test_revision_round_allows_up_to_ten(self):
        value = valid_request()
        value["mode"] = "revision"
        value["revision_round"] = 10
        dc.validate_request(value)
        value["revision_round"] = 11
        with self.assertRaises(dc.ProtocolError):
            dc.validate_request(value)


if __name__ == "__main__":
    unittest.main()
