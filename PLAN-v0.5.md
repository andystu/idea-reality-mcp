# idea-reality-mcp v0.5 PLAN — Temporal Signals + Score Recalibration

## 現狀診斷

### 分數分布（n=1,696）
```
 0-29:  111 ( 6.5%)  ████
30-59:  556 (32.8%)  █████████████████
60-74:  482 (28.4%)  ███████████████    ← 最大群，全部擠在一起
75-79:   46 ( 2.7%)  ██                 ← 谷底（threshold 跳躍）
80-89:  247 (14.6%)  ████████
90-94:  254 (15.0%)  ████████           ← 不自然 spike（天花板效應）
```

### 根因
1. **Sub-score 全部 cap 在 90** → 高競爭 idea 全部擠在 90，無法區分「很多人做」vs「超級飽和」
2. **Threshold-based 跳躍** → repos 從 50→51 跳 40→60 分，75-79 出現斷崖
3. **缺少時間維度** → 500 個 repo（全部 3 年前的廢棄項目）跟 500 個 repo（每月都有新的）得到同樣分數
4. **quick 比 deep 平均高 9 分** → deep 加了更多 source 後分數被稀釋降低，但用戶期望 deep = 更好 ≠ 更低

### 已有但未使用的時間數據
| Source | 欄位 | 狀態 | 成本 |
|--------|------|------|------|
| GitHub | `updated_at` | ✅ 已 fetch | 零成本 |
| Product Hunt | `createdAt` | ✅ 已 fetch | 零成本 |
| HN | individual `created_at_i` | ✅ 在 response 裡 | 需解析 |
| npm | created/modified | ❌ 需額外 API call | 中等 |
| PyPI | created/modified | ❌ 需 scrape 個別頁面 | 高 |

---

## 四維辯論

### 維度 1：產品價值（Product Value）

**正方：Temporal signals 是殺手級差異化**
- 市面上沒有任何 idea checker 告訴你「這個市場是在加速還是在死亡」
- 用戶最痛的問題不是「有沒有人做過」，而是「現在進場還有沒有機會」
- Temporal signal 直接回答第二個問題：recent_ratio 高 = 市場在爆發（可能是好時機也可能是紅海）
- 分數從單一維度（量）變成二維（量 × 時間趨勢），報告價值跳升

**反方：用戶真的看得懂嗎？**
- 目前用戶 70% 用 quick mode，看完分數就走
- 加了 temporal signal 但用戶不知道怎麼解讀 = 白做
- 風險：over-engineer，用戶只想要「做/不做」的簡單答案

**結論：做。但 temporal signal 必須直接影響主分數，不能只是附加指標。用戶不需要理解「recent_ratio=0.4」，只需要看到分數從 65 變成 72（trending up）或 58（stale market）。**

### 維度 2：技術可行性（Technical Feasibility）

**低成本（零額外 API call）：**
- GitHub `updated_at`：已經 fetch 5 repos per query，直接算 recently_updated_ratio
- Product Hunt `createdAt`：已經 fetch，直接算 recently_launched_ratio
- HN `created_at_i`：需要改 hn.py 解析 individual hits（目前只取 nbHits count）

**中等成本：**
- GitHub `created_at`：search API 不回傳 created_at，需要改 query 加 `created:>2025-01-01` filter 做兩次查詢（total vs recent）
  - 替代方案：GitHub search 支援 `created:>YYYY-MM-DD` 作為 query filter，可以跑兩次 search 比較

**高成本（不做）：**
- npm/PyPI temporal：需要額外 API call，rate limit 風險，ROI 不明確

**結論：Phase 1 只做零成本 + GitHub created filter（一次額外 search call），不碰 npm/PyPI。**

### 維度 3：商業影響（Business Impact）

**正方：更好的分數 = 更高轉換**
- 分數鑑別力提高 → 報告更有價值 → 付費意願上升
- 「Trending」標籤 = 情緒驅動，比數字更能促進付費
- Deep mode 可以拿到更多 temporal data = deep 報告更值得付費

**反方：分數改了舊數據怎麼辦？**
- 1,696 筆歷史數據的分數會跟新分數不可比
- 同一個 idea 重查分數不同 → 用戶困惑
- score_history 功能建立在分數可比的前提上

**結論：接受 breaking change。v0.5 分數不跟 v0.4 可比，在 CHANGELOG 明確說明。score_history 加 version 欄位。**

### 維度 4：風險（Risk）

