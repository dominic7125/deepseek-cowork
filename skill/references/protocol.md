# DeepSeek Cowork Protocol 2.0

Protocol 2.0 replaces model-generated unified diffs with complete file content.
Unknown protocol versions must be rejected.

## Request

The request contains exactly:

- `protocol_version`: `"2.0"`
- `task`: `summary` and non-empty `acceptance_criteria`
- `mode`: `implementation` or `revision`
- `complexity`: `standard` or `complex`
- `revision_round`: `0` for implementation, `1..3` for revision
- `authorized_files`: unique relative POSIX paths split into `modify` and `create`
- `files`: current content for authorized existing files
- `project_rules`
- `verification_commands`
- `review_feedback`
- `verification_failure`

All paths use `/`, remain relative to the repository, and contain no empty,
`.` or `..` segments, drive prefixes, or backslashes.

## Success response

```json
{
  "protocol_version": "2.0",
  "status": "files",
  "summary": "Implemented the requested change",
  "files": [
    {
      "path": "src/example.py",
      "content": "complete final file content\n"
    }
  ],
  "assumptions": [],
  "verification_notes": []
}
```

Rules:

- `files` contains only changed files and at least one entry.
- Every entry has exactly `path` and complete final `content`.
- Paths must be unique at runtime and explicitly authorized.
- `modify` targets must already exist.
- `create` targets must not exist.
- Deletion, rename, move, binary output, and partial snippets are unsupported.
- The local script writes files atomically and asks Git to generate the diff.

## Blocked response

```json
{
  "protocol_version": "2.0",
  "status": "blocked",
  "summary": "Missing required context",
  "missing_context": ["src/model.py"]
}
```

## Retry policy

- Temporary HTTP failures use the configured transport retry count.
- Invalid JSON or an invalid Protocol 2.0 shape gets one format-only retry.
- A second format failure stops DeepSeek use for that attempt.
- The three revision rounds are reserved for implementation correctness, not formatting.
