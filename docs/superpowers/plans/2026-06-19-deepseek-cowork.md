# DeepSeek Cowork Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and install a global Codex Skill that delegates bounded implementation work to DeepSeek, safely applies its patch, runs verification, and returns structured evidence for Codex review.

**Architecture:** The repository contains the distributable Skill under `skill/`, one standard-library Python orchestration script, versioned protocol documentation and schemas, plus a PowerShell installer. Codex owns planning, context selection, review, and the three-round policy; the script owns configuration, API calls, response validation, patch safety, patch application, and verification execution.

**Tech Stack:** Python 3.11+ standard library (`argparse`, `dataclasses`, `hashlib`, `http.client`, `json`, `pathlib`, `subprocess`, `time`, `tomllib`, `urllib`), PowerShell 5.1+, Git, `unittest`.

---

## File Structure

```text
README.md
install.ps1
skill/
├─ SKILL.md
├─ scripts/
│  └─ deepseek_cowork.py
└─ references/
   ├─ protocol.md
   ├─ request.schema.json
   └─ response.schema.json
tests/
├─ __init__.py
├─ helpers.py
├─ test_api.py
├─ test_config.py
├─ test_patch.py
├─ test_protocol.py
├─ test_run.py
└─ test_verification.py
```

Responsibilities:

- `skill/SKILL.md`: Codex-facing workflow, complexity routing, context minimization, review loop, and takeover rules.
- `skill/scripts/deepseek_cowork.py`: deterministic CLI and all runtime behavior.
- `skill/references/protocol.md`: human-readable protocol contract and examples.
- `skill/references/*.schema.json`: machine-readable request and response contracts.
- `install.ps1`: copies the Skill to the user scope, creates the config template, and protects it with Windows ACLs.
- `tests/helpers.py`: temporary Git repository and fixture builders shared by tests.
- `tests/test_*.py`: focused behavior tests.

### Task 1: Add protocol schemas and protocol validation

**Files:**

- Create: `skill/references/request.schema.json`
- Create: `skill/references/response.schema.json`
- Create: `skill/references/protocol.md`
- Create: `skill/scripts/deepseek_cowork.py`
- Create: `tests/__init__.py`
- Create: `tests/test_protocol.py`

- [ ] **Step 1: Write failing protocol tests**

Create tests that load the script with `importlib.util.spec_from_file_location` and assert:

```python
def test_valid_request_is_accepted():
    dc.validate_request(valid_request())

def test_revision_round_above_three_is_rejected():
    request = valid_request()
    request["revision_round"] = 4
    with self.assertRaisesRegex(dc.ProtocolError, "revision_round"):
        dc.validate_request(request)

def test_blocked_response_must_not_contain_patch():
    response = {
        "protocol_version": "1.0",
        "status": "blocked",
        "summary": "Need context",
        "missing_context": ["src/model.py"],
        "patch": "unexpected",
    }
    with self.assertRaisesRegex(dc.ProtocolError, "blocked"):
        dc.validate_response(response)
```

- [ ] **Step 2: Run the tests and confirm failure**

Run:

```powershell
python -m unittest tests.test_protocol -v
```

Expected: import or attribute failures because the script and validators do not exist.

- [ ] **Step 3: Add the versioned JSON schemas**

Define JSON Schema draft 2020-12 documents with `additionalProperties: false`.

Request requirements:

- `protocol_version` must equal `"1.0"`.
- `mode` is `implementation` or `revision`.
- `complexity` is `standard` or `complex`.
- `revision_round` is integer `0..3`.
- `authorized_files.modify` and `.create` are unique string arrays.
- `files` contains unique path/content objects.
- `review_feedback` contains severity, file, optional line, problem, and required change.
- `verification_failure` is null or contains command, exit code, and summary.

Response requirements:

- `status` is `patch` or `blocked`.
- `patch` requires `changed_files`, `patch`, `assumptions`, and `verification_notes`.
- `blocked` requires `missing_context` and forbids `patch` and `changed_files`.

- [ ] **Step 4: Implement minimal manual validators**

In `deepseek_cowork.py`, add:

