from __future__ import annotations

import re
from pathlib import PurePosixPath

PROTOCOL_VERSION = "1.0"


class CoworkError(Exception):
    pass


class ProtocolError(CoworkError):
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
    seen = set()
    for index, item in enumerate(value):
        text = _require_string(item, f"{path}[{index}]", nonempty=item_nonempty)
        if text in seen:
            raise ProtocolError(f"{path} contains duplicate values")
        seen.add(text)
        result.append(text)
    return tuple(result)


def _validate_relative_posix_path(value, path):
    text = _require_string(value, path, nonempty=True)
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
