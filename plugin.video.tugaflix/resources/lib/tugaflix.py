# -*- coding: utf-8 -*-
"""
TugaFlix Kodi Addon - Main scraper for tugaflix.site
Handles sitemap parsing, listing pages, and metadata extraction.
"""

from __future__ import absolute_import

import re
import urllib.parse
import xml.etree.ElementTree as ET

from resources.lib.constants import BASE_URL, USER_AGENT
from resources.lib.common import (http_request, http_request_follow, log,
                                  extract_json_from_script, find_iframe_src,
                                  clean_html_entities)
from resources.lib.providers import resolve_movie_url, resolve_episode_url


class TugaFlixScraper:
    """Scrapes movie/series data from tugaflix.site."""

    def __init__(self):
        self._sitemap_cache = {}
        self._sitemap_pages = {}

    # ─── Sitemap management ─────────────────────────────────────────

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

        # Parse sitemap XML for sub-sitemap URLs
        prefix = "/wp-sitemap-posts-filmes-" if content_type == "movie" else "/wp-sitemap-posts-series-"
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

        sitemaps = self._get_sitemaps(content_type)
        all_urls = []
        for sm_url in sitemaps:
            text, code, _ = http_request_follow(sm_url, timeout=30)
            if text and code == 200:
                urls = re.findall(r'<loc>([^<]+)</loc>', text)
                all_urls.extend([u.strip() for u in urls])
                log(f"  Sitemap: {len(urls)} URLs", "debug")

        self._sitemap_cache[cache_key] = all_urls
        log(f"Total {content_type} URLs: {len(all_urls)}", "info")
        return all_urls

    # ─── Listing scrapers ───────────────────────────────────────────

    def get_movies_listing(self, page=1, per_page=24, genre=None, year=None, country=None):
        """
        Get a list of movies with pagination and optional filtering.
        Returns list of dicts with: title, year, slug, poster, rating, plot
        """
        page = int(page)
        all_urls = self._get_all_urls('movie')
        if genre or year or country:
            # Filter via category pages instead
            return self._get_filtered_movies(genre, year, country, page, per_page)

        start = (page - 1) * per_page
        end = start + per_page
        page_urls = all_urls[start:end]

        items = []
        for url in page_urls:
            item = self._parse_movie_url(url)
            if item:
                items.append(item)
        return items

    def _get_filtered_movies(self, genre=None, year=None, country=None, page=1, per_page=24):
        """Get movies filtered by genre/year/country using category pages."""
        # Build the filter URL
        parts = []
        if genre:
            parts.append(f"genre/{genre}")
        if year:
            parts.append(f"year/{year}")
        if country:
            parts.append(f"country/{country}")

        filter_path = "/".join(parts)
        page_url = f"{BASE_URL}/{filter_path}/page/{page}/" if filter_path else f"{BASE_URL}/filmes/page/{page}/"

        html, code, _ = http_request(page_url, timeout=30)
        if not html:
            return []

        return self._parse_movie_grid(html)

    def _parse_movie_url(self, url):
        """Parse a single movie URL to extract slug."""
        match = re.search(r'/filmes/([^/]+)/', url)
        if not match:
            return None

        slug = match.group(1).rstrip('/')
        # Extract year from slug if present (e.g., spider-man-brand-new-day-2026)
        year = None
        year_match = re.search(r'-(\d{4})(-vp)?$', slug)
        if year_match:
            year = int(year_match.group(1))

        # Clean slug: remove year suffix for the URL
        clean_slug = slug
        if year:
            clean_slug = re.sub(r'-(\d{4})(-vp)?$', '', slug)

        return {
            'slug': clean_slug,
            'title': _prettify_slug(slug),
            'year': year,
            'url': url,
        }

    def _parse_movie_grid(self, html):
        """Parse the movie grid from a listing page."""
        items = []
        # Pattern: <a href=".../filmes/{slug}/" ...>Title</a> with poster img
        pattern = r'<a\s+href="([^"]*)/filmes/([^/]+)/"[^>]*class="poster-overlay"><div[^>]*><div[^>]*>([^<]+)</div>'
        for match in re.finditer(pattern, html):
            url, slug, title = match.groups()
            slug = slug.rstrip('/')
            title = clean_html_entities(title)

            # Extract year from slug
            year = None
            m = re.search(r'-(\d{4})(-vp)?$', slug)
            if m:
                year = int(m.group(1))

            clean_slug = re.sub(r'-(\d{4})(-vp)?$', '', slug) if year else slug

            # Extract poster (img after the link)
            poster = ""
            img_match = re.search(r'<img[^>]+src="([^"]+)"', match.group(0) + html[match.end():match.end() + 500])
            if img_match:
                poster = img_match.group(1)

            items.append({
                'slug': clean_slug,
                'title': title,
                'year': year,
                'poster': poster,
                'url': f"https://tugaflix.site/filmes/{slug}/",
            })
        return items

    def get_series_listing(self, page=1, per_page=24):
        """Get a list of TV series with pagination."""
        page = int(page)
        all_urls = self._get_all_urls('series')
        start = (page - 1) * per_page
        end = start + per_page
        page_urls = all_urls[start:end]

        items = []
        for url in page_urls:
            item = self._parse_series_url(url)
            if item:
                items.append(item)
        return items

    def _parse_series_url(self, url):
        """Parse a series episode URL to extract the series slug."""
        match = re.search(r'/series/([^/]+)/', url)
        if not match:
            return None
        slug = match.group(1).rstrip('/')
        # Some URLs include season/episode, we just need the base slug
        return {
            'slug': slug,
            'title': _prettify_slug(slug),
            'url': url,
        }

    # ─── Taxonomy scrapers ──────────────────────────────────────────

    def get_genres(self):
        """Get list of genres from the sitemap taxonomy."""
        # Fetch a sample page with genre links
        html, code, _ = http_request(f"{BASE_URL}/filmes/", timeout=30)
        if not html:
            return []
        # Parse genre links from /genre/{slug}/ URLs
        genres = set()
        for match in re.finditer(r'href="[^"]*/genre/([^/]+)/"', html):
            slug = match.group(1)
            # Extract display name from surrounding text
            # The link text is usually after <a> tag
            start = match.start()
            # Find the text content of the <a> tag
            tag_start = html.rfind('>', 0, start)
            tag_end = html.find('</a>', start)
            if tag_start != -1 and tag_end != -1:
                name = clean_html_entities(html[tag_start+1:tag_end].strip())
                genres.add((name, slug))
        return sorted(genres)

    def get_years(self):
        """Get list of years from the site."""
        html, code, _ = http_request(f"{BASE_URL}/filmes/", timeout=30)
        if not html:
            return []
        years = set()
        for match in re.finditer(r'href="[^"]*/year/(\d{4})/"', html):
            years.add(int(match.group(1)))
        return sorted(years, reverse=True)

    def get_countries(self):
        """Get list of countries from the site."""
        html, code, _ = http_request(f"{BASE_URL}/filmes/", timeout=30)
        if not html:
            return []
        countries = set()
        for match in re.finditer(r'href="[^"]*/country/([^/]+)/"', html):
            slug = match.group(1)
            start = match.start()
            tag_start = html.rfind('>', 0, start)
            tag_end = html.find('</a>', start)
            if tag_start != -1 and tag_end != -1:
                name = clean_html_entities(html[tag_start+1:tag_end].strip())
                countries.add((name, slug))
        return sorted(countries)

    # ─── Season/episode scrapers ────────────────────────────────────

    def get_seasons(self, series_slug):
        """Get list of season numbers for a series."""
        # Fetch the series page
        url = f"{BASE_URL}/series/{series_slug}/"
        html, code, _ = http_request(url, timeout=30)
        if not html:
            return [1]  # Fallback to season 1

        # Find season links: /series/{slug}/{n}/
        seasons = set()
        for match in re.finditer(
            rf'/series/{re.escape(series_slug)}/(\d+)/'.replace('-', '-') + r'"',
            html
        ):
            # The above pattern may not work due to URL escaping; use simpler approach
            pass

        # Simpler: find all /series/{slug}/{N}/ links
        pattern = rf'/series/{re.escape(series_slug)}/(\d+)/'
        for m in re.finditer(pattern, html):
            seasons.add(int(m.group(1)))

        if not seasons:
            # Check for season/episode pattern: /1/1/
            for m in re.finditer(r'/(\d+)/(\d+)/', html):
                seas = int(m.group(1))
                if seas > 0:
                    seasons.add(seas)

        return sorted(seasons) if seasons else [1]

    def get_episodes(self, series_slug, season, series_title=None):
        """Get list of episodes for a season."""
        url = f"{BASE_URL}/series/{series_slug}/{season}/"
        html, code, _ = http_request(url, timeout=30)
        if not html:
            return []

        items = []
        # Pattern: /series/{slug}/{season}/{episode}/
        pattern = rf'/series/{re.escape(series_slug)}/{re.escape(season)}/(\d+)/'
        # Also look for episode links in the page
        for m in re.finditer(pattern, html):
            ep_num = int(m.group(1))
            # Find the episode title near this link
            link_start = m.start()
            # Look for the link text
            tag_match = re.search(r'>([^<]+)</a>', html[link_start:link_start+200])
            ep_title = tag_match.group(1).strip() if tag_match else f"Episódio {ep_num}"
            ep_title = clean_html_entities(ep_title)

            items.append({
                'slug': series_slug,
                'series_title': series_title or _prettify_slug(series_slug),
                'season': int(season),
                'episode': ep_num,
                'title': ep_title,
                'poster': '',
                'type': 'episode',
            })

        return items

    # ─── Search ─────────────────────────────────────────────────────

    def search(self, query):
        """Search for movies and series on TugaFlix."""
        search_url = f"{BASE_URL}/?s={urllib.parse.quote(query)}"
        html, code, _ = http_request(search_url, timeout=30)
        if not html:
            return []

        results = []
        # Movies: /filmes/{slug}/
        for m in re.finditer(r'href="([^"]*)/filmes/([^/]+)/"', html):
            url, slug = m.groups()
            slug = slug.rstrip('/')
            year = None
            ym = re.search(r'-(\d{4})(-vp)?$', slug)
            if ym:
                year = int(ym.group(1))
            results.append({
                'type': 'movie',
                'slug': re.sub(r'-(\d{4})(-vp)?$', '', slug) if year else slug,
                'title': _prettify_slug(slug),
                'year': year,
                'url': url,
            })

        # Series: /series/{slug}/
        for m in re.finditer(r'href="([^"]*)/series/([^/]+)/"', html):
            url, slug = m.groups()
            slug = slug.rstrip('/')
            results.append({
                'type': 'series',
                'slug': slug,
                'title': _prettify_slug(slug),
                'url': url,
            })

        return results

    # ─── Resolution ─────────────────────────────────────────────────

    def resolve_movie(self, slug, year=None):
        """Resolve a movie to a direct playable URL."""
        return resolve_movie_url(slug, year)

    def resolve_episode(self, slug, season, episode):
        """Resolve a TV episode to a direct playable URL."""
        return resolve_episode_url(slug, season, episode)


def _prettify_slug(slug):
    """Convert a URL slug to a human-readable title."""
    # Remove year suffix
    slug = re.sub(r'-(\d{4})(-vp)?$', '', slug)
    # Replace hyphens with spaces, capitalise
    title = slug.replace('-', ' ').title()
    # Handle common patterns
    title = title.replace(' Do ', ' do ').replace(' Da ', ' da ').replace(' De ', ' de ')
    title = title.replace(' E ', ' e ')
    # VP suffix
    if title.endswith(' Vp'):
        title = title[:-3].rstrip()
    return title