```python
PROTOCOL_VERSION = "1.0"

class CoworkError(Exception):
    pass

class ProtocolError(CoworkError):
    pass

def _require_type(value, expected, path):
    if not isinstance(value, expected):
        raise ProtocolError(f"{path} has invalid type")

def validate_request(data):
    _require_type(data, dict, "request")
    required = {
        "protocol_version", "task", "mode", "complexity",
        "revision_round", "authorized_files", "files",
        "project_rules", "verification_commands",
        "review_feedback", "verification_failure",
    }
    if set(data) != required:
        raise ProtocolError("request fields do not match protocol 1.0")
    if data["protocol_version"] != PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol_version")
    if data["mode"] not in {"implementation", "revision"}:
        raise ProtocolError("invalid mode")
    if data["complexity"] not in {"standard", "complex"}:
        raise ProtocolError("invalid complexity")
    if type(data["revision_round"]) is not int or not 0 <= data["revision_round"] <= 3:
        raise ProtocolError("revision_round must be between 0 and 3")
    if data["mode"] == "implementation" and data["revision_round"] != 0:
        raise ProtocolError("implementation must use revision_round 0")
    if data["mode"] == "revision" and data["revision_round"] == 0:
        raise ProtocolError("revision must use revision_round 1..3")
    _require_exact_keys(data["task"], {"summary", "acceptance_criteria"}, "task")
    _require_nonempty_string(data["task"]["summary"], "task.summary")
    _require_string_list(data["task"]["acceptance_criteria"], "task.acceptance_criteria", nonempty=True)
    _require_exact_keys(data["authorized_files"], {"modify", "create"}, "authorized_files")
    modify = _require_path_list(data["authorized_files"]["modify"], "authorized_files.modify")
    create = _require_path_list(data["authorized_files"]["create"], "authorized_files.create")
    if set(modify) & set(create):
        raise ProtocolError("authorized modify/create paths overlap")
    _validate_file_entries(data["files"])
    supplied = {entry["path"] for entry in data["files"]}
    if not supplied.issubset(set(modify)):
        raise ProtocolError("files may contain only authorized existing files")
    _require_string_list(data["project_rules"], "project_rules")
    _require_string_list(data["verification_commands"], "verification_commands")
    _validate_feedback(data["review_feedback"])
    _validate_verification_failure(data["verification_failure"])

def validate_response(data):
    _require_type(data, dict, "response")
    if data.get("protocol_version") != PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol_version")
    status = data.get("status")
    if status == "patch":
        required = {
            "protocol_version", "status", "summary", "changed_files",
            "patch", "assumptions", "verification_notes",
        }
        if set(data) != required or not data["patch"].strip():
            raise ProtocolError("invalid patch response")
    elif status == "blocked":
        required = {
            "protocol_version", "status", "summary", "missing_context",
        }
        if set(data) != required:
            raise ProtocolError("blocked response must not contain patch fields")
    else:
        raise ProtocolError("invalid response status")
```

Implement every nested check represented by the schemas; the runtime must not require the third-party `jsonschema` package.

- [ ] **Step 5: Document the exact protocol**

In `protocol.md`, include request, patch response, blocked response, path rules, round semantics, and compatibility rule: reject unknown protocol versions rather than guessing.

- [ ] **Step 6: Run protocol tests**

Run:

```powershell
python -m unittest tests.test_protocol -v
```

Expected: all protocol tests pass.

- [ ] **Step 7: Commit**

```powershell
git add skill/references skill/scripts/deepseek_cowork.py tests
git commit -m "feat: define cowork protocol"
```

### Task 2: Load and validate global configuration

**Files:**

- Modify: `skill/scripts/deepseek_cowork.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing configuration tests**

Cover a valid TOML file, missing API key, invalid URL, unknown model key, negative timeout, and default config location:

```python
def test_load_config_selects_models(tmp_path):
    path = write_config(tmp_path, api_key="sk-test")
    config = dc.load_config(path)
    self.assertEqual(config.fast_model, "deepseek-v4-flash")
    self.assertEqual(config.reasoning_model, "deepseek-v4-pro")

def test_missing_api_key_is_rejected(tmp_path):
    path = write_raw_config(tmp_path, "base_url='https://api.deepseek.com'")
    with self.assertRaisesRegex(dc.ConfigError, "api_key"):
        dc.load_config(path)
