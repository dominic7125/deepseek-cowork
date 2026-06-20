---
name: deepseek-cowork
description: Let Codex plan and review while DeepSeek implements bounded code changes through its API. Use when the user asks Codex and DeepSeek to co-work or reduce Codex implementation token use.
---

# DeepSeek Cowork

1. Confirm the working directory is the intended Git repository. Inspect `git status` and preserve existing user changes.
2. Plan the task and write concrete acceptance criteria.
3. Select only necessary, non-secret files. Never send credentials, `.env` files, unrelated code, full chat history, or unbounded logs.
4. Set task complexity accurately for context, but always use the configured Pro reasoning model. Flash is intentionally disabled because reliable protocol output is more important than lower model cost.
5. Build a Protocol 1.0 request. Explicitly list files DeepSeek may modify and files it may create. Do not authorize deletion or rename.
6. Put the request under `.codex/deepseek-cowork/request.json` and run:

```powershell
python "$HOME\.agents\skills\deepseek-cowork\scripts\deepseek_cowork.py" run `
  --repo-root "$PWD" `
  --request ".codex\deepseek-cowork\request.json"
```

7. Review the actual Git diff and verification result. If Codex judges the result correct and the acceptance criteria are met, finish immediately; do not run unnecessary revision rounds.
8. Only if review fails, send current relevant files plus concise `review_feedback`. Use at most three revision rounds (1, 2, then 3), stopping as soon as Codex approves. Do not resend full history.
9. API retries do not count as revision rounds. A blocked response may be retried in the same round after adding only the missing context.
10. If round 3 still fails, stop using DeepSeek and fix the remaining work directly with Codex.

Read `references/protocol.md` when constructing requests.
