---
name: deepseek-cowork
description: Let Codex plan and review while DeepSeek implements bounded code changes through its API. Use when the user asks Codex and DeepSeek to co-work or reduce Codex implementation token use.
---

# DeepSeek Cowork

1. First estimate the work. If Codex can implement it in about 15 minutes or it changes fewer than three files, Codex should implement it directly unless the user explicitly requests DeepSeek. This avoids delegation overhead on small tasks.
2. Confirm the working directory is the intended Git repository. Inspect `git status` and preserve existing user changes.
3. Plan the task and write concrete acceptance criteria.
4. Select only necessary, non-secret files. Never send credentials, `.env` files, unrelated code, full chat history, or unbounded logs.
5. Set task complexity accurately for context, but always use the configured Pro reasoning model. Flash is intentionally disabled because reliable protocol output is more important than lower model cost.
6. Build a Protocol 2.0 request. Explicitly list files DeepSeek may modify and files it may create. Do not authorize deletion or rename.
7. Put the request under `.codex/deepseek-cowork/request.json` and run:

```powershell
python "$HOME\.agents\skills\deepseek-cowork\scripts\deepseek_cowork.py" run `
  --repo-root "$PWD" `
  --request ".codex\deepseek-cowork\request.json"
```

8. Review the local Git-generated diff and verification result. If Codex judges the result correct and the acceptance criteria are met, finish immediately; do not run unnecessary revision rounds.
9. Do not inspect or write feedback during intermediate failures. The script sends concise test/lint/build failures directly to DeepSeek for up to ten automatic revision rounds, stopping immediately when verification passes.
10. A malformed response gets one automatic format-only retry and does not consume a revision round.
11. After verification passes or all ten revisions are exhausted, Codex performs one final review and directly fixes any remaining issue. Do not send Codex's final review back to DeepSeek.

Read `references/protocol.md` when constructing requests.
