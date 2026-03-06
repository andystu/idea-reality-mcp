"""Tests for paid report generation engine (api/report.py)."""

import json
import os
import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure api/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

import db as score_db  # noqa: E402
import report  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _use_tmp_db(tmp_path, monkeypatch):
    """Use a temporary database for each test."""
    db_path = str(tmp_path / "test_report.db")
    monkeypatch.setattr(score_db, "DB_PATH", db_path)
    score_db.init_db()


SAMPLE_SIGNAL_RESULT = {
    "reality_signal": 65,
    "duplicate_likelihood": "high",
    "evidence": [
        {
            "source": "github",
            "type": "repo_count",
            "query": "code review tool",
            "count": 4500,
            "detail": "4500 repos found across queries",
        },
        {
            "source": "github",
            "type": "max_stars",
            "query": "code review tool",
            "count": 14000,
            "detail": "Top repo has 14000 stars",
        },
        {
            "source": "hackernews",
            "type": "hn_mention_count",
            "query": "code review",
            "count": 87,
            "detail": "87 HN posts",
        },
    ],
    "top_similars": [
        {"name": "semgrep/semgrep", "stars": 14000, "url": "https://github.com/semgrep/semgrep", "description": "Lightweight static analysis"},
        {"name": "reviewdog/reviewdog", "stars": 9000, "url": "https://github.com/reviewdog/reviewdog", "description": "Automated code review"},
    ],
    "pivot_hints": ["hint1", "hint2", "hint3"],
    "meta": {
        "checked_at": "2026-03-06T00:00:00+00:00",
        "sources_used": ["github", "hackernews"],
        "depth": "quick",
        "version": "0.4.0",
    },
}


def _mock_haiku_response(content: str):
    """Create a mock Anthropic message response."""
    msg = MagicMock()
    msg.content = [MagicMock(text=content)]
    return msg


def _make_mock_anthropic(mock_client):
    """Create a fake anthropic module with AsyncAnthropic returning mock_client."""
    fake_mod = ModuleType("anthropic")
    fake_mod.AsyncAnthropic = MagicMock(return_value=mock_client)
    return fake_mod


# ---------------------------------------------------------------------------
# Section 1: score_explanation
# ---------------------------------------------------------------------------

class TestScoreExplanation:
    def test_high_score(self):
        result = report._build_score_explanation(SAMPLE_SIGNAL_RESULT)
        assert result["score"] == 65
        assert "Moderate competition" in result["summary"]
        assert "github" in result["source_contributions"]
        assert result["top_source"] == "github"

    def test_very_high_score(self):
        sr = {**SAMPLE_SIGNAL_RESULT, "reality_signal": 85}
        result = report._build_score_explanation(sr)
        assert "High competition" in result["summary"]

    def test_low_score(self):
        sr = {**SAMPLE_SIGNAL_RESULT, "reality_signal": 15}
        result = report._build_score_explanation(sr)
        assert "Low competition" in result["summary"]

    def test_empty_evidence(self):
        sr = {"reality_signal": 0, "evidence": []}
        result = report._build_score_explanation(sr)
        assert result["score"] == 0
        assert result["top_source"] == "none"
        assert result["source_contributions"] == {}

    def test_multiple_sources_ranked(self):
        sr = {
            "reality_signal": 50,
            "evidence": [
                {"source": "github", "count": 100, "detail": "100 repos"},
                {"source": "hackernews", "count": 500, "detail": "500 posts"},
            ],
        }
        result = report._build_score_explanation(sr)
        assert result["top_source"] == "hackernews"
        sources = list(result["source_contributions"].keys())
        assert sources[0] == "hackernews"


# ---------------------------------------------------------------------------
# Section 2: market_pulse
# ---------------------------------------------------------------------------

class TestMarketPulse:
    def test_no_similar_ideas(self):
        result = report._build_market_pulse("unique quantum widget")
        assert result["similar_count"] == 0

    def test_with_matching_ideas(self):
        # Seed some ideas into the DB
        for i, score in enumerate([40, 50, 60, 70]):
            score_db.save_score(
                idea_text=f"code review tool variant {i}",
                score=score,
                breakdown="{}",
                keywords="[]",
            )
        result = report._build_market_pulse("code review automation")
        assert result["similar_count"] >= 1
        assert result["avg_score"] > 0

    def test_trend_calculation(self):
        # Seed enough data for trend calc (at least 4 rows)
        for score in [30, 35, 70, 75]:
            score_db.save_score(
                idea_text="monitoring dashboard app",
                score=score,
                breakdown="{}",
                keywords="[]",
            )
        result = report._build_market_pulse("monitoring dashboard")
        assert result["trend"] in ("increasing", "decreasing", "stable", "insufficient_data")

    def test_short_idea_text(self):
        result = report._build_market_pulse("ab")
        assert result["similar_count"] == 0
        assert result["trend"] in ("no_data", "insufficient_data")

    def test_empty_idea_text(self):
        result = report._build_market_pulse("")
        assert result["trend"] == "insufficient_data"