```

- [ ] **Step 2: Confirm failure**

Run:

```powershell
python -m unittest tests.test_config -v
```

Expected: missing `load_config`, `Config`, or `ConfigError`.

- [ ] **Step 3: Implement immutable configuration**

Add:

```python
@dataclass(frozen=True)
class Config:
    api_key: str
    base_url: str
    fast_model: str
    reasoning_model: str
    max_revision_rounds: int
    timeout_seconds: float
    transient_retries: int
    verification_commands: tuple[str, ...]

class ConfigError(CoworkError):
    pass

def default_config_path():
    return Path.home() / ".codex" / "deepseek-cowork" / "config.toml"

def load_config(path=None):
    config_path = Path(path) if path else default_config_path()
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)
    _require_exact_keys(raw, {"api_key", "base_url", "models", "runtime", "verification"}, "config")
    _require_exact_keys(raw["models"], {"fast", "reasoning"}, "models")
    _require_exact_keys(
        raw["runtime"],
        {"max_revision_rounds", "timeout_seconds", "transient_retries"},
        "runtime",
    )
    _require_exact_keys(raw["verification"], {"commands"}, "verification")
    api_key = _config_string(raw["api_key"], "api_key")
    base_url = _https_url(raw["base_url"], "base_url")
    max_rounds = _config_int(raw["runtime"]["max_revision_rounds"], "max_revision_rounds", minimum=0)
    if max_rounds != 3:
        raise ConfigError("protocol 1.0 requires max_revision_rounds = 3")
    return Config(
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        fast_model=_config_string(raw["models"]["fast"], "models.fast"),
        reasoning_model=_config_string(raw["models"]["reasoning"], "models.reasoning"),
        max_revision_rounds=max_rounds,
        timeout_seconds=_config_number(raw["runtime"]["timeout_seconds"], "timeout_seconds", minimum_exclusive=0),
        transient_retries=_config_int(raw["runtime"]["transient_retries"], "transient_retries", minimum=0),
        verification_commands=tuple(
            _config_string(command, "verification.commands[]")
            for command in raw["verification"]["commands"]
        ),
    )
```

Do not print or include `api_key` in exceptions, logs, dataclass representations, or result JSON. Override `Config.__repr__` or mark the key field `repr=False`.

- [ ] **Step 4: Run configuration tests**

Run:

```powershell
python -m unittest tests.test_config -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add skill/scripts/deepseek_cowork.py tests/test_config.py
git commit -m "feat: load cowork configuration"
```

### Task 3: Implement DeepSeek API routing and retries

**Files:**

- Modify: `skill/scripts/deepseek_cowork.py`
- Create: `tests/test_api.py`

- [ ] **Step 1: Write failing API tests**

Inject the HTTP sender and sleep function so tests perform no network calls:

```python
def test_standard_uses_fast_model():
    sender = FakeSender([ok_response(valid_patch_response())])
    result = dc.call_deepseek(config(), valid_request(), sender=sender, sleep=lambda _: None)
    self.assertEqual(sender.requests[0]["json"]["model"], "deepseek-v4-flash")
    self.assertEqual(sender.requests[0]["json"]["thinking"], {"type": "disabled"})
    self.assertEqual(result["status"], "patch")

def test_complex_uses_reasoning_model():
    request = valid_request()
    request["complexity"] = "complex"
    sender = FakeSender([ok_response(valid_patch_response())])
    dc.call_deepseek(config(), request, sender=sender, sleep=lambda _: None)
    body = sender.requests[0]["json"]
    self.assertEqual(body["model"], "deepseek-v4-pro")
    self.assertEqual(body["thinking"], {"type": "enabled"})

def test_429_retries_twice_then_succeeds():
    sender = FakeSender([http_error(429), http_error(503), ok_response(valid_patch_response())])
    dc.call_deepseek(config(transient_retries=2), valid_request(), sender=sender, sleep=lambda _: None)
    self.assertEqual(len(sender.requests), 3)
