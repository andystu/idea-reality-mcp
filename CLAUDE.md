@.claude/instructions.md

## REST API (Render — 2026-02-26 新增)

- **生產 URL：** `https://idea-reality-mcp.onrender.com`
- **入口：** `api/main.py`（FastAPI wrapper，直接 import scoring engine）
- **端點：**
  - `GET /health` — liveness probe
  - `POST /api/check` — body: `{idea_text, depth}` → 回傳完整 report dict
  - `ANY /mcp` — MCP Streamable HTTP transport（Smithery / MCP HTTP clients 連接用）
- **CORS：** 允許 mnemox.ai、mnemox-ai.github.io、localhost
- **部署：** `render.yaml`（free tier，sleep/wake acceptable）
- **PRODUCTHUNT_TOKEN：** optional，未設時 gracefully skip PH source

## Recent Changes
- [2026-03-15] PayPal 付款修復：credential typo、capture endpoint 加 language 參數、quick mode 不顯示 paywall、付款回來 UX 重寫
- [2026-03-15] Search Quality Improvement: idea expansion (LLM), per-platform queries, relevance filtering. 275 tests
- [2026-03-15] Merged PR #3 (antonio-mello-ai): StackOverflow as 6th data source (deep mode)
- [2026-03-15] Jarvis 系統建立，加入 /morning 掃描範圍

## Current Status
- v0.5.0, 275 tests passing
- PayPal Checkout API 正常運作（sandbox 測試通過）
- 付款回來 UX：隱藏免費結果 → spinner + idea text → 付費報告
- 報告語言：支援 en/zh，透過 capture endpoint language 參數
- PR #2 (shuofengzhang: duplicate keyword fix) 待審
- Google SEO 第一大來源，290+ stars