# ---------------------------------------------------------------------------
# Section 3: extended_competitors
# ---------------------------------------------------------------------------

class TestExtendedCompetitors:
    @pytest.mark.asyncio
    async def test_returns_repos_from_github(self):
        """Should call GitHub API with per_page=10 and return filtered repos."""
        github_response = {
            "total_count": 100,
            "items": [
                {
                    "full_name": "owner/repo1",
                    "html_url": "https://github.com/owner/repo1",
                    "stargazers_count": 5000,
                    "description": "A great tool for code review",
                    "updated_at": "2026-03-01",
                },
                {
                    "full_name": "owner/repo2",
                    "html_url": "https://github.com/owner/repo2",
                    "stargazers_count": 3000,
                    "description": "Another review tool",
                    "updated_at": "2026-02-15",
                },
            ],
        }

        mock_resp = MagicMock()
        mock_resp.json.return_value = github_response
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await report._fetch_extended_competitors(SAMPLE_SIGNAL_RESULT)

        assert len(result) >= 1
        assert result[0]["name"] == "owner/repo1"
        assert result[0]["stars"] == 5000

    @pytest.mark.asyncio
    async def test_fallback_when_no_keywords(self):
        """Should return top_similars when no keywords in evidence."""
        sr = {
            "reality_signal": 50,
            "evidence": [],
            "top_similars": [{"name": "fallback/repo", "stars": 100}],
        }
        result = await report._fetch_extended_competitors(sr)
        assert len(result) == 1
        assert result[0]["name"] == "fallback/repo"

    @pytest.mark.asyncio
    async def test_handles_http_error(self):
        """Should gracefully handle HTTP errors and return empty list."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Network error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        sr = {
            "reality_signal": 50,
            "evidence": [{"query": "test", "source": "github", "count": 10, "detail": ""}],
            "top_similars": [],
        }

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await report._fetch_extended_competitors(sr)

        assert result == []


# ---------------------------------------------------------------------------
# Sections 4-6: LLM analysis
# ---------------------------------------------------------------------------

class TestLLMAnalysis:
    @pytest.mark.asyncio
    async def test_fallback_without_api_key(self, monkeypatch):
        """Should return fallback template when no ANTHROPIC_API_KEY."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = await report._generate_llm_analysis(
            "test idea", SAMPLE_SIGNAL_RESULT, [], "en",
        )
        assert "differentiation_strategy" in result
        assert "gtm_recommendation" in result
        assert "risk_assessment" in result
        assert "underserved niche" in result["differentiation_strategy"]

    @pytest.mark.asyncio
    async def test_fallback_zh(self, monkeypatch):
        """Should return Chinese fallback when language is zh."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = await report._generate_llm_analysis(
            "測試想法", SAMPLE_SIGNAL_RESULT, [], "zh",
        )
        assert "利基市場" in result["differentiation_strategy"]

    @pytest.mark.asyncio
    async def test_fallback_unknown_lang(self, monkeypatch):
        """Should default to English fallback for unknown languages."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = await report._generate_llm_analysis(
            "test", SAMPLE_SIGNAL_RESULT, [], "ja",
        )
        assert "differentiation_strategy" in result

    @pytest.mark.asyncio
    async def test_successful_llm_call(self, monkeypatch):
        """Should return LLM-generated analysis on success."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        analysis_json = json.dumps({
            "differentiation_strategy": "Focus on X because semgrep lacks Y.",
            "gtm_recommendation": "Launch on Product Hunt first.",
            "risk_assessment": "Market risk: Low. Technical risk: Medium.",
        })

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_haiku_response(analysis_json)
        )

        with patch.dict("sys.modules", {"anthropic": _make_mock_anthropic(mock_client)}):
            result = await report._generate_llm_analysis(
                "AI code review", SAMPLE_SIGNAL_RESULT, [], "en",
            )

        assert "semgrep" in result["differentiation_strategy"]
        assert "Product Hunt" in result["gtm_recommendation"]

    @pytest.mark.asyncio
    async def test_strips_code_fences(self, monkeypatch):
        """Should handle LLM wrapping JSON in code fences."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        fenced = '```json\n' + json.dumps({
            "differentiation_strategy": "diff",
            "gtm_recommendation": "gtm",
            "risk_assessment": "risk",
        }) + '\n```'

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_haiku_response(fenced)
        )

        with patch.dict("sys.modules", {"anthropic": _make_mock_anthropic(mock_client)}):
            result = await report._generate_llm_analysis(
                "test", SAMPLE_SIGNAL_RESULT, [], "en",
            )

        assert result["differentiation_strategy"] == "diff"

    @pytest.mark.asyncio
    async def test_fallback_on_invalid_json(self, monkeypatch):
        """Should fall back to template when LLM returns non-JSON."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_haiku_response("Here is my analysis:\n1. Do X")
        )

        with patch.dict("sys.modules", {"anthropic": _make_mock_anthropic(mock_client)}):
            result = await report._generate_llm_analysis(
                "test", SAMPLE_SIGNAL_RESULT, [], "en",
            )

        assert "underserved niche" in result["differentiation_strategy"]

    @pytest.mark.asyncio
    async def test_fallback_on_missing_keys(self, monkeypatch):
        """Should fall back when LLM returns JSON with missing keys."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        incomplete = json.dumps({"differentiation_strategy": "only this"})
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_haiku_response(incomplete)
        )

        with patch.dict("sys.modules", {"anthropic": _make_mock_anthropic(mock_client)}):
            result = await report._generate_llm_analysis(
                "test", SAMPLE_SIGNAL_RESULT, [], "en",
            )

        assert "gtm_recommendation" in result  # should be fallback

    @pytest.mark.asyncio
    async def test_fallback_on_api_exception(self, monkeypatch):
        """Should fall back when API call throws."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=Exception("API down"))

        with patch.dict("sys.modules", {"anthropic": _make_mock_anthropic(mock_client)}):
            result = await report._generate_llm_analysis(
                "test", SAMPLE_SIGNAL_RESULT, [], "en",
            )

        assert "differentiation_strategy" in result

    @pytest.mark.asyncio
    async def test_passes_language_in_prompt(self, monkeypatch):
        """Should include Language field in the user prompt."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        analysis_json = json.dumps({
            "differentiation_strategy": "策略",
            "gtm_recommendation": "推薦",
            "risk_assessment": "風險",
        })

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_haiku_response(analysis_json)
        )

        with patch.dict("sys.modules", {"anthropic": _make_mock_anthropic(mock_client)}):
            await report._generate_llm_analysis(
                "AI 工具", SAMPLE_SIGNAL_RESULT, [], "zh",
            )

        call_args = mock_client.messages.create.call_args
        user_msg = call_args.kwargs["messages"][0]["content"]
        assert "Language: zh" in user_msg