```

Also cover timeout, invalid JSON, malformed API envelope, HTTP 401 without retry, and redaction of response bodies from auth errors.

- [ ] **Step 2: Confirm failure**

Run:

```powershell
python -m unittest tests.test_api -v
```

Expected: missing API functions and error types.

- [ ] **Step 3: Implement API request construction**

Use `urllib.request` and send:

```python
body = {
    "model": config.reasoning_model if request["complexity"] == "complex" else config.fast_model,
    "messages": [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": json.dumps(request, ensure_ascii=False, separators=(",", ":")),
        },
    ],
    "response_format": {"type": "json_object"},
    "stream": False,
    "thinking": {
        "type": "enabled" if request["complexity"] == "complex" else "disabled"
    },
}
```

`SYSTEM_PROMPT` must state that the model is an implementation worker, has no repository access beyond supplied files, must obey authorized paths, must not delete/move files, and must output exactly one protocol 1.0 JSON object.

Parse `choices[0].message.content` as JSON and pass it to `validate_response`.

- [ ] **Step 4: Implement bounded retries**

Retry only timeout, connection errors, HTTP 429, and HTTP 5xx. Before retry number `attempt`, call `sleep(2 ** attempt)` where the first retry uses `attempt=0`. Raise `ApiError` immediately for HTTP 400/401/402/403/404 and never include the API key or full remote response body in the exception.

- [ ] **Step 5: Run API tests**

Run:

```powershell
python -m unittest tests.test_api -v
```

Expected: all tests pass without internet access.

- [ ] **Step 6: Commit**

```powershell
git add skill/scripts/deepseek_cowork.py tests/test_api.py
git commit -m "feat: call deepseek with model routing"
```

### Task 4: Parse and enforce patch safety

**Files:**

- Modify: `skill/scripts/deepseek_cowork.py`
- Create: `tests/helpers.py`
- Create: `tests/test_patch.py`

- [ ] **Step 1: Write failing patch-policy tests**

Create temporary Git repositories and test:

```python
def test_authorized_modify_is_allowed():
    request = valid_request(modify=["src/app.py"])
    patch = patch_modifying("src/app.py", "old\n", "new\n")
    analysis = dc.analyze_patch(repo, request, patch)
    self.assertEqual(analysis.changed_files, ("src/app.py",))

def test_delete_is_rejected():
    patch = deletion_patch("src/app.py")
    with self.assertRaisesRegex(dc.PatchError, "delete"):
        dc.analyze_patch(repo, request, patch)

def test_path_traversal_is_rejected():
    patch = "--- a/../secret.txt\n+++ b/../secret.txt\n@@ -1 +1 @@\n-a\n+b\n"
    with self.assertRaisesRegex(dc.PatchError, "path"):
        dc.analyze_patch(repo, request, patch)
```

Add separate tests for absolute paths, unauthorized modify/create, rename headers, binary markers, symlink mode `120000`, gitlink mode `160000`, emptying a non-empty file, duplicate path, mismatched `changed_files`, and malformed diff.

- [ ] **Step 2: Confirm failure**

Run:

```powershell
python -m unittest tests.test_patch -v
```

Expected: missing patch analyzer.

- [ ] **Step 3: Implement strict diff parsing**

Add immutable result types:

```python
@dataclass(frozen=True)
class PatchFile:
    old_path: str | None
    new_path: str
    is_new: bool

@dataclass(frozen=True)
class PatchAnalysis:
    files: tuple[PatchFile, ...]
    changed_files: tuple[str, ...]
