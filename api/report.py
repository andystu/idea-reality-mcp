"""Paid report generation engine.

Produces a structured report from compute_signal() output, including:
1. score_explanation — why this score, which sources contributed most
2. market_pulse — similar ideas from score_history DB
3. extended_competitors — GitHub repos (per_page=10)
4-6. llm_analysis — differentiation_strategy, gtm_recommendation, risk_assessment
"""

from __future__ import annotations

import json
import logging
import os
import sys

import httpx

# api/ on sys.path so we can import db
sys.path.insert(0, os.path.dirname(__file__))
import db as score_db  # noqa: E402

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Section 1: Score explanation
# ---------------------------------------------------------------------------

def _build_score_explanation(signal_result: dict) -> dict:
    """Explain why the idea got this score, which sources contributed most."""
    score = signal_result.get("reality_signal", 0)
    evidence = signal_result.get("evidence", [])

    # Group evidence by source
    source_contributions: dict[str, dict] = {}
    for ev in evidence:
        src = ev.get("source", "unknown")
        count = ev.get("count", 0)
        if src not in source_contributions:
            source_contributions[src] = {"total_signals": 0, "details": []}
        source_contributions[src]["total_signals"] += count
        source_contributions[src]["details"].append(ev.get("detail", ""))

    ranked = sorted(
        source_contributions.items(),
        key=lambda x: x[1]["total_signals"],
        reverse=True,
    )

    top_source = ranked[0][0] if ranked else "none"

    if score >= 70:
        summary = (
            f"High competition detected (score: {score}/100). "
            f"The '{top_source}' source contributed the strongest signals."
        )
    elif score >= 40:
        summary = (
            f"Moderate competition exists (score: {score}/100). "
            f"Most signals came from '{top_source}'."
        )
    else:
        summary = (
            f"Low competition detected (score: {score}/100). "
            f"Limited signals found across all sources."
        )

    return {
        "score": score,
        "summary": summary,
        "source_contributions": {
            src: {"total_signals": d["total_signals"], "details": d["details"]}
            for src, d in ranked
        },
        "top_source": top_source,
    }


# ---------------------------------------------------------------------------
# Section 2: Market pulse — similar ideas from score_history
# ---------------------------------------------------------------------------

def _build_market_pulse(idea_text: str) -> dict:
    """Query score_history for similar ideas using keyword LIKE search."""
    words = [w.lower() for w in idea_text.split() if len(w) >= 4]
    if not words:
        words = [w.lower() for w in idea_text.split() if len(w) >= 2]

    if not words:
        return {"similar_count": 0, "avg_score": 0, "trend": "insufficient_data"}

    try:
        conn = score_db._get_conn()
        # OR-match any keyword (cap at 5 to keep query bounded)
        conditions = " OR ".join(["idea_text LIKE ?"] * min(len(words), 5))
        params = [f"%{w}%" for w in words[:5]]

        rows = conn.execute(
            f"SELECT score, created_at FROM score_history "
            f"WHERE {conditions} ORDER BY created_at DESC LIMIT 50",
            params,
        ).fetchall()
        conn.close()

        if not rows:
            return {"similar_count": 0, "avg_score": 0, "trend": "no_data"}

        scores = [row["score"] for row in rows]
        similar_count = len(scores)
        avg_score = round(sum(scores) / len(scores), 1)

        # Trend: newer half vs older half
        if len(scores) >= 4:
            mid = len(scores) // 2
            newer_avg = sum(scores[:mid]) / mid
            older_avg = sum(scores[mid:]) / (len(scores) - mid)
            if newer_avg > older_avg + 5:
                trend = "increasing"
            elif newer_avg < older_avg - 5:
                trend = "decreasing"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"

        return {
            "similar_count": similar_count,
            "avg_score": avg_score,
            "trend": trend,
        }
    except Exception:
        logger.exception("market_pulse query failed")
        return {"similar_count": 0, "avg_score": 0, "trend": "error"}


# ---------------------------------------------------------------------------
# Section 3: Extended competitors — GitHub search with per_page=10
# ---------------------------------------------------------------------------

