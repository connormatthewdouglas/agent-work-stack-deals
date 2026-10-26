"""Shared, dependency-free deal filtering and ranking (used by MCP server; reusable by site/CLI)."""
from .deals import (PUBLIC_FIELDS, SUMMARY_FIELDS, DealError, FeedLoader, compare, get_deal,
                    public_view, rank_key, search)

__all__ = ["PUBLIC_FIELDS", "SUMMARY_FIELDS", "DealError", "FeedLoader", "compare", "get_deal",
           "public_view", "rank_key", "search"]
