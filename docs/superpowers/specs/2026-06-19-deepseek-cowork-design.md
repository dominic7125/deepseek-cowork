# Codex–DeepSeek Cowork Skill 設計

日期：2026-06-19

## 目標與流程

建立個人全域 Codex Skill。Codex 負責規劃、選取最少上下文、審查與最終修正；DeepSeek API 負責主要程式實作，以降低 Codex 的實作 token 消耗。

1. Codex 制定計畫與驗收條件。
2. Codex 選取必要檔案及授權修改範圍。
3. DeepSeek 產生 unified diff。
4. Python 腳本驗證、套用 patch 並執行驗證命令。
5. Codex 審查 diff 和驗證結果。
6. DeepSeek 依意見修正，最多三輪。
7. 三輪後仍不通過，由 Codex 接手修改與驗證。

## 安裝結構

```text
~/.agents/skills/deepseek-cowork/
├─ SKILL.md
├─ scripts/deepseek_cowork.py
├─ references/
│  ├─ protocol.md
│  ├─ request.schema.json
│  └─ response.schema.json
└─ tests/test_deepseek_cowork.py
```

全域設定位於 `~/.codex/deepseek-cowork/config.toml`。API key 以明文保存，安裝時使用 Windows ACL 限制為目前使用者可讀。

## 責任邊界

Codex：

- 規劃、驗收條件、複雜度和模型模式。
- 選取最少必要檔案。
- 明確列出允許修改及新增的檔案。
- 提供最終驗證命令。
- 審查每輪修改並產生精簡、可操作的修正意見。
- 第三輪仍失敗時接手。

Python 腳本：

- 讀取設定並呼叫 DeepSeek Chat Completions API。
- 驗證版本化 JSON 協議和 unified diff。
- 阻擋未授權、刪檔、改名、binary、symlink、submodule、越界 patch。
- 套用 patch、執行驗證命令、回傳結構化結果。
- 暫時性 API 錯誤最多重試兩次。

DeepSeek：

- 只能使用請求所附內容，不自行讀取 repository 或執行 shell。
- 只能回傳符合 schema 的 JSON。
- 可以修改既有授權檔案及新增事先授權檔案，不得刪除、移動或重新命名檔案。

## 模型路由

- 快速模式：`deepseek-v4-flash`，thinking disabled。
- 複雜模式：`deepseek-v4-pro`，thinking enabled。
- Codex 在第一輪前判斷複雜度；架構、跨模組、複雜除錯、併發、安全或資料遷移直接使用複雜模式。
- 模型名稱由設定提供，不硬編碼在 Skill 流程中。

## Git 與驗證

- 必須在 Git repository 中執行。
- 允許開始前已有未提交修改。
- 腳本記錄基準工作樹和相關檔案內容，不得覆蓋或回復使用者原有修改。
- 不使用破壞性 Git 重置，不自動 commit。
- 專案覆寫的驗證命令優先；否則由 Codex 根據專案設定與慣例決定。
- 腳本不自行猜測驗證命令，只執行 Codex 傳入的命令。

## 通訊協議

協議使用版本化 JSON 封套；patch 使用 unified diff。腳本不得解析自由格式自然語言。

請求主要欄位：

```json
{
  "protocol_version": "1.0",
  "task": {
    "summary": "實作登入功能",
    "acceptance_criteria": ["錯誤密碼回傳 401"]
  },
  "mode": "implementation",
  "complexity": "standard",
  "revision_round": 0,
  "authorized_files": {
    "modify": ["src/auth.py"],
    "create": ["tests/test_auth.py"]
  },
  "files": [{"path": "src/auth.py", "content": "..."}],
  "project_rules": ["不得刪除檔案"],
  "verification_commands": ["pytest tests/test_auth.py"],
  "review_feedback": [],
  "verification_failure": null
}
```

成功回應：

```json
{
  "protocol_version": "1.0",
  "status": "patch",
  "summary": "加入登入驗證與測試",
  "changed_files": ["src/auth.py", "tests/test_auth.py"],
  "patch": "--- a/src/auth.py\n+++ b/src/auth.py\n...",
  "assumptions": [],
  "verification_notes": []
}
```

缺少上下文時回傳：

```json
{
  "protocol_version": "1.0",
  "status": "blocked",
  "summary": "缺少使用者資料模型",
  "missing_context": ["src/models/user.py"]
}
```

`status=patch` 必須包含非空 patch；`status=blocked` 不得包含 patch。`changed_files` 必須與 diff 路徑完全一致。新增檔案必須事先列在 `authorized_files.create`；否則 DeepSeek 應回傳 `blocked`。

## Patch 安全政策

套用前拒絕：

- 刪除檔案或清空檔案以規避刪除限制。
- 修改或新增未授權檔案。
- 絕對路徑、`../`、repository 外部路徑。
- symlink、submodule、binary patch。
- 更名或移動。
- 格式無效、無法乾淨套用或 `changed_files` 不一致。

所有正規化目標路徑必須位於 repository root 內。

## 修正迴圈與錯誤

初次實作為 round 0；修正 round 為 1 至 3。每輪只傳原始任務、最新相關檔案、規則、授權範圍、當輪審查意見及裁切後的驗證失敗摘要，不傳完整對話歷史。

- timeout、HTTP 429、HTTP 5xx、暫時性連線錯誤：指數退避重試兩次，不計入修正輪次。
- 認證、餘額或無效請求：立即停止。
- 無效 JSON、schema 錯誤或危險 patch：算一次失敗輪次。
- `blocked`：不套用；補充最少上下文後可重送同一輪。
- round 3 後仍失敗：停止 DeepSeek，Codex 接手。

## 設定

```toml
api_key = "sk-..."
base_url = "https://api.deepseek.com"

[models]
fast = "deepseek-v4-flash"
reasoning = "deepseek-v4-pro"

[runtime]
max_revision_rounds = 3
timeout_seconds = 180
transient_retries = 2

[verification]
commands = []
```

第一版不設定或追蹤 token／成本。

## 測試與完成標準

測試涵蓋設定解析、API 重試、非暫時性錯誤、協議驗證、patch 安全、授權路徑、套用衝突、驗證輸出裁切、三輪狀態及保留既有未提交修改。

完成時：

- `$deepseek-cowork` 可觸發流程。
- 全域設定可安全讀取 API key。
- 一般與複雜模式正確路由。
- DeepSeek 僅取得選取的上下文。
- 回應通過協議及 patch 安全檢查。
- 既有未提交修改不被破壞。
- 最多三輪修正，之後 Codex 接手。

第一版不包含 MCP、Plugin、Web UI、自動 commit/push/PR、非 Git 專案、檔案刪除/移動或用量追蹤。
