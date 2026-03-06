"""Paid report generation engine — V1.0 redesign.

4 sections, data-driven, no generic advice:
1. Score Breakdown — per-source signal bars
2. Crowd Intelligence — N similar queries, avg score (facts only)
3. Real Competitors — top 10 with activity badges
4. Strategic Analysis — Sonnet LLM, one cohesive analysis
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone

import httpx

sys.path.insert(0, os.path.dirname(__file__))
import db as score_db  # noqa: E402

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Section 1: Score Breakdown — per-source signal bars
# ---------------------------------------------------------------------------


def _build_score_breakdown(signal_result: dict) -> dict:
    """Build per-source breakdown showing where signals came from."""
    score = signal_result.get("reality_signal", 0)
    evidence = signal_result.get("evidence", [])
    dup = signal_result.get("duplicate_likelihood", "unknown")

    # Aggregate signals by source
    sources: dict[str, int] = {}
    for ev in evidence:
        src = ev.get("source", "unknown")
        count = ev.get("count", 0)
        sources[src] = sources.get(src, 0) + count

    total_signals = sum(sources.values()) or 1
    ranked = sorted(sources.items(), key=lambda x: x[1], reverse=True)

    bars = []
    for src, count in ranked:
        pct = round(count / total_signals * 100)
        bars.append({
            "source": src,
            "signals": count,
            "percentage": pct,
        })

    # Score interpretation — factual, no opinion
    explanations = {
        "very_low": "Your idea has very little existing competition — this is rare and promising.",
        "low": "Few direct matches found. The market has room for new entrants.",
        "moderate": "Some existing projects, but meaningful differentiation is possible.",
        "high": "Active projects across multiple sources. Strong differentiation needed.",
        "very_high": "Multiple established projects. Consider a very specific niche or unique angle.",
    }

    if score >= 80:
        level = "very_high"
        summary = f"Very high competition ({score}/100). Multiple established projects exist."
    elif score >= 60:
        level = "high"
        summary = f"High competition ({score}/100). Active projects found across multiple sources."
    elif score >= 40:
        level = "moderate"
        summary = f"Moderate competition ({score}/100). Some existing projects, but room for differentiation."
    elif score >= 20:
        level = "low"
        summary = f"Low competition ({score}/100). Few direct matches found."
    else:
        level = "very_low"
        summary = f"Very low competition ({score}/100). Minimal existing solutions detected."

    return {
        "score": score,
        "level": level,
        "summary": summary,
        "explanation": explanations[level],
        "duplicate_likelihood": dup,
        "source_bars": bars,
        "total_signals": total_signals,
    }


# ---------------------------------------------------------------------------
# Section 2: Crowd Intelligence — facts only, no causal reasoning
# ---------------------------------------------------------------------------


def _build_crowd_intelligence(idea_text: str, idea_hash: str, score: int) -> dict:
    """Query score_history for similar ideas. Report FACTS only.

    Does NOT say 'lower score = entry angles' or any causal claims.
    Just: N queries matched, avg score, depth breakdown.
    """
    # Extract meaningful words for LIKE search
    words = [w.lower() for w in idea_text.split() if len(w) >= 4]
    if not words:
        words = [w.lower() for w in idea_text.split() if len(w) >= 3]

    similar = score_db.search_similar_ideas(
        keywords=words[:5],
        exclude_hash=idea_hash,
        limit=50,
    )

    # Total database size for context
    total_checks = score_db.get_total_checks()

    if not similar:
        return {
            "similar_count": 0,
            "total_database_queries": total_checks,
            "message": (
                f"Your idea is unique among {total_checks} queries in our database. "
                f"No one has searched for anything similar yet."
            ),
        }

    scores = [s["score"] for s in similar]
    avg_score = round(sum(scores) / len(scores), 1)

    # Depth breakdown
    depth_counts = {}
    for s in similar:
        d = s.get("depth", "quick")
        depth_counts[d] = depth_counts.get(d, 0) + 1

    # Score comparison
    if score > avg_score + 10:
        score_comparison = "higher than"
    elif score < avg_score - 10:
        score_comparison = "lower than"
    else:
        score_comparison = "similar to"

    return {
        "similar_count": len(similar),
        "avg_score": avg_score,
        "your_score": score,
        "score_comparison": score_comparison,
        "total_database_queries": total_checks,
        "depth_breakdown": depth_counts,
        "message": (
            f"{len(similar)} people searched for similar ideas. "
            f"Average competition score: {avg_score}/100. "
            f"Your score is {score_comparison} the average."
        ),
    }


# ---------------------------------------------------------------------------
# Section 3: Real Competitors — activity badges
# ---------------------------------------------------------------------------


def _activity_badge(updated_at: str) -> dict:
    """Compute activity badge from GitHub updated_at timestamp.

    🔥 Active: updated < 30 days ago
    🆕 New: (can't determine from updated_at alone, skip)
    💤 Inactive: updated > 180 days ago
    ⚡ Recent: updated 30-180 days ago
    """
    if not updated_at:
        return {"badge": "❓", "label": "unknown", "days_since_update": None}

    try:
        # Parse ISO timestamp (GitHub format: "2026-03-01T12:00:00Z")
        updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        days = (now - updated).days

        if days < 30:
            return {"badge": "🔥", "label": "active", "days_since_update": days}
        elif days < 180:
            return {"badge": "⚡", "label": "recent", "days_since_update": days}
        else:
            return {"badge": "💤", "label": "inactive", "days_since_update": days}
    except Exception:
        return {"badge": "❓", "label": "unknown", "days_since_update": None}


async def _build_competitor_analysis(signal_result: dict) -> list[dict]:
    """Fetch extended competitors from GitHub with activity badges.

    Does NOT touch keyword extraction (out of scope).
    """
    from idea_reality_mcp.sources.github import (
        GITHUB_API,
        _headers,
        _is_noise_repo,
    )

    # Extract query strings from evidence
    keywords: list[str] = []
    for ev in signal_result.get("evidence", []):
        q = ev.get("query", "")
        if q and q not in keywords:
            keywords.append(q)

    if not keywords:
        # Fallback: use top_similars from signal_result
        return [
            {**s, "activity": _activity_badge(s.get("updated", ""))}
            for s in signal_result.get("top_similars", [])[:10]
        ]

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
                        "created": item.get("created_at", ""),
                        "language": item.get("language", ""),
                    })
            except Exception:
                continue

    all_repos = [r for r in all_repos if not _is_noise_repo(r)]

    # Dedupe and sort by (hit_count, stars)
    seen: set[str] = set()
    unique: list[dict] = []
    for repo in sorted(
        all_repos,
        key=lambda r: (repo_hits.get(r["name"], 0), r["stars"]),
        reverse=True,
    ):
        if repo["name"] not in seen:
            seen.add(repo["name"])
            repo["activity"] = _activity_badge(repo.get("updated", ""))
            unique.append(repo)

    return unique[:10]


# ---------------------------------------------------------------------------
# Section 4: Strategic Analysis — Sonnet (paid) / Haiku (free fallback)
# ---------------------------------------------------------------------------

_STRATEGIC_PROMPT = """You are a competitive intelligence analyst writing a paid report section.

Given:
- An idea description
- Competition score and source breakdown
- Real competitor data with activity status
- Crowd intelligence (how many people searched similar ideas)

Write ONE cohesive strategic analysis (400-600 words). Structure:

1. **Competitive Landscape** (2-3 sentences): What does the data tell us? Reference specific competitors by name, their star counts, and activity status.

2. **Market Gaps** (2-3 sentences): Based on the competitors found, what's missing? What do users likely still struggle with? (Infer from the types of projects found, NOT from generic startup advice.)

3. **Positioning Opportunity** (2-3 sentences): Given the crowd data (N people searched similar ideas) and competitor activity, where should this idea position itself?

4. **Key Risk** (1-2 sentences): The single biggest risk based on the actual data, not generic "market risk" statements.

RULES:
- Reference ACTUAL competitor names, star counts, and activity badges from the data provided
- Every claim must tie back to a specific data point
- NO generic startup advice (no "build an MVP", "focus on user feedback", "consider content marketing")
- If data is thin, say so honestly instead of making things up
- Write in the language specified in the Language field
- No markdown headers — use natural paragraph transitions
- No code fences"""

_FALLBACK_ANALYSIS = (
    "Strategic analysis could not be generated at this time. "
    "The data above (competitors, activity badges, and crowd signals) "
    "provides the raw intelligence for your own analysis."
)


async def _generate_strategic_analysis(
    idea_text: str,
    signal_result: dict,
    competitors: list[dict],
    crowd: dict,
    language: str,
) -> str:
    """Call Sonnet for paid report strategic analysis. Falls back to template."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.info("[REPORT] skipped LLM — no ANTHROPIC_API_KEY")
        return _FALLBACK_ANALYSIS

    # Build competitor summary
    comp_lines = []
    for c in competitors[:10]:
        activity = c.get("activity", {})
        badge = activity.get("badge", "")
        days = activity.get("days_since_update")
        days_str = f", last updated {days}d ago" if days is not None else ""
        desc = f" — {c['description'][:100]}" if c.get("description") else ""
        comp_lines.append(
            f"- {badge} {c['name']} ({c.get('stars', 0)}★{days_str}){desc}"
        )
    competitors_text = "\n".join(comp_lines) if comp_lines else "(no competitors found)"

    # Build source breakdown
    breakdown = signal_result.get("evidence", [])
    ev_lines = []
    for ev in breakdown[:8]:
        ev_lines.append(f"- [{ev.get('source', '?')}] {ev.get('detail', '')}")
    evidence_text = "\n".join(ev_lines) if ev_lines else "(no evidence)"

    # Crowd summary
    sim_count = crowd.get("similar_count", 0)
    avg_score = crowd.get("avg_score", 0)
    total_db = crowd.get("total_database_queries", 0)
    crowd_text = (
        f"Database: {total_db} total queries. "
        f"{sim_count} similar queries found, avg score {avg_score}/100."
        if sim_count > 0
        else f"Database: {total_db} total queries. No similar queries found."
    )

    user_prompt = (
        f"Idea: {idea_text}\n"
        f"Reality Signal: {signal_result.get('reality_signal', 0)}/100\n"
        f"Duplicate Likelihood: {signal_result.get('duplicate_likelihood', 'unknown')}\n"
        f"Language: {language}\n\n"
        f"Source Evidence:\n{evidence_text}\n\n"
        f"Competitors:\n{competitors_text}\n\n"
        f"Crowd Intelligence:\n{crowd_text}"
    )

    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=api_key)
        message = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=_STRATEGIC_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return message.content[0].text.strip()

    except Exception:
        logger.exception("[REPORT] Sonnet analysis failed")
        return _FALLBACK_ANALYSIS


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def generate_report(
    idea_text: str,
    signal_result: dict,
    language: str = "en",
) -> dict:
    """Generate a paid report from compute_signal() output.

    Returns dict with keys:
    - score_breakdown: per-source signal bars
    - crowd_intelligence: similar queries data
    - competitors: top 10 with activity badges
    - strategic_analysis: Sonnet-generated cohesive analysis (string)
    """
    idea_h = score_db.idea_hash(idea_text)
    score = signal_result.get("reality_signal", 0)

    score_breakdown = _build_score_breakdown(signal_result)
    crowd = _build_crowd_intelligence(idea_text, idea_h, score)
    competitors = await _build_competitor_analysis(signal_result)
    analysis = await _generate_strategic_analysis(
        idea_text, signal_result, competitors, crowd, language,
    )

    return {
        "score_breakdown": score_breakdown,
        "crowd_intelligence": crowd,
        "competitors": competitors,
        "strategic_analysis": analysis,
    }