**R1：GitHub API rate limit**
- 目前每次 query 3-8 個 keyword variant × 1 call = 3-8 calls
- 加 created filter 要 ×2 = 6-16 calls
- GitHub unauthenticated: 10 req/min，authenticated: 30 req/min
- 風險等級：🟡 中。日均 150-240 queries × 8 = ~1,200-1,920 calls/day，authenticated 應該夠

**R2：Scoring formula regression**
- 改了公式可能讓某些 edge case 分數變得荒謬
- 緩解：跑 1,696 筆歷史 idea 的 before/after 比較（dry run）

**R3：HN 解析改動可能破壞現有功能**
- 目前只取 count，改成解析 individual hits 需要測試
- 緩解：加 tests，graceful fallback

---

## 實作計畫

### Task 1：GitHub Temporal Signal（sources/github.py）
- 對每個 keyword query，額外跑一次 `created:>6months_ago` filter
- 計算 `recent_created_ratio = recent_repos / total_repos`
- 回傳新欄位 `recently_created_count` + `recent_ratio`
- 用已有的 `updated_at` 計算 `recently_updated_ratio`（6 個月內 update 的 / total）

### Task 2：HN Temporal Signal（sources/hn.py）
- 解析 individual hits 的 `created_at_i`
- 計算 `recent_mention_ratio`（最近 3 個月 / 總 12 個月）
- 新欄位加到 return dict

### Task 3：Product Hunt Temporal Signal（sources/producthunt.py）
- 用已有的 `createdAt` 計算 `recent_launch_ratio`
- 零成本，純邏輯改動

### Task 4：Score Recalibration（scoring/engine.py）
- **Sub-score 上限 90 → 100**（解決天花板）
- **Threshold → 連續函數**：用 log curve 取代跳躍式分數
  - `score = min(100, k * log(1 + count))`
  - k 校準到：1 repo=10, 10 repos=30, 50 repos=55, 200 repos=75, 1000 repos=95
- **加入 temporal modifier**：
  - `temporal_boost = (recent_ratio - 0.5) * 20`（-10 到 +10）
  - recent_ratio > 0.5 = 市場加速（+boost）
  - recent_ratio < 0.5 = 市場減速（-penalty）
  - 直接加到 final signal 上
- **新 sub_scores 欄位**：
  - `market_momentum`: 0-100（based on all temporal signals）
- **新 output 欄位**：
  - `trend`: "accelerating" | "stable" | "declining"

### Task 5：Evidence 強化
- evidence 加 `temporal` type entries
- 例：`"GitHub: 45% of repos created in last 6 months (accelerating)"`

### Task 6：Tests + Dry Run
- 新增 temporal signal tests（每個 source）
- 新增 score recalibration tests（連續函數 vs 舊 threshold）
- Dry run：用 1,696 筆歷史 keywords 跑 before/after 分數比較（不打 API，用 mock）
- 目標：分數 std 從 ~18 提高到 ~25（更分散）

### Task 7：Version Bump + Release
- pyproject.toml → 0.5.0
- CHANGELOG.md
- score_history 加 `version` 欄位
- api/main.py version string
- PyPI publish

---

## 預期效果

| 指標 | v0.4（現在） | v0.5（目標） |
|------|------------|------------|
| 分數 std | ~18 | ~25 |
| 90 分 spike | 15%（254 筆） | <5% |
| 75-79 谷底 | 2.7% | 消除 |
| 新維度 | 無 | market_momentum + trend |
| Deep 獨有價值 | 只多 3 source | + temporal analysis |

---

## auto-claude tasks.txt

