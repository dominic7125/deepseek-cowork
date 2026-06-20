from __future__ import annotations

from dataclasses import dataclass, field
import argparse
import json
import math
import os
import subprocess
import tempfile
import tomllib
import re
import time
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

PROTOCOL_VERSION = "2.0"


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
        raise ProtocolError(f"{path} fields do not match protocol {PROTOCOL_VERSION}")


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
        raw_bytes = config_path.read_bytes()
        if raw_bytes.startswith(b"\xef\xbb\xbf"):
            raw_bytes = raw_bytes[3:]
        raw = tomllib.loads(raw_bytes.decode("utf-8"))
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
            raise ProtocolError(f"review_feedback fields do not match protocol {PROTOCOL_VERSION}")
        required = {"severity", "file", "problem", "required_change"}
        if not required.issubset(actual):
            raise ProtocolError(f"review_feedback fields do not match protocol {PROTOCOL_VERSION}")
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
    if status == "files":
        expected = {
            "protocol_version",
            "status",
            "summary",
            "files",
            "assumptions",
            "verification_notes",
        }
        if set(data) != expected:
            raise ProtocolError(f"files response fields do not match protocol {PROTOCOL_VERSION}")
        _require_string(data["summary"], "summary", nonempty=True)
        _require_type(data["files"], list, "files")
        if not data["files"]:
            raise ProtocolError("files response must contain at least one file")
        seen = set()
        for index, item in enumerate(data["files"]):
            _require_exact_keys(item, {"path", "content"}, f"files[{index}]")
            path = _validate_relative_posix_path(item["path"], f"files[{index}].path")
            _require_string(item["content"], f"files[{index}].content")
            if path in seen:
                raise ProtocolError("files response contains duplicate paths")
            seen.add(path)
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
{"protocol_version":"2.0","status":"files","summary":"...","files":[{"path":"path","content":"complete final file content"}],"assumptions":[],"verification_notes":[]}

Missing-context shape:
{"protocol_version":"2.0","status":"blocked","summary":"...","missing_context":["path"]}

The protocol_version value must be the string "2.0". Do not echo request fields such as
task, mode, authorized_files, or files. Only modify/create authorized paths. Never delete,
rename, or move files. Return complete final text content for every changed file. Do not
return diffs, patches, line numbers, markdown fences, or unchanged files."""


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
    model = config.reasoning_model
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
        "thinking": {"type": "enabled"},
    }
    url = f"{config.base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    for format_attempt in range(2):
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
            except (TimeoutError, URLError):
                error = ApiError("temporary API connection error")
                retryable = True
            except ApiError as exc:
                error = exc
                retryable = "temporary" in str(exc)
            except (KeyError, IndexError, TypeError, json.JSONDecodeError, ProtocolError) as exc:
                if format_attempt == 0:
                    body["messages"].append(
                        {
                            "role": "user",
                            "content": (
                                "Your previous response violated Protocol 2.0. "
                                "Return exactly one of the two JSON shapes from the system prompt."
                            ),
                        }
                    )
                    break
                raise ApiError("API returned invalid Protocol 2.0 JSON twice") from exc
            if not retryable or attempt == config.transient_retries:
                raise error
            sleep(2**attempt)
        else:
            continue
    raise ApiError("API request failed")


def _git(repo_root, args):
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def write_response_files(repo_root, request_data, response):
    repo_root = Path(repo_root).resolve()
    top = _git(repo_root, ["rev-parse", "--show-toplevel"])
    if top.returncode or Path(top.stdout.strip()).resolve() != repo_root:
        raise PatchError("repo-root must be the Git repository root")
    modify = set(request_data["authorized_files"]["modify"])
    create = set(request_data["authorized_files"]["create"])
    entries = response["files"]
    paths = [entry["path"] for entry in entries]
    unauthorized = set(paths) - modify - create
    if unauthorized:
        raise PatchError(f"response changes unauthorized files: {', '.join(sorted(unauthorized))}")

    targets = {}
    originals = {}
    temp_paths = []
    try:
        for entry in entries:
            relative = entry["path"]
            raw_target = repo_root / Path(*PurePosixPath(relative).parts)
            target = raw_target.resolve()
            if not target.is_relative_to(repo_root) or raw_target.is_symlink():
                raise PatchError(f"unsafe target path: {relative}")
            if relative in modify and not target.is_file():
                raise PatchError(f"authorized modify path does not exist: {relative}")
            if relative in create and target.exists():
                raise PatchError(f"authorized create path already exists: {relative}")
            targets[relative] = target
            originals[relative] = target.read_bytes() if target.exists() else None
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix=".deepseek-cowork-", dir=target.parent)
            os.close(fd)
            temp_path = Path(temp_name)
            temp_path.write_text(entry["content"], encoding="utf-8", newline="")
            temp_paths.append(temp_path)

        for entry, temp_path in zip(entries, temp_paths):
            os.replace(temp_path, targets[entry["path"]])
        return tuple(paths)
    except Exception:
        for relative, original in originals.items():
            target = targets[relative]
            if original is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(original)
        raise
    finally:
        for temp_path in temp_paths:
            temp_path.unlink(missing_ok=True)


def generated_diff(repo_root, request_data, paths):
    modify = [path for path in paths if path in request_data["authorized_files"]["modify"]]
    create = [path for path in paths if path in request_data["authorized_files"]["create"]]
    parts = []
    if modify:
        result = _git(repo_root, ["diff", "--", *modify])
        parts.append(result.stdout)
    for path in create:
        result = _git(repo_root, ["diff", "--no-index", "--", "/dev/null", path])
        if result.returncode not in {0, 1}:
            raise PatchError(f"could not generate diff for {path}")
        parts.append(result.stdout)
    return "".join(parts)


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
    changed_files = write_response_files(repo_root, request_data, response)
    diff = generated_diff(repo_root, request_data, changed_files)
    commands = request_data["verification_commands"] or list(config.verification_commands)
    verification = run_verification(repo_root, commands, config.timeout_seconds)
    return (
        0 if verification["passed"] else 4,
        {
            "protocol_version": PROTOCOL_VERSION,
            "outcome": "applied",
            "summary": response["summary"],
            "changed_files": list(changed_files),
            "diff": diff,
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
