# -*- coding: utf-8 -*-
"""
TugaFlix Kodi Addon - Main scraper for tugaflix.site
Handles listing pages, taxonomy filters, search and metadata extraction.
"""

from __future__ import absolute_import

import re
import urllib.parse

from resources.lib.constants import BASE_URL
from resources.lib.common import (http_request, http_request_follow, log,
                                  clean_html_entities)
from resources.lib.providers import resolve_movie_url, resolve_episode_url


# <a href="https://tugaflix.site/filmes/slug-2026/" class="poster-overlay">
#   <div class="poster-bottom"><div class="ov-title">Title (2026)</div>...</div>
# </a><img src="https://image.tmdb.org/...jpg" ...>
_GRID_RE = re.compile(
    r'<a\s+href="([^"]+)/(filmes|series)/([^/"]+)/"\s+class="poster-overlay">'
    r'(.*?)</a>\s*<img[^>]+src="([^"]*)"',
    re.DOTALL,
)
_GRID_TITLE_RE = re.compile(r'class="ov-title">([^<]+)</div>')
_GRID_RATING_RE = re.compile(r'IMDb\s*([\d.]+)')
_YEAR_IN_TITLE_RE = re.compile(r'\s*\((\d{4})\)$')
_YEAR_IN_SLUG_RE = re.compile(r'-(\d{4})(?:-vp)?$')

_SELECT_RE = re.compile(r'<select\s+name="(\w+)"[^>]*>(.*?)</select>', re.DOTALL)
_OPTION_RE = re.compile(r'<option\s+value="([^"]+)"\s*>?([^<]*)</option>')

_SEASON_RE = re.compile(
    r'<a\s+href="[^"]*/series/([^/"]+)/(\d+)/"\s+class="btn season-btn')
_SEASON_RE_FALLBACK = re.compile(r'/series/([^/"]+)/(\d+)/')
_EPISODE_RE = re.compile(
    r'<a\s+href="([^"]*/series/([^/"]+)/(\d+)/(\d+)/)"[^>]*>(.*?)</a>', re.DOTALL)
_EPISODE_TITLE_RE = re.compile(r'class="fw-semibold[^"]*">([^<]+)</div>')
_EPISODE_POSTER_RE = re.compile(r'<img[^>]+src="([^"]+)"')
_EPISODE_BADGE_RE = re.compile(r'>E(\d+)<')


