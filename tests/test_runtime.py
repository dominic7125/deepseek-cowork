import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "deepseek_cowork_runtime", ROOT / "skill" / "scripts" / "deepseek_cowork.py"
)
dc = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dc
SPEC.loader.exec_module(dc)


def request():
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


def response(files=None):
    return {
        "protocol_version": "2.0",
        "status": "files",
        "summary": "done",
        "files": files or [{"path": "a.txt", "content": "new\n"}],
        "assumptions": [],
        "verification_notes": [],
    }


def config(retries=0):
    return dc.Config(
        "secret", "https://api.deepseek.com", "fast", "pro", 10, 10, retries, ()
    )


class RuntimeTests(unittest.TestCase):
    def test_all_tasks_use_pro_and_complete_file_protocol(self):
        calls = []

        def sender(url, headers, body, timeout):
            calls.append(body)
            return 200, json.dumps(
                {"choices": [{"message": {"content": json.dumps(response())}}]}
            )

        self.assertEqual(dc.call_deepseek(config(), request(), sender=sender), response())
        self.assertEqual(calls[0]["model"], "pro")
        self.assertEqual(calls[0]["thinking"], {"type": "enabled"})
        self.assertIn('"status":"files"', dc.SYSTEM_PROMPT)
        self.assertNotIn("unified diff", dc.SYSTEM_PROMPT)

    def test_invalid_format_gets_exactly_one_retry(self):
        calls = []

        def sender(url, headers, body, timeout):
            calls.append(json.loads(json.dumps(body)))
            content = {"wrong": True} if len(calls) == 1 else response()
            return 200, json.dumps(
                {"choices": [{"message": {"content": json.dumps(content)}}]}
            )

        self.assertEqual(dc.call_deepseek(config(), request(), sender=sender), response())
        self.assertEqual(len(calls), 2)
        self.assertIn("violated Protocol 2.0", calls[1]["messages"][-1]["content"])

    def test_second_invalid_format_stops(self):
        def sender(*args):
            return 200, json.dumps(
                {"choices": [{"message": {"content": '{"wrong":true}'}}]}
            )

        with self.assertRaisesRegex(dc.ApiError, "twice"):
            dc.call_deepseek(config(), request(), sender=sender)

    def test_writes_authorized_files_and_git_generates_diff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "-C", directory, "init"], check=True, capture_output=True)
            (root / "a.txt").write_text("old\n", encoding="utf-8")
            subprocess.run(["git", "-C", directory, "add", "a.txt"], check=True)
            subprocess.run(
                [
                    "git", "-C", directory, "-c", "user.name=Test",
                    "-c", "user.email=test@example.com", "commit", "-m", "init",
                ],
                check=True,
                capture_output=True,
            )
            changed = dc.write_response_files(
                root,
                request(),
                response(
                    [
                        {"path": "a.txt", "content": "new\n"},
                        {"path": "b.txt", "content": "created\n"},
                    ]
                ),
            )
            diff = dc.generated_diff(root, request(), changed)
            self.assertEqual((root / "a.txt").read_text(), "new\n")
            self.assertEqual((root / "b.txt").read_text(), "created\n")
            self.assertIn("a.txt", diff)
            self.assertIn("b.txt", diff)

    def test_rejects_unauthorized_or_wrong_create_modify_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "-C", directory, "init"], check=True, capture_output=True)
            (root / "a.txt").write_text("old\n")
            with self.assertRaises(dc.PatchError):
                dc.write_response_files(
                    root, request(), response([{"path": "secret.txt", "content": "x"}])
                )
            (root / "b.txt").write_text("exists\n")
            with self.assertRaisesRegex(dc.PatchError, "already exists"):
                dc.write_response_files(
                    root, request(), response([{"path": "b.txt", "content": "x"}])
                )

    def test_workflow_self_repairs_until_verification_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "-C", directory, "init"], check=True, capture_output=True)
            (root / "a.txt").write_text("old\n")
            subprocess.run(["git", "-C", directory, "add", "a.txt"], check=True)
            subprocess.run(
                [
                    "git", "-C", directory, "-c", "user.name=Test",
                    "-c", "user.email=test@example.com", "commit", "-m", "init",
                ],
                check=True,
                capture_output=True,
            )
            request_data = request()
            request_data["authorized_files"]["create"] = []
            request_data["verification_commands"] = [
                "if ((Get-Content -Raw a.txt).Trim() -eq 'good') { exit 0 } else { exit 1 }"
            ]
            request_path = root / "request.json"
            request_path.write_text(json.dumps(request_data), encoding="utf-8")
            replies = [
                response([{"path": "a.txt", "content": "bad\n"}]),
                response([{"path": "a.txt", "content": "good\n"}]),
            ]
            seen_requests = []

            def sender(url, headers, body, timeout):
                seen_requests.append(json.loads(body["messages"][1]["content"]))
                return 200, json.dumps(
                    {"choices": [{"message": {"content": json.dumps(replies.pop(0))}}]}
                )

            code, result = dc.run_workflow(
                root, request_path, sender=sender, config_override=config()
            )
            self.assertEqual(code, 0)
            self.assertEqual(result["deepseek_attempts"], 2)
            self.assertEqual(seen_requests[1]["mode"], "revision")
            self.assertEqual(seen_requests[1]["revision_round"], 1)
            self.assertIsNotNone(seen_requests[1]["verification_failure"])
            self.assertEqual((root / "a.txt").read_text(), "good\n")

    def test_workflow_stops_after_ten_failed_self_repairs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "-C", directory, "init"], check=True, capture_output=True)
            (root / "a.txt").write_text("old\n")
            subprocess.run(["git", "-C", directory, "add", "a.txt"], check=True)
            subprocess.run(
                [
                    "git", "-C", directory, "-c", "user.name=Test",
                    "-c", "user.email=test@example.com", "commit", "-m", "init",
                ],
                check=True,
                capture_output=True,
            )
            request_data = request()
            request_data["authorized_files"]["create"] = []
            request_data["verification_commands"] = ["exit 1"]
            request_path = root / "request.json"
            request_path.write_text(json.dumps(request_data), encoding="utf-8")
            calls = []

            def sender(url, headers, body, timeout):
                calls.append(1)
                return 200, json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        response(
                                            [
                                                {
                                                    "path": "a.txt",
                                                    "content": f"attempt {len(calls)}\n",
                                                }
                                            ]
                                        )
                                    )
                                }
                            }
                        ]
                    }
                )

            code, result = dc.run_workflow(
                root, request_path, sender=sender, config_override=config()
            )
            self.assertEqual(code, 4)
            self.assertEqual(len(calls), 11)
            self.assertEqual(result["deepseek_attempts"], 11)
            self.assertEqual(result["revision_rounds"], 10)


if __name__ == "__main__":
    unittest.main()