```

Parse only Git-style unified diffs beginning with `diff --git a/... b/...`. Reject unknown extended headers. Normalize paths with `PurePosixPath`, reject backslashes, drive prefixes, absolute paths, empty components, `"."`, and `".."`.

Resolve every target against `repo_root.resolve()` and verify `target.is_relative_to(repo_root.resolve())`.

Run `git ls-files --stage -- <path>` to reject mode `120000` and `160000`. Reject patch headers containing:

```text
deleted file mode
rename from
rename to
similarity index
Binary files
GIT binary patch
old mode 120000
new mode 120000
old mode 160000
new mode 160000
```

Require modified paths in `authorized_files.modify`, new paths in `authorized_files.create`, and exact equality between parsed paths and response `changed_files`.

- [ ] **Step 4: Detect empty-file deletion bypass**

After applying to a temporary index/worktree check or by parsing resulting hunks, reject a patch whose resulting content for an existing non-empty file is zero bytes. Tests must cover both full-line deletion and replacement with no newline.

- [ ] **Step 5: Run patch tests**

Run:

```powershell
python -m unittest tests.test_patch -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add skill/scripts/deepseek_cowork.py tests/helpers.py tests/test_patch.py
git commit -m "feat: enforce patch safety policy"
```

### Task 5: Apply patches without destroying dirty-worktree changes

**Files:**

- Modify: `skill/scripts/deepseek_cowork.py`
- Modify: `tests/test_patch.py`

- [ ] **Step 1: Write failing application tests**

Cover:

- authorized patch applies to current working-tree content;
- an unrelated pre-existing modified file remains byte-identical;
- an authorized file with pre-existing edits receives a patch generated from its current supplied content;
- `git apply --check` failure leaves all files unchanged;
- a new authorized file is created;
- no commit is produced.

Representative test:

```python
def test_apply_preserves_unrelated_dirty_file():
    repo = make_repo({"src/app.py": "old\n", "notes.txt": "base\n"})
    write(repo / "notes.txt", "user edit\n")
    before = (repo / "notes.txt").read_bytes()
    dc.apply_patch(repo, patch_modifying("src/app.py", "old\n", "new\n"))
    self.assertEqual((repo / "notes.txt").read_bytes(), before)
    self.assertEqual((repo / "src/app.py").read_text(), "new\n")
```

- [ ] **Step 2: Confirm failure**

Run:

```powershell
python -m unittest tests.test_patch -v
```

Expected: missing `apply_patch`.

- [ ] **Step 3: Implement atomic preflight and application**

Implement:

```python
def run_git(repo_root, args, *, input_text=None):
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )

def apply_patch(repo_root, patch):
    check = run_git(repo_root, ["apply", "--check", "--whitespace=error-all", "-"], input_text=patch)
    if check.returncode:
        raise PatchError(_safe_summary(check.stderr, 2000))
    applied = run_git(repo_root, ["apply", "--whitespace=error-all", "-"], input_text=patch)
    if applied.returncode:
        raise PatchError(_safe_summary(applied.stderr, 2000))
```

Before preflight, confirm `git rev-parse --show-toplevel` equals the resolved requested repository. Snapshot SHA-256 and existence for every path reported by `git status --porcelain=v1 -z`. If the second `git apply` unexpectedly fails, verify snapshots are unchanged; if not, raise a high-severity `PatchError` naming affected paths without attempting destructive rollback.

- [ ] **Step 4: Run patch application tests**

Run:

```powershell
python -m unittest tests.test_patch -v
```

Expected: all tests pass and temporary repositories retain unrelated edits.

- [ ] **Step 5: Commit**

```powershell
git add skill/scripts/deepseek_cowork.py tests/test_patch.py
git commit -m "feat: safely apply deepseek patches"
```

### Task 6: Execute verification commands and bound output

**Files:**

- Modify: `skill/scripts/deepseek_cowork.py`
- Create: `tests/test_verification.py`

- [ ] **Step 1: Write failing verification tests**

Test sequential execution, stop-on-first-failure, timeout, UTF-8 replacement, and output truncation:

```python
def test_stops_after_first_failed_command():
    runner = FakeCommandRunner([
        completed("python -m unittest", 1, "", "failure"),
    ])
    result = dc.run_verification(repo, ["python -m unittest", "never-run"], runner=runner)
    self.assertFalse(result.passed)
    self.assertEqual(len(runner.calls), 1)

def test_output_is_bounded():
    result = dc._summarize_output("x" * 50000, max_chars=12000)
    self.assertLessEqual(len(result), 12000)
    self.assertIn("[output truncated]", result)
```

- [ ] **Step 2: Confirm failure**

Run:

```powershell
python -m unittest tests.test_verification -v
```

Expected: missing verification functions.

- [ ] **Step 3: Implement verification**

Use:

```python
@dataclass(frozen=True)
class CommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool

