from __future__ import annotations

from dataclasses import dataclass, field
import argparse
import json
import math
import subprocess
import tomllib
import re
import time
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

PROTOCOL_VERSION = "1.0"


class CoworkError(Exception):
    pass


class ProtocolError(CoworkError):
    pass


@dataclass(frozen=True)
class Config:
    api_key: str = field(repr=False)
    base_url: str
    fast_model: str
    reasoning_model: str
    max_revision_rounds: int
    timeout_seconds: float
    transient_retries: int
    verification_commands: tuple[str, ...]


class ConfigError(CoworkError):
    pass


class ApiError(CoworkError):
    pass


class PatchError(CoworkError):
    pass


def _require_type(value, expected, path):
    if not isinstance(value, expected):
        raise ProtocolError(f"{path} has invalid type")


def _require_exact_keys(value, keys, path):
    _require_type(value, dict, path)
    expected = set(keys)
    actual = set(value)
    if actual != expected:
        raise ProtocolError(f"{path} fields do not match protocol 1.0")


def _require_string(value, path, *, nonempty=False):
    _require_type(value, str, path)
    if nonempty and not value.strip():
        raise ProtocolError(f"{path} must be a non-empty string")
    return value


def _require_int(value, path, *, minimum=None, maximum=None):
    if type(value) is not int:
        raise ProtocolError(f"{path} has invalid type")
    if minimum is not None and value < minimum:
        raise ProtocolError(f"{path} is out of range")
    if maximum is not None and value > maximum:
        raise ProtocolError(f"{path} is out of range")
    return value


def _require_string_list(value, path, *, item_nonempty=False):
    _require_type(value, list, path)
    result = []
    for index, item in enumerate(value):
        text = _require_string(item, f"{path}[{index}]", nonempty=item_nonempty)
        result.append(text)
    return tuple(result)


def _config_type(value, expected, path):
    if not isinstance(value, expected):
        raise ConfigError(f"{path} has invalid type")


def _config_exact_keys(value, keys, path):
    _config_type(value, dict, path)
    expected = set(keys)
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        details = []
        if missing:
            details.append(f"missing keys: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected keys: {', '.join(unexpected)}")
        raise ConfigError(f"{path} fields do not match expected configuration ({'; '.join(details)})")


def _config_string(value, path, *, nonempty=False):
    _config_type(value, str, path)
    if nonempty and not value.strip():
        raise ConfigError(f"{path} must be a non-empty string")
    return value


def _config_int(value, path, *, minimum=None):
    if type(value) is not int:
        raise ConfigError(f"{path} has invalid type")
    if minimum is not None and value < minimum:
        raise ConfigError(f"{path} is out of range")
    return value


def _config_number(value, path, *, minimum_exclusive=None):
    if type(value) not in {int, float}:
        raise ConfigError(f"{path} has invalid type")
    number = float(value)
    if not math.isfinite(number):
        raise ConfigError(f"{path} must be finite")
    if minimum_exclusive is not None and number <= minimum_exclusive:
        raise ConfigError(f"{path} must be greater than 0")
    return number


def _config_string_list(value, path, *, item_nonempty=False):
    _config_type(value, list, path)
    result = []
    for index, item in enumerate(value):
        text = _config_string(item, f"{path}[{index}]", nonempty=item_nonempty)
        result.append(text)
    return tuple(result)


def _https_url(value, path):
    text = _config_string(value, path, nonempty=True)
    if any(char.isspace() for char in text):
        raise ConfigError(f"{path} must be an HTTPS URL")
    try:
        parsed = urlparse(text)
        if parsed.scheme != "https":
            raise ConfigError(f"{path} must be an HTTPS URL")
        if parsed.username is not None or parsed.password is not None:
            raise ConfigError(f"{path} must be an HTTPS URL")
        if parsed.query or parsed.fragment:
            raise ConfigError(f"{path} must be an HTTPS URL")
        port = parsed.port
        hostname = parsed.hostname
    except ValueError as exc:
        raise ConfigError(f"{path} must be an HTTPS URL") from exc
    if hostname is None or not hostname.strip():
        raise ConfigError(f"{path} must be an HTTPS URL")
    if port is not None and not (0 < port < 65536):
        raise ConfigError(f"{path} must be an HTTPS URL")
    return text.rstrip("/")


