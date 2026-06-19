# DeepSeek Cowork Protocol 1.0

This repository uses protocol version `1.0`. Implementations must reject unknown protocol versions rather than guessing at compatibility.

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

Rules:

- `protocol_version` must be `"1.0"`.
- `mode` must be `"implementation"` or `"revision"`.
- `complexity` must be `"standard"` or `"complex"`.
- `revision_round` must be an integer from `0` to `3`.
- `task` contains exactly `summary` and `acceptance_criteria`.
- `authorized_files.modify` and `authorized_files.create` are arrays of unique relative POSIX paths.
- `files` is an array of `{ "path", "content" }` objects with unique paths.
- `project_rules` and `verification_commands` are arrays of strings.
- `review_feedback` is an array of structured review notes.
- `verification_failure` is either `null` or a structured failure object.

Round semantics:

- `implementation` requests must use `revision_round = 0`.
- `revision` requests must use `revision_round = 1`, `2`, or `3`.

## Response

Patch responses must contain exactly:

- `protocol_version`
- `status`
- `summary`
- `changed_files`
- `patch`
- `assumptions`
- `verification_notes`

Blocked responses must contain exactly:

- `protocol_version`
- `status`
- `summary`
- `missing_context`

Rules:

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

