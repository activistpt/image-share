# -*- coding: utf-8 -*-
"""
TugaFlix Kodi Addon - Sitemap parsing utilities.
Handles discovery of all movie/series URLs via WordPress sitemaps.
"""

from __future__ import absolute_import

import re
import gzip
import io
import urllib.parse
import urllib.request

from resources.lib.constants import BASE_URL, SITEMAP_FILMES, SITEMAP_SERIES
from resources.lib.common import log, http_request_follow


def _fetch_sitemap(url):
    """Fetch and parse a sitemap XML, returning list of URLs."""
    text, code, _ = http_request_follow(url, timeout=30)
    if not text or code != 200:
        log(f"Failed to fetch sitemap: {url} (code={code})", "error")
        return []

    # Handle gzipped sitemaps
    urls = re.findall(r'<loc>(.*?)</loc>', text, re.DOTALL)
    return [u.strip() for u in urls]


def get_sitemap_urls(sitemap_type="filmes"):
    """
    Get all URLs from sitemaps of a given type.
    Returns list of full URLs to movie/series pages.
    """
    # First, get the sitemap index to find all sitemap pages
    index_urls = _fetch_sitemap(f"{BASE_URL}/wp-sitemap.xml")
    target_prefix = SITEMAP_FILMES if sitemap_type == "filmes" else SITEMAP_SERIES

    all_urls = []
    for sitemap_url in index_urls:
        if target_prefix in sitemap_url:
            urls = _fetch_sitemap(sitemap_url)
            all_urls.extend(urls)
            log(f"Fetched {len(urls)} URLs from {sitemap_url}", "debug")

    log(f"Total {sitemap_type} URLs: {len(all_urls)}", "info")
    return all_urls


class SitemapScraper:
    """Provides access to sitemap-based URLs with pagination."""

    _CACHE = {}

    @classmethod
    def get_urls(cls, content_type, page=1, per_page=24):
        """Get paginated list of URLs for movies or series."""
        cache_key = f"sitemap_{content_type}"
        if cache_key not in cls._CACHE:
            if content_type == "movie":
                cls._CACHE[cache_key] = get_sitemap_urls("filmes")
            else:
                cls._CACHE[cache_key] = get_sitemap_urls("series")

        all_urls = cls._CACHE[cache_key]
        start = (page - 1) * per_page
        end = start + per_page
        return all_urls[start:end]

    @classmethod
    def clear_cache(cls):
        cls._CACHE = {}
