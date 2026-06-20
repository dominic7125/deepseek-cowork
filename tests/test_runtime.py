import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / "skill" / "scripts" / "deepseek_cowork.py"
SPEC = importlib.util.spec_from_file_location("deepseek_cowork", SCRIPT)
dc = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dc
SPEC.loader.exec_module(dc)


def request():
    return {
        "protocol_version": "1.0",
        "task": {"summary": "change", "acceptance_criteria": ["works"]},
        "mode": "implementation",
        "complexity": "standard",
        "revision_round": 0,
        "authorized_files": {"modify": ["a.txt"], "create": []},
        "files": [{"path": "a.txt", "content": "old\n"}],
        "project_rules": [],
        "verification_commands": [],
        "review_feedback": [],
        "verification_failure": None,
    }


class RuntimeTests(unittest.TestCase):
    def test_system_prompt_contains_exact_response_shapes(self):
        self.assertIn('"protocol_version":"1.0"', dc.SYSTEM_PROMPT)
        self.assertIn('"status":"patch"', dc.SYSTEM_PROMPT)
        self.assertIn('"status":"blocked"', dc.SYSTEM_PROMPT)
        self.assertIn("Do not echo request fields", dc.SYSTEM_PROMPT)

    def test_routes_all_tasks_to_reasoning_model_and_parses_json(self):
        response = {
            "protocol_version": "1.0",
            "status": "patch",
            "summary": "done",
            "changed_files": ["a.txt"],
            "patch": "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n",
            "assumptions": [],
            "verification_notes": [],
        }
        calls = []

        def sender(url, headers, body, timeout):
            calls.append((url, headers, body, timeout))
            return 200, json.dumps(
                {"choices": [{"message": {"content": json.dumps(response)}}]}
            )

        config = dc.Config("secret", "https://api.deepseek.com", "fast", "pro", 3, 10, 0, ())
        self.assertEqual(dc.call_deepseek(config, request(), sender=sender), response)
        self.assertEqual(calls[0][2]["model"], "pro")
        self.assertEqual(calls[0][2]["thinking"], {"type": "enabled"})

    def test_rejects_delete_and_unauthorized_patch(self):
        response = {
            "changed_files": ["secret.txt"],
            "patch": "diff --git a/secret.txt b/secret.txt\n--- a/secret.txt\n+++ b/secret.txt\n",
        }
        with self.assertRaises(dc.PatchError):
            dc.validate_patch(request(), response)
        response["patch"] = "diff --git a/a.txt b/a.txt\ndeleted file mode 100644\n"
        response["changed_files"] = ["a.txt"]
        with self.assertRaises(dc.PatchError):
            dc.validate_patch(request(), response)

    def test_retries_temporary_api_error(self):
        attempts = []
        response = {
            "protocol_version": "1.0",
            "status": "blocked",
            "summary": "need context",
            "missing_context": ["b.txt"],
        }

        def sender(*args):
            attempts.append(1)
            if len(attempts) == 1:
                return 429, "{}"
            return 200, json.dumps(
                {"choices": [{"message": {"content": json.dumps(response)}}]}
            )

        config = dc.Config("secret", "https://api.deepseek.com", "fast", "pro", 3, 10, 1, ())
        self.assertEqual(
            dc.call_deepseek(config, request(), sender=sender, sleep=lambda _: None),
            response,
        )
        self.assertEqual(len(attempts), 2)

    def test_normalize_patch_removes_model_generated_blob_hashes(self):
        patch = (
            "diff --git a/hello.py b/hello.py\n"
            "new file mode 100644\n"
            "index 0000000..e69de29\n"
            "--- /dev/null\n"
            "+++ b/hello.py\n"
        )
        normalized = dc._normalize_patch(patch)
        self.assertNotIn("index 0000000..e69de29", normalized)
        self.assertIn("new file mode 100644", normalized)
        self.assertTrue(normalized.endswith("\n"))

    def test_apply_new_file_with_bad_blob_hash_on_windows(self):
        patch = (
            "diff --git a/hello.py b/hello.py\n"
            "new file mode 100644\n"
            "index 0000000..e69de29\n"
            "--- /dev/null\n"
            "+++ b/hello.py\n"
            "@@ -0,0 +1 @@\n"
            '+print("Hello, World!")\n'
        )
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(["git", "-C", directory, "init"], check=True, capture_output=True)
            dc.apply_patch(directory, patch)
            self.assertEqual(
                (Path(directory) / "hello.py").read_text(encoding="utf-8"),
                'print("Hello, World!")\n',
            )


if __name__ == "__main__":
    unittest.main()