def default_config_path():
    return Path.home() / ".codex" / "deepseek-cowork" / "config.toml"


def load_config(path=None):
    config_path = Path(path) if path is not None else default_config_path()
    try:
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)
    except OSError as exc:
        raise ConfigError(f"configuration file error: {config_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"configuration file is not valid TOML: {config_path}") from exc

    _config_exact_keys(raw, {"api_key", "base_url", "models", "runtime", "verification"}, "config")
    _config_exact_keys(raw["models"], {"fast", "reasoning"}, "models")
    _config_exact_keys(
        raw["runtime"],
        {"max_revision_rounds", "timeout_seconds", "transient_retries"},
        "runtime",
    )
    _config_exact_keys(raw["verification"], {"commands"}, "verification")

    api_key = _config_string(raw["api_key"], "api_key", nonempty=True)
    base_url = _https_url(raw["base_url"], "base_url")
    fast_model = _config_string(raw["models"]["fast"], "models.fast", nonempty=True)
    reasoning_model = _config_string(raw["models"]["reasoning"], "models.reasoning", nonempty=True)
    max_revision_rounds = _config_int(
        raw["runtime"]["max_revision_rounds"], "max_revision_rounds", minimum=0
    )
    if max_revision_rounds != 3:
        raise ConfigError("max_revision_rounds must be exactly 3")
    timeout_seconds = _config_number(
        raw["runtime"]["timeout_seconds"], "timeout_seconds", minimum_exclusive=0
    )
    transient_retries = _config_int(
        raw["runtime"]["transient_retries"], "transient_retries", minimum=0
    )
    verification_commands = _config_string_list(
        raw["verification"]["commands"], "verification.commands", item_nonempty=True
    )

    return Config(
        api_key=api_key,
        base_url=base_url,
        fast_model=fast_model,
        reasoning_model=reasoning_model,
        max_revision_rounds=max_revision_rounds,
        timeout_seconds=timeout_seconds,
        transient_retries=transient_retries,
        verification_commands=verification_commands,
    )


def _validate_relative_posix_path(value, path):
    text = _require_string(value, path, nonempty=True)
    if text == ".":
        raise ProtocolError(f"{path} must be a relative POSIX path")
    if "\\" in text:
        raise ProtocolError(f"{path} must be a relative POSIX path")
    if text.startswith("/") or text.startswith("//"):
        raise ProtocolError(f"{path} must be a relative POSIX path")
    if re.match(r"^[A-Za-z]:", text):
        raise ProtocolError(f"{path} must be a relative POSIX path")
    pure = PurePosixPath(text)
    if pure.is_absolute():
        raise ProtocolError(f"{path} must be a relative POSIX path")
    if str(pure) != text:
        raise ProtocolError(f"{path} must be a normalized relative POSIX path")
    for part in pure.parts:
        if part in {"", ".", ".."}:
            raise ProtocolError(f"{path} must be a relative POSIX path")
    return text


def _validate_task(task):
    _require_exact_keys(task, {"summary", "acceptance_criteria"}, "task")
    _require_string(task["summary"], "task.summary", nonempty=True)
    criteria = _require_string_list(
        task["acceptance_criteria"], "task.acceptance_criteria", item_nonempty=True
    )
    if not criteria:
        raise ProtocolError("task.acceptance_criteria must not be empty")


def _validate_authorized_files(authorised):
    _require_exact_keys(authorised, {"modify", "create"}, "authorized_files")
    modify = _require_string_list(
        authorised["modify"], "authorized_files.modify", item_nonempty=True
    )
    create = _require_string_list(
        authorised["create"], "authorized_files.create", item_nonempty=True
    )
    modify_set = set()
    for index, path in enumerate(modify):
        validated = _validate_relative_posix_path(path, f"authorized_files.modify[{index}]")
        if validated in modify_set:
            raise ProtocolError("authorized_files.modify contains duplicate paths")
        modify_set.add(validated)
    create_set = set()
    for index, path in enumerate(create):
        validated = _validate_relative_posix_path(path, f"authorized_files.create[{index}]")
        if validated in create_set:
            raise ProtocolError("authorized_files.create contains duplicate paths")
        create_set.add(validated)
    if modify_set & create_set:
        raise ProtocolError("authorized modify/create paths overlap")
    return modify_set, create_set


def _validate_files(files, authorized_modify):
    _require_type(files, list, "files")
    seen = set()
    for index, entry in enumerate(files):
        _require_exact_keys(entry, {"path", "content"}, f"files[{index}]")
        path = _validate_relative_posix_path(entry["path"], f"files[{index}].path")
        _require_string(entry["content"], f"files[{index}].content")
        if path in seen:
            raise ProtocolError("files contains duplicate paths")
        seen.add(path)
        if path not in authorized_modify:
            raise ProtocolError("files may contain only authorized existing files")


def _validate_project_rules(value):
    _require_string_list(value, "project_rules", item_nonempty=True)


def _validate_verification_commands(value):
    _require_string_list(value, "verification_commands", item_nonempty=True)


def _validate_review_feedback(value):
    _require_type(value, list, "review_feedback")
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ProtocolError(f"review_feedback[{index}] has invalid type")
        allowed = {"severity", "file", "problem", "required_change", "line"}
        actual = set(item)
        if not actual.issubset(allowed):
            raise ProtocolError("review_feedback fields do not match protocol 1.0")
        required = {"severity", "file", "problem", "required_change"}
        if not required.issubset(actual):
            raise ProtocolError("review_feedback fields do not match protocol 1.0")
        _require_string(item["severity"], f"review_feedback[{index}].severity", nonempty=True)
        _validate_relative_posix_path(item["file"], f"review_feedback[{index}].file")
        _require_string(item["problem"], f"review_feedback[{index}].problem", nonempty=True)
        _require_string(
            item["required_change"], f"review_feedback[{index}].required_change", nonempty=True
        )
        if "line" in item:
            _require_int(item["line"], f"review_feedback[{index}].line", minimum=1)


def _validate_verification_failure(value):
    if value is None:
        return
    _require_exact_keys(value, {"command", "exit_code", "summary"}, "verification_failure")
    _require_string(value["command"], "verification_failure.command", nonempty=True)
    _require_int(value["exit_code"], "verification_failure.exit_code")
    _require_string(value["summary"], "verification_failure.summary", nonempty=True)


def validate_request(data):
    _require_exact_keys(
        data,
        {
            "protocol_version",
            "task",
            "mode",
            "complexity",
            "revision_round",
            "authorized_files",
            "files",
            "project_rules",
            "verification_commands",
            "review_feedback",
            "verification_failure",
        },
        "request",
    )
    if data["protocol_version"] != PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol_version")
    if data["mode"] not in {"implementation", "revision"}:
        raise ProtocolError("invalid mode")
    if data["complexity"] not in {"standard", "complex"}:
        raise ProtocolError("invalid complexity")
    revision_round = _require_int(data["revision_round"], "revision_round", minimum=0, maximum=3)
    if data["mode"] == "implementation" and revision_round != 0:
        raise ProtocolError("implementation mode requires revision_round 0")
    if data["mode"] == "revision" and revision_round == 0:
        raise ProtocolError("revision mode requires revision_round 1..3")
    _validate_task(data["task"])
    modify, _create = _validate_authorized_files(data["authorized_files"])
    _validate_files(data["files"], modify)
    _validate_project_rules(data["project_rules"])
    _validate_verification_commands(data["verification_commands"])
    _validate_review_feedback(data["review_feedback"])
    _validate_verification_failure(data["verification_failure"])


def _validate_string_path_list(value, path):
    _require_type(value, list, path)
    seen = set()
    result = []
    for index, item in enumerate(value):
        text = _validate_relative_posix_path(item, f"{path}[{index}]")
        if text in seen:
            raise ProtocolError(f"{path} contains duplicate paths")
        seen.add(text)
        result.append(text)
    return tuple(result)


def validate_response(data):
    _require_type(data, dict, "response")
    if data.get("protocol_version") != PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol_version")
    status = data.get("status")
    if status == "patch":
        expected = {
            "protocol_version",
            "status",
            "summary",
            "changed_files",
            "patch",
            "assumptions",
            "verification_notes",
        }
        if set(data) != expected:
            raise ProtocolError("patch response fields do not match protocol 1.0")
        _require_string(data["summary"], "summary", nonempty=True)
        _validate_string_path_list(data["changed_files"], "changed_files")
        _require_string(data["patch"], "patch", nonempty=True)
        _require_string_list(data["assumptions"], "assumptions")
        _require_string_list(data["verification_notes"], "verification_notes")
        return
    if status == "blocked":
        expected = {"protocol_version", "status", "summary", "missing_context"}
        if set(data) != expected:
            raise ProtocolError("blocked response must not contain patch fields")
        _require_string(data["summary"], "summary", nonempty=True)
        _validate_string_path_list(data["missing_context"], "missing_context")
        return
    raise ProtocolError("invalid response status")


SYSTEM_PROMPT = """You are an implementation worker. Use only the supplied files and rules.
Return exactly one JSON object, with no markdown and no extra fields.

Success shape:
{"protocol_version":"1.0","status":"patch","summary":"...","changed_files":["path"],"patch":"diff --git a/path b/path\\n...","assumptions":[],"verification_notes":[]}

Missing-context shape:
{"protocol_version":"1.0","status":"blocked","summary":"...","missing_context":["path"]}

The protocol_version value must be the string "1.0". Do not echo request fields such as
task, mode, authorized_files, or files. Only modify/create authorized paths. Never delete,
rename, move, or emit binary patches. A successful patch must be a git-style unified diff
beginning with "diff --git"."""


def _default_sender(url, headers, body, timeout):
    request = Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return response.status, response.read().decode("utf-8", errors="replace")


def call_deepseek(config, request_data, *, sender=None, sleep=time.sleep):
    validate_request(request_data)
    sender = sender or _default_sender
    model = (
        config.reasoning_model
        if request_data["complexity"] == "complex"
        else config.fast_model
    )
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    request_data, ensure_ascii=False, separators=(",", ":")
                ),
            },
        ],
        "response_format": {"type": "json_object"},
        "stream": False,
        "thinking": {
            "type": "enabled"
            if request_data["complexity"] == "complex"
            else "disabled"
        },
    }
    url = f"{config.base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    for attempt in range(config.transient_retries + 1):
        try:
            status, raw = sender(url, headers, body, config.timeout_seconds)
            if status == 429 or status >= 500:
                raise ApiError(f"temporary API error: HTTP {status}")
            if status >= 400:
                raise ApiError(f"API request failed: HTTP {status}")
            envelope = json.loads(raw)
            content = envelope["choices"][0]["message"]["content"]
            result = json.loads(content)
            validate_response(result)
            return result
        except HTTPError as exc:
            error = ApiError(f"API request failed: HTTP {exc.code}")
            retryable = exc.code == 429 or exc.code >= 500
        except (TimeoutError, URLError) as exc:
            error = ApiError("temporary API connection error")
            retryable = True
        except ApiError as exc:
            error = exc
            retryable = "temporary" in str(exc)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ApiError("API returned an invalid JSON response") from exc
        if not retryable or attempt == config.transient_retries:
            raise error
        sleep(2**attempt)
    raise ApiError("API request failed")


