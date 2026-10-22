# -*- coding: utf-8 -*-
"""
TugaFlix Kodi Addon - Provider resolution dispatch.
"""

from __future__ import absolute_import

from resources.lib.providers.streamtape import StreamtapeResolver
from resources.lib.common import http_request, log
from resources.lib.constants import PROVIDERS


def resolve_movie_url(slug, year=None):
    """
    Resolve a movie slug to a direct playable URL.

    Flow:
      1. POST to the movie page with server_name=st1 (Streamtape)
      2. Extract the iframe src pointing to tuga.best/player/movie.php
      3. POST start_video=1 to get the Streamtape embed iframe
      4. Resolve the Streamtape embed to a direct MP4 URL
    """
    from resources.lib.constants import BASE_URL, USER_AGENT

    movie_url = f"{BASE_URL}/filmes/{slug}/"
    if year:
        movie_url = f"{BASE_URL}/filmes/{slug}-{year}/"

    # Step 1: POST server selection to get the player iframe
    html, code, _ = http_request(
        movie_url, method="POST", data={"server_name": "st1"},
        headers={"User-Agent": USER_AGENT, "Referer": f"{BASE_URL}/"},
        timeout=30,
    )

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
    html2, code2, _ = http_request(
        player_iframe, method="POST", data={"start_video": "1"},
        headers={"User-Agent": USER_AGENT, "Referer": f"{BASE_URL}/"},
        timeout=30,
    )

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
        return result['url']

    log("Failed to resolve Streamtape URL", "error")
    return None


def resolve_episode_url(series_slug, season, episode):
    """
    Resolve a TV episode URL to a direct playable URL.

    Flow:
      1. Fetch the episode page on tugaflix
      2. Extract the tuga.best iframe (often embedded directly for series)
      3. POST start_video=1 to get the Streamtape embed
      4. Resolve Streamtape to direct MP4
    """
    from resources.lib.constants import BASE_URL, USER_AGENT

    episode_url = f"{BASE_URL}/series/{series_slug}/{season}/{episode}/"

    html, code, _ = http_request(
        episode_url,
        headers={"User-Agent": USER_AGENT, "Referer": f"{BASE_URL}/"},
        timeout=30,
    )

    if not html:
        log(f"Failed to fetch episode page: {episode_url}", "error")
        return None

    # Find tuga.best iframe
    player_iframe = _extract_iframe_src(html, "tuga.best")
    if player_iframe:
        # TV episodes use name="submit" instead of name="start_video"
        post_data = {"submit": "1"}
        html2, code2, _ = http_request(
            player_iframe, method="POST", data=post_data,
            headers={"User-Agent": USER_AGENT, "Referer": f"{BASE_URL}/"},
            timeout=30,
        )
        if html2:
            streamtape_url = _extract_iframe_src(html2, "streamtape.com")
            if streamtape_url:
                result = StreamtapeResolver().resolve(streamtape_url)
                if result and result.get('url'):
                    return result['url']

    # Fallback: try tv.php directly (same POST parameter)
    tv_php_url = _extract_iframe_src(html, "tuga.best/player/tv.php")
    if tv_php_url:
        html2, _, _ = http_request(
            tv_php_url, method="POST", data={"submit": "1"},
            headers={"User-Agent": USER_AGENT, "Referer": f"{BASE_URL}/"},
            timeout=30,
        )
        if html2:
            streamtape_url = _extract_iframe_src(html2, "streamtape.com")
            if streamtape_url:
                result = StreamtapeResolver().resolve(streamtape_url)
                if result and result.get('url'):
                    return result['url']

    log("Failed to resolve episode URL", "error")
    return None


def _extract_iframe_src(html, keyword=None):
    """Extract iframe src attribute, optionally filtered by keyword."""
    import re
    pattern = r'<iframe[^>]+src=["\']([^"\']+)["\']'
    for match in re.finditer(pattern, html, re.IGNORECASE):
        src = match.group(1)
        src = src.replace('&amp;', '&')
        if src.startswith("//"):
            src = "https:" + src
        if keyword is None or keyword.lower() in src.lower():
            return src
    return None