async def _fetch_extended_competitors(signal_result: dict) -> list[dict]:
    """Fetch extended competitor list from GitHub with per_page=10."""
    from idea_reality_mcp.sources.github import (
        GITHUB_API,
        _headers,
        _is_noise_repo,
    )

    # Extract unique query strings from evidence
    keywords: list[str] = []
    for ev in signal_result.get("evidence", []):
        q = ev.get("query", "")
        if q and q not in keywords:
            keywords.append(q)

    if not keywords:
        return signal_result.get("top_similars", [])[:10]

    all_repos: list[dict] = []
    repo_hits: dict[str, int] = {}

    async with httpx.AsyncClient(timeout=15.0) as client:
        for query in keywords[:3]:
            try:
                resp = await client.get(
                    GITHUB_API,
                    params={
                        "q": query,
                        "sort": "stars",
                        "order": "desc",
                        "per_page": 10,
                    },
                    headers=_headers(),
                )
                resp.raise_for_status()
                data = resp.json()

                for item in data.get("items", []):
                    name = item.get("full_name", "")
                    if not name:
                        continue
                    repo_hits[name] = repo_hits.get(name, 0) + 1
                    all_repos.append({
                        "name": name,
                        "url": item.get("html_url", ""),
                        "stars": item.get("stargazers_count", 0),
                        "description": (item.get("description") or "")[:300],
                        "updated": item.get("updated_at", ""),
                    })
            except Exception:
                continue

    all_repos = [r for r in all_repos if not _is_noise_repo(r)]

    seen: set[str] = set()
    unique: list[dict] = []
    for repo in sorted(
        all_repos,
        key=lambda r: (repo_hits.get(r["name"], 0), r["stars"]),
        reverse=True,
    ):
        if repo["name"] not in seen:
            seen.add(repo["name"])
            unique.append(repo)

    return unique[:10]


# ---------------------------------------------------------------------------
# Sections 4-6: LLM analysis (Haiku 4.5)
# ---------------------------------------------------------------------------

_REPORT_SYSTEM_PROMPT = (
    "You are a startup strategist generating a paid competitive analysis report.\n"
    "Given an idea, its reality signal score, and competitor data, produce a structured analysis.\n\n"
    "Output ONLY a JSON object with exactly 3 keys:\n"
    '- "differentiation_strategy": 2-3 paragraphs on how to differentiate from competitors. '
    "Reference specific competitor names.\n"
    '- "gtm_recommendation": 2-3 paragraphs on go-to-market strategy. '
    "Include channels, pricing, and launch tactics.\n"
    '- "risk_assessment": 2-3 paragraphs assessing market, technical, and competitive risks. '
    "Rate each as low/medium/high.\n\n"
    "Rules:\n"
    "- Reference actual competitor names and data\n"
    "- Be specific and actionable\n"
    "- No markdown in values — plain text with line breaks\n"
    "- If the language field is not 'en', write the entire analysis in that language\n"
    "- No code fences around the JSON"
)

_FALLBACK_ANALYSIS = {
    "en": {
        "differentiation_strategy": (
            "Based on the competitive landscape, consider focusing on an underserved niche "
            "or user segment that existing solutions overlook. Look at competitor issue trackers "
            "and user reviews to identify recurring pain points that remain unaddressed. "
            "A vertical-specific solution often outperforms general-purpose tools in conversion."
        ),
        "gtm_recommendation": (
            "Start with a focused launch targeting early adopters in developer communities "
            "(Hacker News, Reddit, Product Hunt). Offer a generous free tier to build initial "
            "traction, then convert power users to paid plans. Consider content marketing through "
            "technical blog posts that demonstrate your unique approach."
        ),
        "risk_assessment": (
            "Market risk: Medium — competition exists but gaps remain. "
            "Technical risk: Depends on implementation complexity and team capability. "
            "Competitive risk: Established players may add similar features. "
            "Move fast and focus on user feedback loops to stay ahead."
        ),
    },
    "zh": {
        "differentiation_strategy": (
            "根據競爭格局分析，建議聚焦在現有解決方案忽略的利基市場或使用者群體。"
            "檢視競品的 issue tracker 和使用者評論，找出反覆出現但未被解決的痛點。"
            "垂直領域的專精方案通常在轉換率上優於通用型工具。"
        ),
        "gtm_recommendation": (
            "先針對開發者社群中的早期採用者進行精準發布（Hacker News、Reddit、Product Hunt）。"
            "提供寬裕的免費方案以建立初始用戶基礎，再將重度用戶轉化為付費方案。"
            "透過技術部落格文章展示你的獨特方法，進行內容行銷。"
        ),
        "risk_assessment": (
            "市場風險：中等 — 存在競爭但仍有空缺。"
            "技術風險：取決於實作複雜度和團隊能力。"
            "競爭風險：既有玩家可能新增類似功能。"
            "快速行動並專注於使用者回饋循環以保持領先。"
        ),
    },
}


