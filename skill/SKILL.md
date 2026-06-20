---
name: deepseek-cowork
description: Let Codex plan and review while DeepSeek implements bounded code changes through its API. Use when the user asks Codex and DeepSeek to co-work or reduce Codex implementation token use.
---

# DeepSeek Cowork

1. In the intended Git repository, give DeepSeek Pro a concise Protocol 2.0 request: goal, 3–8 measurable acceptance criteria, authorized paths, necessary non-secret files, project rules, and verification commands.

2. Let DeepSeek own tests, implementation, and up to ten automatic verification-driven repairs. Do not inspect intermediate rounds; a valid result stops the loop immediately.

3. DeepSeek returns complete changed-file contents. The script enforces authorized paths, writes files atomically, runs verification, and lets Git generate the diff.

4. Write the request to `.codex/deepseek-cowork/request.json`, then run `python "$HOME\.agents\skills\deepseek-cowork\scripts\deepseek_cowork.py" run --repo-root "$PWD" --request ".codex\deepseek-cowork\request.json"` with an external timeout of at least three hours.

5. Codex performs one final review only. Prefer final changed files for small repositories, a focused diff for local edits, and targeted high-risk files for large changes.

6. Codex directly fixes remaining issues and verifies the result. Never send the final Codex review back to DeepSeek.

Read `references/protocol.md` only when constructing or troubleshooting the request.