class TugaFlixScraper:
    """Scrapes movie/series data from tugaflix.site."""

    def __init__(self):
        self._sitemap_cache = {}
        self._filter_options = None

    # ─── HTTP helpers ──────────────────────────────────────────────

    def _fetch_page(self, path, query=None):
        """
        GET a listing page, following redirects (/filmes/?paged=2 ->
        /filmes/page/2/).

        Returns '' when the page cannot be loaded or does not exist (HTTP 404
        past the end of the pagination) so callers stop instead of falling
        back to a different data source.
        """
        url = f"{BASE_URL}{path}"
        if query:
            pairs = [(k, v) for k, v in query.items() if v not in (None, "")]
            if pairs:
                url = f"{url}?{urllib.parse.urlencode(pairs)}"

        html, code, _final = http_request_follow(url, timeout=30)
        if not html or code != 200:
            log(f"Listing page not available: {url} (code={code})", "debug")
            return ""
        return html

    # ─── Grid parsing ──────────────────────────────────────────────

    def _parse_grid(self, html):
        """
        Parse the poster grid used by every listing/search page.

        Returns list of dicts: title, year, slug, url, poster, rating, type.
        """
        items = []
        seen = set()
        for match in _GRID_RE.finditer(html or ""):
            base, kind, slug, block, poster = match.groups()
            key = (kind, slug)
            if key in seen:
                continue
            seen.add(key)

            title_match = _GRID_TITLE_RE.search(block)
            if title_match:
                title = clean_html_entities(title_match.group(1).strip())
            else:
                title = _prettify_slug(slug)

            rating_match = _GRID_RATING_RE.search(block)
            rating = 0.0
            if rating_match:
                try:
                    rating = float(rating_match.group(1))
                except ValueError:
                    rating = 0.0

            year_match = _YEAR_IN_TITLE_RE.search(title)
            if year_match:
                # "Title (2026)" -> title="Title", year=2026 (evita o ano repetido)
                year = int(year_match.group(1))
                title = title[:year_match.start()].rstrip()
            else:
                year = _year_from_slug(slug)

            items.append({
                'type': 'movie' if kind == 'filmes' else 'series',
                'slug': slug,
                'title': title,
                'year': year,
                'rating': rating,
                'poster': poster,
                'plot': '',
                'url': f"{base.rstrip('/')}/{kind}/{slug}/",
            })
        return items

    # ─── Listing scrapers ──────────────────────────────────────────

    def get_movies_listing(self, page=1, per_page=24, genre=None, year=None,
                           country=None):
        """
        Get a page of movies, optionally filtered by genre/year/country.
        Returns list of dicts with: title, year, slug, url, poster, rating.
        """
        page = int(page)
        query = {'paged': page if page > 1 else ''}
        if genre:
            query['genre'] = genre
        elif year:
            query['ano'] = year
        elif country:
            query['country'] = country

        html = self._fetch_page("/filmes/", query)
        if not html:
            return []

        items = self._parse_grid(html)
        if items:
            return items
        if genre or year or country:
            return []
        # Grid markup unavailable: fall back to the sitemap (no artwork).
        return self._listing_from_sitemap('movie', page, per_page)

    def get_series_listing(self, page=1, per_page=24):
        """Get a page of TV series."""
        page = int(page)
        html = self._fetch_page("/series/", {'paged': page if page > 1 else ''})
        if not html:
            return []

        items = self._parse_grid(html)
        if items:
            return items
        return self._listing_from_sitemap('series', page, per_page)

    def _listing_from_sitemap(self, content_type, page, per_page):
        """Fallback listing built from the WordPress sitemap."""
        all_urls = self._get_all_urls(content_type)
        start = (page - 1) * per_page
        urls = all_urls[start:start + per_page]

        items = []
        for url in urls:
            item = (self._parse_movie_url(url) if content_type == 'movie'
                    else self._parse_series_url(url))
            if item:
                items.append(item)
        return items

    # ─── Taxonomy options (from the site's filter form) ────────────

    def _get_filter_options(self):
        """Parse the filter <select>s of /filmes/ (genre, ano, country)."""
        if self._filter_options is not None:
            return self._filter_options

        options = {'genre': [], 'ano': [], 'country': []}
        html, _code, _ = http_request(f"{BASE_URL}/filmes/", timeout=30)
        if html:
            for name, body in _SELECT_RE.findall(html):
                if name not in options:
                    continue
                options[name] = [(value, clean_html_entities(label).strip())
                                 for value, label in _OPTION_RE.findall(body)
                                 if value]

        self._filter_options = options
        log(f"Filter options: " +
            ", ".join(f"{k}={len(v)}" for k, v in options.items()), "debug")
        return options

    def get_genres(self):
        """Get [(display name, slug)] for every movie genre."""
        return list(self._get_filter_options()['genre'])

    def get_years(self):
        """Get years (most recent first)."""
        years = []
        for value, _label in self._get_filter_options()['ano']:
            if value.isdigit():
                years.append(int(value))
        return sorted(years, reverse=True)

    def get_countries(self):
        """Get [(display name, slug)] for every country."""
        return list(self._get_filter_options()['country'])

    # ─── Sitemap (fallback data source) ────────────────────────────

    def _get_sitemaps(self, content_type):
        """Fetch sitemap index and return relevant sitemap URLs."""
        cache_key = f"index_{content_type}"
        if cache_key in self._sitemap_cache:
            return self._sitemap_cache[cache_key]

        # sitemap.xml redirects to wp-sitemap.xml; use http_request_follow
        text, code, _ = http_request_follow(f"{BASE_URL}/wp-sitemap.xml", timeout=30)
        if not text or code != 200:
            log("Failed to fetch sitemap index", "error")
            return []

        prefix = "/wp-sitemap-posts-filmes-" if content_type == 'movie' \
            else "/wp-sitemap-posts-series-"
        urls = re.findall(r'<loc>([^<]+)</loc>', text)
        relevant = [u for u in urls if prefix in u]
        self._sitemap_cache[cache_key] = relevant
        log(f"Found {len(relevant)} sub-sitemaps for {content_type}", "debug")
        return relevant

    def _get_all_urls(self, content_type):
        """Fetch all URLs from all sitemaps of a given type."""
        cache_key = f"all_urls_{content_type}"
        if cache_key in self._sitemap_cache:
            return self._sitemap_cache[cache_key]

        all_urls = []
        for sm_url in self._get_sitemaps(content_type):
            text, code, _ = http_request_follow(sm_url, timeout=30)
            if text and code == 200:
                all_urls.extend(u.strip()
                                for u in re.findall(r'<loc>([^<]+)</loc>', text))

        self._sitemap_cache[cache_key] = all_urls
        log(f"Total {content_type} URLs: {len(all_urls)}", "info")
        return all_urls

    def _parse_movie_url(self, url):
        """Build a movie item from a sitemap URL (keeps the exact URL)."""
        match = re.search(r'/filmes/([^/]+)/?$', url)
        if not match:
            return None
        slug = match.group(1)
        return {
            'type': 'movie',
            'slug': slug,
            'title': _prettify_slug(slug),
            'year': _year_from_slug(slug),
            'rating': 0,
            'poster': '',
            'plot': '',
            'url': url.rstrip('/') + '/',
        }

    def _parse_series_url(self, url):
        """Build a series item from a sitemap URL (keeps the exact URL)."""
        match = re.search(r'/series/([^/]+)/?$', url)
        if not match:
            return None
        slug = match.group(1)
        return {
            'type': 'series',
            'slug': slug,
            'title': _prettify_slug(slug),
            'year': None,
            'rating': 0,
            'poster': '',
            'plot': '',
            'url': url.rstrip('/') + '/',
        }

    # ─── Season/episode scrapers ───────────────────────────────────

    def get_seasons(self, series_slug):
        """Get the list of season numbers for a series."""
        html, _code, _ = http_request(f"{BASE_URL}/series/{series_slug}/",
                                      timeout=30)
        if not html:
            return [1]  # Fallback to season 1

        seasons = {int(num) for _slug, num in _SEASON_RE.findall(html)}
        if not seasons:
            seasons = {int(num) for slug, num in _SEASON_RE_FALLBACK.findall(html)
                       if slug == series_slug}
        return sorted(seasons) if seasons else [1]

    def get_episodes(self, series_slug, season, series_title=None):
        """Get the list of episodes for a season."""
        html, _code, _ = http_request(
            f"{BASE_URL}/series/{series_slug}/{season}/", timeout=30)
        if not html:
            return []

        items = []
        seen = set()
        for url, slug, _seas, ep_num, block in _EPISODE_RE.findall(html):
            if slug != series_slug or str(_seas) != str(season):
                continue
            ep_num = int(ep_num)
            if ep_num in seen:
                continue
            seen.add(ep_num)

            title_match = _EPISODE_TITLE_RE.search(block)
            title = (clean_html_entities(title_match.group(1).strip())
                     if title_match else f"Episódio {ep_num}")
            poster_match = _EPISODE_POSTER_RE.search(block)

            items.append({
                'slug': series_slug,
                'series_title': series_title or _prettify_slug(series_slug),
                'season': int(season),
                'episode': ep_num,
                'title': title,
                'poster': poster_match.group(1) if poster_match else '',
                'url': url,
                'type': 'episode',
            })

        log(f"{len(items)} episodes for {series_slug} S{season}", "debug")
        return items

    # ─── Search ────────────────────────────────────────────────────

    def search(self, query):
        """
        Search movies and series.

        Uses /filmes/?s= and /series/?s= - the site's own search results
        page (/?s= only renders the home tabs, it has no results).
        """
        query = (query or "").strip()
        if not query:
            return []

        results = []
        seen = set()
        for path in ("/filmes/", "/series/"):
            html, _code, _ = http_request(
                f"{BASE_URL}{path}?s={urllib.parse.quote(query)}", timeout=30)
            if not html:
                continue
            for item in self._parse_grid(html):
                if item['url'] in seen:
                    continue
                seen.add(item['url'])
                results.append(item)

        log(f"Search '{query}': {len(results)} results", "debug")
        return results

    # ─── Resolution ────────────────────────────────────────────────

    def resolve_movie(self, slug, year=None, url=None):
        """Resolve a movie to a direct playable URL plus subtitles.

        Returns dict with 'url' and 'subtitles' keys, or None.
        """
        return resolve_movie_url(slug, year, url=url)

    def resolve_episode(self, slug, season, episode, url=None):
        """Resolve a TV episode to a direct playable URL plus subtitles.

        Returns dict with 'url' and 'subtitles' keys, or None.
        """
        return resolve_episode_url(slug, season, episode, url=url)


def _year_from_slug(slug):
    """Extract a 4 year from the end of a slug (-vp variants included)."""
    match = _YEAR_IN_SLUG_RE.search(slug)
    return int(match.group(1)) if match else None


def _prettify_slug(slug):
    """Convert a URL slug to a human-readable title."""
    slug = _YEAR_IN_SLUG_RE.sub('', slug)
    title = slug.replace('-', ' ').title()
    title = (title.replace(' Do ', ' do ').replace(' Da ', ' da ')
                  .replace(' De ', ' de ').replace(' E ', ' e '))
    if title.endswith(' Vp'):
        title = title[:-3].rstrip()
    return title
