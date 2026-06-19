# DeepSeek Cowork Protocol 1.0

This protocol version is fixed at `1.0`. Implementations must reject unknown protocol versions rather than guessing at compatibility.

## Request

The request object must contain exactly these fields:

- `protocol_version`
- `task`
- `mode`
- `complexity`
- `revision_round`
- `authorized_files`
- `files`
- `project_rules`
- `verification_commands`
- `review_feedback`
- `verification_failure`

Nested constraints:

- `protocol_version` must be `"1.0"`.
- `mode` must be `"implementation"` or `"revision"`.
- `complexity` must be `"standard"` or `"complex"`.
- `revision_round` must be an integer from `0` to `3`.
- `task` contains exactly `summary` and `acceptance_criteria`.
- `task.summary` is a non-empty string.
- `task.acceptance_criteria` is a non-empty array of strings and may repeat values.
- `authorized_files.modify` and `authorized_files.create` are arrays of unique relative POSIX paths.
- `files` is an array of `{ "path", "content" }` objects with unique paths.
- `files[].path uniqueness is enforced at runtime because JSON Schema cannot enforce uniqueness across array objects.`
- `files[].path` is a relative POSIX path and `files[].content` is a string.
- `project_rules` is an array of strings and may repeat values.
- `verification_commands` is an array of strings and may repeat values.
- `review_feedback` is an array of objects.
- `review_feedback` items must contain `severity`, `file`, `problem`, and `required_change`.
- `review_feedback` items may include `line`.
- `review_feedback[].file` is a relative POSIX path.
- `verification_failure` is either `null` or an object with `command`, `exit_code`, and `summary`.
- `verification_failure.command` and `verification_failure.summary` are non-empty strings.
- `verification_failure.exit_code` is an integer.

Round semantics:

- `implementation` requests must use `revision_round = 0`.
- `revision` requests must use `revision_round = 1`, `2`, or `3`.

## Response

Patch responses contain exactly `changed_files`, `patch`, `assumptions`, and `verification_notes`.

Patch responses must contain exactly:

- `protocol_version`
- `status`
- `summary`
- `changed_files`
- `patch`
- `assumptions`
- `verification_notes`

Blocked responses contain exactly `missing_context`.

Blocked responses must contain exactly:

- `protocol_version`
- `status`
- `summary`
- `missing_context`

Response array constraints:

- `changed_files` is a unique array of relative POSIX paths.
- `patch` is a non-empty unified diff string.
- `assumptions` is an array of strings and may repeat values.
- `verification_notes` is an array of strings and may repeat values.
- `missing_context` is a unique array of relative POSIX paths.
- `status` is `"patch"` or `"blocked"`.
- A `patch` response must include a non-empty unified diff.
- A `blocked` response must not include `patch` or `changed_files`.

## Path rules

All paths in requests and responses must be relative POSIX paths:

- use `/` separators;
- no absolute paths;
- no drive prefixes;
- no backslashes;
- no `.` or `..` path segments;
- no empty path segments.

## Compatibility rule

If a request or response uses a protocol version other than `1.0`, reject it explicitly.