async def _generate_llm_analysis(
    idea_text: str,
    signal_result: dict,
    competitors: list[dict],
    language: str,
) -> dict:
    """Call Haiku 4.5 for structured analysis. Falls back to template on failure."""
    # Normalize language for fallback lookup: zh-TW, zh-CN → zh
    _fb_lang = "zh" if language.startswith("zh") else language

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.info("[REPORT] skipped LLM — no ANTHROPIC_API_KEY")
        return dict(_FALLBACK_ANALYSIS.get(_fb_lang, _FALLBACK_ANALYSIS["en"]))

    comp_lines = []
    for c in competitors[:10]:
        stars = f" ({c['stars']} stars)" if c.get("stars") else ""
        desc = f" — {c['description']}" if c.get("description") else ""
        comp_lines.append(f"- {c['name']}{stars}{desc}")
    competitors_text = "\n".join(comp_lines) if comp_lines else "(none found)"

    ev_lines = []
    for ev in signal_result.get("evidence", [])[:10]:
        ev_lines.append(f"- [{ev.get('source', '?')}] {ev.get('detail', '')}")
    evidence_text = "\n".join(ev_lines) if ev_lines else "(no evidence)"

    user_prompt = (
        f"Idea: {idea_text}\n"
        f"Reality Signal: {signal_result.get('reality_signal', 0)}/100\n"
        f"Duplicate Likelihood: {signal_result.get('duplicate_likelihood', 'unknown')}\n"
        f"Language: {language}\n\n"
        f"Competitors:\n{competitors_text}\n\n"
        f"Evidence:\n{evidence_text}"
    )

    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=api_key)
        message = await client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1500,
            system=_REPORT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        raw = message.content[0].text.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            raw = "\n".join(lines).strip()

        analysis = json.loads(raw)

        required = {"differentiation_strategy", "gtm_recommendation", "risk_assessment"}
        if not isinstance(analysis, dict) or not required.issubset(analysis.keys()):
            logger.warning("[REPORT] LLM returned incomplete keys")
            return dict(_FALLBACK_ANALYSIS.get(_fb_lang, _FALLBACK_ANALYSIS["en"]))

        return {
            "differentiation_strategy": str(analysis["differentiation_strategy"]),
            "gtm_recommendation": str(analysis["gtm_recommendation"]),
            "risk_assessment": str(analysis["risk_assessment"]),
        }

    except json.JSONDecodeError:
        logger.warning("[REPORT] LLM returned non-JSON")
        return dict(_FALLBACK_ANALYSIS.get(_fb_lang, _FALLBACK_ANALYSIS["en"]))
    except Exception:
        logger.exception("[REPORT] LLM analysis failed")
        return dict(_FALLBACK_ANALYSIS.get(_fb_lang, _FALLBACK_ANALYSIS["en"]))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_report(
    idea_text: str,
    signal_result: dict,
    language: str = "en",
) -> dict:
    """Generate a paid report from compute_signal() output.

    Args:
        idea_text: The original idea description.
        signal_result: Return value of ``compute_signal()``.
        language: Output language ('en' or 'zh').

    Returns:
        Dict with keys: score_explanation, market_pulse,
        extended_competitors, llm_analysis.
    """
    score_explanation = _build_score_explanation(signal_result)
    market_pulse = _build_market_pulse(idea_text)
    extended_competitors = await _fetch_extended_competitors(signal_result)
    llm_analysis = await _generate_llm_analysis(
        idea_text, signal_result, extended_competitors, language,
    )

    return {
        "score_explanation": score_explanation,
        "market_pulse": market_pulse,
        "extended_competitors": extended_competitors,
        "llm_analysis": llm_analysis,
    }
