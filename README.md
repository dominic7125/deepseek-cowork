# DeepSeek Cowork for Codex

Codex plans and reviews; DeepSeek implements. Codex stops as soon as the result passes review, with at most three revision rounds before Codex takes over.

All DeepSeek work uses the configured Pro reasoning model. Flash is retained in the config format for backward compatibility but is not called.

Protocol 2.0 asks DeepSeek for complete changed-file contents. The local script
writes authorized files and lets Git generate the diff, avoiding fragile
model-generated hunk line numbers. Small changes (roughly under 15 minutes or
fewer than three files) are handled directly by Codex unless DeepSeek is
explicitly requested.

## Install

Requires Git and Python 3.11+ on Windows:

```powershell
git clone https://github.com/dominic7125/deepseek-cowork.git
cd deepseek-cowork
.\install.ps1
```

Edit `~/.codex/deepseek-cowork/config.toml` locally and replace `REPLACE_ME` with your DeepSeek API key. The key is plaintext but the installer restricts the file ACL to your Windows user and SYSTEM. Do not paste the key into chat or commit it.

Restart Codex if the Skill does not appear, then invoke:

```text
$deepseek-cowork implement <your task>
```

The repository must use Git. Existing uncommitted changes are allowed; commit or back them up when they are important. DeepSeek receives only files selected by Codex and cannot delete or rename files.

Exit codes: `0` applied and verified, `2` needs context, `3` configuration/API/patch error, `4` patch applied but verification failed.
