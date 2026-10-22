# -*- coding: utf-8 -*-
"""
TugaFlix Kodi Addon - Provider resolution dispatch.
"""

from __future__ import absolute_import

import urllib.parse

from resources.lib.providers.streamtape import StreamtapeResolver
from resources.lib.common import http_request, http_request_follow, clean_html_entities, log
from resources.lib.constants import PROVIDERS

_REFERER = "https://tugaflix.site/"
_REDIRECT_CODES = (301, 302, 303, 307, 308)


def _post(url, data):
    """
    POST and follow redirects to the real page.

    Some legacy slugs redirect on GET but answer POST with a 404, so on 404
    the canonical URL is resolved with a redirect-following GET first.
    """
    from resources.lib.constants import USER_AGENT

    headers = {"User-Agent": USER_AGENT, "Referer": _REFERER}
    current = url
    for _ in range(4):
        html, code, final = http_request(current, method="POST", data=data,
                                         headers=headers, timeout=30)
        if code in _REDIRECT_CODES and final and final != current:
            current = final
            continue
        if code == 404:
            _text, _code, canonical = http_request_follow(current, timeout=30)
            if canonical and canonical != current:
                log(f"Following canonical URL: {canonical}", "debug")
                current = canonical
                continue
            return None, code, current
        return html, code, current
    return html, code, current


def _extract_subtitles(streamtape_url):
    """
    Extract subtitle URL(s) from a Streamtape embed URL.

    The TugaFlix player passes Portuguese subtitles via the c1_file
    query parameter on the Streamtape embed URL.  For movies the path
    is /sub/ and for TV episodes it is /substv/.

    Returns a list of subtitle URLs (may be empty when no subs exist).
    """
    if not streamtape_url or '?' not in streamtape_url:
        return []
    try:
        parsed = urllib.parse.urlparse(streamtape_url)
        params = urllib.parse.parse_qs(parsed.query)
        c1_file = params.get('c1_file', [])
        if c1_file and c1_file[0].startswith('http'):
            log(f"Found Portuguese subtitles: {c1_file[0][:80]}...", "debug")
            return [c1_file[0]]
    except Exception as e:
        log(f"Error extracting subtitles: {e}", "warning")
    return []


def resolve_movie_url(slug, year=None, url=None):
    """
    Resolve a movie to a direct playable URL plus Portuguese subtitles.

    Flow:
      1. POST to the movie page with server_name=st1 (Streamtape)
      2. Extract the iframe src pointing to tuga.best/player/movie.php
      3. POST start_video=1 to get the Streamtape embed iframe
      4. Resolve the Streamtape embed to a direct MP4 URL
      5. Extract subtitle URL from the c1_file parameter of the embed

    Returns:
      dict with 'url' (direct media URL) and 'subtitles' (list of URLs),
      or None on failure.
    """
    from resources.lib.constants import BASE_URL

    if url:
        movie_url = url
    else:
        movie_url = f"{BASE_URL}/filmes/{slug}/"
        if year:
            movie_url = f"{BASE_URL}/filmes/{slug}-{year}/"

    # Step 1: POST server selection to get the player iframe
    html, code, movie_url = _post(movie_url, {"server_name": "st1"})

    if not html:
        log(f"Failed to fetch movie page: {movie_url}", "error")
        return None

    # Step 2: Find the tuga.best iframe
    player_iframe = _extract_iframe_src(html, "tuga.best")
    if not player_iframe:
        log("No tuga.best iframe found on movie page", "error")
        return None

    log(f"Player iframe: {player_iframe}", "debug")

    # Step 3: POST start_video=1 to get the Streamtape embed
    html2, code2, _ = _post(player_iframe, {"start_video": "1"})

    if not html2:
        log("Failed to fetch player page", "error")
        return None

    # Step 4: Extract Streamtape embed URL
    streamtape_url = _extract_iframe_src(html2, "streamtape.com")
    if not streamtape_url:
        log("No Streamtape iframe found", "error")
        return None

    # Step 5: Resolve Streamtape to direct URL
    result = StreamtapeResolver().resolve(streamtape_url)
    if result and result.get('url'):
        # Extract Portuguese subtitles from the Streamtape embed URL
        subtitles = _extract_subtitles(streamtape_url)
        return {'url': result['url'], 'subtitles': subtitles}

    log("Failed to resolve Streamtape URL", "error")
    return None


def resolve_episode_url(series_slug, season, episode, url=None):
    """
    Resolve a TV episode to a direct playable URL plus Portuguese subtitles.

    Flow:
      1. Fetch the episode page on tugaflix
      2. Extract the tuga.best iframe (often embedded directly for series)
      3. POST start_video=1 to get the Streamtape embed
      4. Resolve Streamtape to direct MP4
      5. Extract subtitle URL from the c1_file parameter of the embed

    Returns:
      dict with 'url' (direct media URL) and 'subtitles' (list of URLs),
      or None on failure.
    """
    from resources.lib.constants import BASE_URL

    episode_url = url or f"{BASE_URL}/series/{series_slug}/{season}/{episode}/"

    html, code, final = http_request_follow(episode_url, timeout=30)
    if not html or code != 200:
        log(f"Failed to fetch episode page: {episode_url} (code={code})", "error")
        return None

    # Find tuga.best iframe (either player/movie.php or player/tv.php)
    player_iframe = _extract_iframe_src(html, "tuga.best")
    if player_iframe:
        for post_data in ({"submit": "1"}, {"start_video": "1"}):
            html2, _code2, _ = _post(player_iframe, post_data)
            if not html2:
                continue
            streamtape_url = _extract_iframe_src(html2, "streamtape.com")
            if streamtape_url:
                result = StreamtapeResolver().resolve(streamtape_url)
                if result and result.get('url'):
                    # Extract Portuguese subtitles from the Streamtape embed URL
                    subtitles = _extract_subtitles(streamtape_url)
                    return {'url': result['url'], 'subtitles': subtitles}

    log("Failed to resolve episode URL", "error")
    return None


def _extract_iframe_src(html, keyword=None):
    """Extract iframe src attribute, optionally filtered by keyword."""
    import re
    pattern = r'<iframe[^>]+src=["\']([^"\']+)["\']'
    for match in re.finditer(pattern, html, re.IGNORECASE):
        # Decode HTML entities (&#038; etc.) so query params are not truncated
        src = clean_html_entities(match.group(1))
        if src.startswith("//"):
            src = "https:" + src
        if keyword is None or keyword.lower() in src.lower():
            return src
    return None
