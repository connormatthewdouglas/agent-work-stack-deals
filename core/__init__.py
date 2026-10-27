"""Shared, dependency-free deal filtering and ranking (used by MCP server; reusable by site/CLI)."""
from .deals import (USER_AGENT, VERSION, GpuPricesLoader, StackPricingLoader, compare_gpu_prices, gpu_models, PUBLIC_FIELDS, SUMMARY_FIELDS, DealError, FeedLoader, compare, get_deal,
                    public_view, rank_key, search)

__all__ = ["USER_AGENT", "VERSION", "GpuPricesLoader", "StackPricingLoader", "compare_gpu_prices", "gpu_models", "PUBLIC_FIELDS", "SUMMARY_FIELDS", "DealError", "FeedLoader", "compare", "get_deal",
           "public_view", "rank_key", "search"]