# ---------------------------------------------------------------------------
# Integration: generate_report()
# ---------------------------------------------------------------------------

class TestGenerateReport:
    @pytest.mark.asyncio
    async def test_returns_all_sections(self, monkeypatch):
        """generate_report should return all 4 top-level keys."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        # Mock extended_competitors to avoid real HTTP calls
        with patch.object(
            report, "_fetch_extended_competitors", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = [
                {"name": "owner/repo", "stars": 1000, "description": "Test repo"},
            ]

            result = await report.generate_report(
                "AI code review tool",
                SAMPLE_SIGNAL_RESULT,
                language="en",
            )

        assert "score_explanation" in result
        assert "market_pulse" in result
        assert "extended_competitors" in result
        assert "llm_analysis" in result

        assert result["score_explanation"]["score"] == 65
        assert isinstance(result["market_pulse"]["similar_count"], int)
        assert isinstance(result["extended_competitors"], list)
        assert "differentiation_strategy" in result["llm_analysis"]

    @pytest.mark.asyncio
    async def test_default_language_is_en(self, monkeypatch):
        """generate_report should default to English."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        with patch.object(
            report, "_fetch_extended_competitors", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = []

            result = await report.generate_report(
                "test idea", SAMPLE_SIGNAL_RESULT,
            )

        assert "underserved niche" in result["llm_analysis"]["differentiation_strategy"]