```
# idea-reality v0.5 — Temporal Signals + Score Recalibration
# 每個 task 獨立自足，按順序執行

# Task 1: GitHub temporal signal
Read C:/Users/johns/projects/idea-reality-mcp/src/idea_reality_mcp/sources/github.py completely. Add a second search query per keyword with `created:>YYYY-MM-DD` (6 months ago) to get recent_created_count. Use existing `updated_at` field from the 5 repos to calculate recently_updated_ratio (repos updated within 6 months / total). Return new fields: recent_created_count, recent_ratio, recently_updated_ratio. Do NOT break existing return format — add new keys alongside existing ones. Run tests after: C:/Users/johns/.local/bin/uv.exe run pytest tests/ -v

# Task 2: HN temporal signal
Read C:/Users/johns/projects/idea-reality-mcp/src/idea_reality_mcp/sources/hn.py completely. Currently only uses nbHits (total count). Parse the individual hits array to extract created_at_i timestamps. Calculate recent_mention_ratio = mentions in last 3 months / total mentions in 12 months. Return new field: recent_mention_ratio. Graceful fallback: if parsing fails, return recent_mention_ratio=None. Run tests after: C:/Users/johns/.local/bin/uv.exe run pytest tests/ -v

# Task 3: Product Hunt temporal signal
Read C:/Users/johns/projects/idea-reality-mcp/src/idea_reality_mcp/sources/producthunt.py completely. The createdAt field is already fetched in GraphQL response. Calculate recent_launch_ratio = products launched in last 6 months / total products. Return new field: recent_launch_ratio. Run tests after: C:/Users/johns/.local/bin/uv.exe run pytest tests/ -v

# Task 4: Score recalibration — continuous function
Read C:/Users/johns/projects/idea-reality-mcp/src/idea_reality_mcp/scoring/engine.py completely (especially compute_signal and the threshold functions). Replace threshold-based scoring with log-curve continuous function: score = min(100, k * log(1 + count)). Calibrate k per source so that: GitHub repos (1→10, 10→30, 50→55, 200→75, 1000→95), GitHub stars (10→15, 100→35, 500→55, 1000→70, 10000→95), HN mentions (1→15, 5→30, 15→55, 30→75, 100→95), npm/PyPI packages (1→10, 5→25, 20→45, 100→70, 500→95), ProductHunt (1→15, 3→30, 10→50, 30→70, 100→95). Remove the old if/elif threshold blocks. Sub-score cap change from 90 to 100. Run tests after: C:/Users/johns/.local/bin/uv.exe run pytest tests/ -v — expect MANY test failures because expected scores changed. Update test expected values to match new formula.

# Task 5: Integrate temporal signals into final score
Read C:/Users/johns/projects/idea-reality-mcp/src/idea_reality_mcp/scoring/engine.py compute_signal function. Add temporal_boost calculation: collect recent_ratio from GitHub, recent_mention_ratio from HN, recent_launch_ratio from PH. Average available ratios into market_momentum (0-1). temporal_boost = (market_momentum - 0.5) * 20 (range: -10 to +10). Add temporal_boost to final signal before clamping. Add new sub_scores key "market_momentum" (0-100, = market_momentum * 100). Add new output field "trend": "accelerating" if momentum > 0.6, "declining" if < 0.3, "stable" otherwise. Add temporal evidence entries. Run tests: C:/Users/johns/.local/bin/uv.exe run pytest tests/ -v

# Task 6: Update tools.py to pass temporal data through
Read C:/Users/johns/projects/idea-reality-mcp/src/idea_reality_mcp/tools.py. Ensure the temporal fields from sources are passed through to compute_signal. Update quick mode and deep mode source calls if needed. Run tests: C:/Users/johns/.local/bin/uv.exe run pytest tests/ -v

# Task 7: Add new tests for temporal signals and score recalibration
Read existing tests in C:/Users/johns/projects/idea-reality-mcp/tests/. Add tests: (a) GitHub temporal — mock response with updated_at dates, verify recent_ratio calculation. (b) HN temporal — mock response with created_at_i timestamps, verify recent_mention_ratio. (c) PH temporal — mock response with createdAt dates, verify recent_launch_ratio. (d) Score recalibration — verify continuous function produces expected scores at calibration points (within ±3). (e) Temporal boost — verify momentum > 0.6 adds positive boost, < 0.3 adds negative. (f) Trend label — verify "accelerating"/"stable"/"declining" thresholds. Target: all existing + new tests pass. Run: C:/Users/johns/.local/bin/uv.exe run pytest tests/ -v

# Task 8: Version bump + changelog
Update C:/Users/johns/projects/idea-reality-mcp/pyproject.toml version to 0.5.0. Update C:/Users/johns/projects/idea-reality-mcp/api/main.py version string if any. Update C:/Users/johns/projects/idea-reality-mcp/src/idea_reality_mcp/scoring/engine.py version in meta output. Write CHANGELOG entry for v0.5.0 at top of C:/Users/johns/projects/idea-reality-mcp/CHANGELOG.md: Added temporal signals (GitHub recency, HN trend, PH launch timing), continuous scoring function (replaces threshold-based), market_momentum sub-score, trend indicator. Changed: score formula (v0.5 scores not comparable to v0.4). Run final tests: C:/Users/johns/.local/bin/uv.exe run pytest tests/ -v. Then git add -A && git commit -m "feat: v0.5.0 temporal signals + score recalibration"
```