def _patch_paths(patch):
    forbidden = (
        "deleted file mode",
        "rename from ",
        "rename to ",
        "GIT binary patch",
        "Binary files ",
        "old mode 120000",
        "new mode 120000",
        "old mode 160000",
        "new mode 160000",
    )
    if any(marker in patch for marker in forbidden):
        raise PatchError("patch contains a forbidden operation")
    paths = []
    for line in patch.splitlines():
        match = re.match(r"^diff --git a/(.+) b/(.+)$", line)
        if not match:
            continue
        old, new = match.groups()
        if old != new:
            raise PatchError("patch may not rename files")
        paths.append(_validate_relative_posix_path(new, "patch path"))
    if not paths:
        raise PatchError("patch contains no git diff")
    if len(paths) != len(set(paths)):
        raise PatchError("patch contains duplicate files")
    return tuple(paths)


def validate_patch(request_data, response):
    paths = _patch_paths(response["patch"])
    if set(paths) != set(response["changed_files"]):
        raise PatchError("changed_files does not match patch")
    modify = set(request_data["authorized_files"]["modify"])
    create = set(request_data["authorized_files"]["create"])
    unauthorized = set(paths) - modify - create
    if unauthorized:
        raise PatchError(f"patch changes unauthorized files: {', '.join(sorted(unauthorized))}")
    for path in create:
        if path in paths and f"new file mode " not in response["patch"]:
            raise PatchError(f"authorized create path is not a new file: {path}")
    return paths


