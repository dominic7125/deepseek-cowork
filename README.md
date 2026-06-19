# DeepSeek Cowork for Codex

Codex plans and reviews; DeepSeek implements; after three failed revisions Codex takes over.

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