@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    commands: tuple[CommandResult, ...]
```

Execute commands through PowerShell on Windows:

```python
["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
```

Use `cwd=repo_root`, `timeout=config.timeout_seconds`, no shell string interpolation in Python, and stop after the first failure. Keep the first 4,000 and last 8,000 characters when truncating combined output.

- [ ] **Step 4: Run verification tests**

Run:

```powershell
python -m unittest tests.test_verification -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add skill/scripts/deepseek_cowork.py tests/test_verification.py
git commit -m "feat: run bounded verification commands"
```

### Task 7: Add the end-to-end CLI contract

**Files:**

- Modify: `skill/scripts/deepseek_cowork.py`
- Create: `tests/test_run.py`

- [ ] **Step 1: Write failing CLI and orchestration tests**

The CLI contract is:

```text
python deepseek_cowork.py run
  --repo-root <absolute path>
  --request <request.json>
  [--config <config.toml>]
```

JSON is written to stdout; diagnostics go to stderr. Exit codes:

- `0`: patch applied and all verification commands passed.
- `2`: DeepSeek returned `blocked`.
- `3`: protocol/config/API/patch error.
- `4`: patch applied but verification failed.

Tests must inject API and command runners and assert exact result envelopes:

```json
{
  "protocol_version": "1.0",
  "outcome": "applied",
  "summary": "Implemented change",
  "changed_files": ["src/app.py"],
  "verification": {
    "passed": true,
    "commands": []
  }
}
```

Also test `blocked`, rejected patch, failed verification, no API key leakage, and revision round 3 acceptance versus round 4 rejection.

- [ ] **Step 2: Confirm failure**

Run:

```powershell
python -m unittest tests.test_run -v
```

Expected: missing `run_workflow` and CLI.

- [ ] **Step 3: Implement orchestration**

Implement this order:

```python
def run_workflow(repo_root, request_path, config_path=None, *, sender=None, runner=None):
    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    validate_request(request)
    config = load_config(config_path)
    response = call_deepseek(config, request, sender=sender)
    if response["status"] == "blocked":
        return 2, blocked_result(response)
    analysis = analyze_patch(repo_root, request, response["patch"])
    assert_changed_files(response, analysis)
    apply_patch(repo_root, response["patch"])
    commands = request["verification_commands"] or list(config.verification_commands)
    verification = run_verification(repo_root, commands, config.timeout_seconds, runner=runner)
    return (0 if verification.passed else 4), applied_result(response, verification)
```

Catch expected `CoworkError` subclasses in `main()`, emit a sanitized error envelope, and return exit code `3`. Do not catch `KeyboardInterrupt`.

- [ ] **Step 4: Run all tests**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add skill/scripts/deepseek_cowork.py tests/test_run.py
git commit -m "feat: add cowork orchestration cli"
```

### Task 8: Write the Codex Skill workflow

**Files:**

- Create: `skill/SKILL.md`

- [ ] **Step 1: Write the Skill metadata**

Use:

```yaml
---
name: deepseek-cowork
description: Delegate bounded coding implementation to DeepSeek API while Codex plans, reviews, verifies, requests up to three revisions, and takes over if needed. Use when the user asks Codex and DeepSeek to co-work or wants to reduce Codex implementation token usage.
---
```

- [ ] **Step 2: Define the mandatory workflow**

The instructions must require Codex to:

1. Confirm the current directory is the intended Git repository.
2. Inspect `git status`, repository guidance, and relevant files.
3. Define task summary and acceptance criteria.
4. Select only necessary file contents.
5. Separate `authorized_files.modify` and `authorized_files.create`.
6. Determine verification commands, preferring explicit project configuration.
7. Classify `complex` only for architecture, cross-module work, complex debugging, concurrency, security, or data migration.
8. Write a request JSON under a repository-local ignored temporary directory such as `.codex/deepseek-cowork/`.
9. Invoke the Python script and inspect its result.
10. Review the actual Git diff and verification evidence.
11. On failure, issue concise structured feedback and submit revision rounds 1, 2, and 3.
12. If round 3 fails review, stop calling DeepSeek and implement the correction directly.

Explicitly prohibit sending secrets, `.env` files, credentials, unrelated source files, full conversation history, or unbounded test logs.

- [ ] **Step 3: Define review and takeover criteria**

Codex may accept only when:

- acceptance criteria are satisfied;
- no unauthorized changes exist;
- verification passes or a documented reason explains why a command cannot run;
- the diff has no obvious correctness, security, compatibility, or maintainability regression.

The Skill must state that API retries are script-level and do not consume revision rounds; invalid/unsafe patches do consume a round; `blocked` can be retried in the same round after adding minimum necessary context.

- [ ] **Step 4: Validate discoverability**

Run:

```powershell
Select-String -Path skill/SKILL.md -Pattern "DeepSeek","three","authorized_files","take over"
```

Expected: all required workflow concepts are present.

- [ ] **Step 5: Commit**

```powershell
git add skill/SKILL.md
git commit -m "feat: add deepseek cowork skill workflow"
```

### Task 9: Add secure Windows installation and user documentation

**Files:**

- Create: `install.ps1`
- Create: `README.md`

- [ ] **Step 1: Implement installer dry-run support**

Parameters:

```powershell
param(
    [string]$InstallRoot = (Join-Path $HOME ".agents\skills\deepseek-cowork"),
    [string]$ConfigPath = (Join-Path $HOME ".codex\deepseek-cowork\config.toml"),
    [switch]$WhatIf
)
```

The installer must:

- verify Python 3.11+ and Git exist;
- copy `skill/*` to `InstallRoot`;
- create the config parent directory;
- create a config template only when the file does not exist;
- never overwrite an existing API key;
- apply ACL protection with:

```powershell
$acl = Get-Acl -LiteralPath $ConfigPath
$acl.SetAccessRuleProtection($true, $false)
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    [System.Security.Principal.WindowsIdentity]::GetCurrent().Name,
    "FullControl",
    "Allow"
)
$acl.SetAccessRule($rule)
Set-Acl -LiteralPath $ConfigPath -AclObject $acl
```

Also grant `SYSTEM` full control so Windows backup and administration remain functional. Resolve and verify destination paths before recursive copying. `-WhatIf` prints intended actions without writing.

- [ ] **Step 2: Document setup and usage**

README sections:

- prerequisites;
- clone and `.\install.ps1`;
- edit `~/.codex/deepseek-cowork/config.toml`;
- restart Codex if the Skill is not detected;
- invoke with `$deepseek-cowork`;
- protocol and security model;
- dirty-worktree behavior;
- troubleshooting exit codes;
- warning that the API key is plaintext but ACL-restricted;
- model names are configurable because provider availability changes.

- [ ] **Step 3: Exercise installer dry run**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -WhatIf
```

Expected: reports Skill and config destinations without creating either.

- [ ] **Step 4: Install into a temporary directory**

Run:

```powershell
$temp = Join-Path $env:TEMP "deepseek-cowork-install-test"
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 `
  -InstallRoot (Join-Path $temp "skill") `
  -ConfigPath (Join-Path $temp "config.toml")
Test-Path (Join-Path $temp "skill\SKILL.md")
Test-Path (Join-Path $temp "config.toml")
```

Expected: both `Test-Path` calls return `True`; config contains no real credential.

- [ ] **Step 5: Commit**

```powershell
git add install.ps1 README.md
git commit -m "docs: add secure installation workflow"
```

### Task 10: Final verification and installation

**Files:**

- Modify only if verification exposes defects.

- [ ] **Step 1: Run the complete test suite**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Compile-check the Python script**

Run:

```powershell
python -m py_compile skill/scripts/deepseek_cowork.py
```

Expected: exit code `0`.

- [ ] **Step 3: Verify repository status and history**

Run:

```powershell
git status --short
git log --oneline --decorate -10
```

Expected: no unintended files; implementation is split across focused commits.

- [ ] **Step 4: Install the Skill globally**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

Expected: Skill is copied to `~/.agents/skills/deepseek-cowork` and config exists at `~/.codex/deepseek-cowork/config.toml`.

- [ ] **Step 5: Ask the user to enter the DeepSeek API key**

Do not request the key in chat and do not print the config. Tell the user to edit the local config file directly. After they confirm, perform a minimal live API smoke test using a temporary Git repository and a harmless authorized text-file patch.

- [ ] **Step 6: Commit any verification fixes**

If Step 1–5 required code changes:

```powershell
git add skill/scripts/deepseek_cowork.py skill/SKILL.md install.ps1 README.md tests
git commit -m "fix: address final verification findings"
```

Otherwise do not create an empty commit.