def _git(repo_root, args, patch=None):
    if patch is not None:
        return subprocess.run(
            ["git", "-C", str(repo_root), *args],
            input=patch.encode("utf-8"),
            capture_output=True,
            check=False,
        )
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def _normalize_patch(patch):
    # DeepSeek sometimes invents incorrect blob hashes; git apply does not need them.
    return "\n".join(
        line for line in patch.splitlines() if not line.startswith("index ")
    ) + "\n"


def apply_patch(repo_root, patch):
    repo_root = Path(repo_root).resolve()
    patch = _normalize_patch(patch)
    top = _git(repo_root, ["rev-parse", "--show-toplevel"])
    if top.returncode or Path(top.stdout.strip()).resolve() != repo_root:
        raise PatchError("repo-root must be the Git repository root")
    check = _git(repo_root, ["apply", "--check", "--whitespace=error-all", "-"], patch)
    if check.returncode:
        raise PatchError("patch cannot be applied cleanly")
    applied = _git(repo_root, ["apply", "--whitespace=error-all", "-"], patch)
    if applied.returncode:
        raise PatchError("patch application failed")


def run_verification(repo_root, commands, timeout):
    results = []
    for command in commands:
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=repo_root,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=timeout,
                check=False,
            )
            output = (completed.stdout + completed.stderr)
            if len(output) > 12000:
                output = output[:4000] + "\n[output truncated]\n" + output[-8000:]
            results.append(
                {"command": command, "exit_code": completed.returncode, "output": output}
            )
            if completed.returncode:
                break
        except subprocess.TimeoutExpired:
            results.append({"command": command, "exit_code": -1, "output": "timed out"})
            break
    return {"passed": all(item["exit_code"] == 0 for item in results), "commands": results}


def run_workflow(repo_root, request_path, config_path=None, *, sender=None):
    request_data = json.loads(Path(request_path).read_text(encoding="utf-8"))
    config = load_config(config_path)
    response = call_deepseek(config, request_data, sender=sender)
    if response["status"] == "blocked":
        return 2, {"outcome": "blocked", **response}
    validate_patch(request_data, response)
    apply_patch(repo_root, response["patch"])
    commands = request_data["verification_commands"] or list(config.verification_commands)
    verification = run_verification(repo_root, commands, config.timeout_seconds)
    return (
        0 if verification["passed"] else 4,
        {
            "protocol_version": PROTOCOL_VERSION,
            "outcome": "applied",
            "summary": response["summary"],
            "changed_files": response["changed_files"],
            "verification": verification,
        },
    )


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run"])
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--config")
    args = parser.parse_args(argv)
    try:
        code, result = run_workflow(
            Path(args.repo_root), Path(args.request), args.config
        )
    except (CoworkError, OSError, json.JSONDecodeError) as exc:
        code, result = 3, {
            "protocol_version": PROTOCOL_VERSION,
            "outcome": "error",
            "error": str(exc),
        }
    print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
