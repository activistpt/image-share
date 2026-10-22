# -*- coding: utf-8 -*-
"""
TugaFlix Kodi Addon - Provider resolvers.
Each provider class resolves a video page to a direct media URL.
"""

from __future__ import absolute_import

import re

from resources.lib.common import http_request, find_iframe_src, log, USER_AGENT
from resources.lib.constants import PLAYER_URL


def resolve_video_url(provider_key, page_url):
    """
    Resolve a provider's embed/player page to a direct video URL.

    Args:
        provider_key: Internal provider name (e.g. 'streamtape')
        page_url: The embed or player URL

    Returns:
        Dict with 'url' (direct media URL) or None on failure.
    """
    resolvers = {
        'streamtape': StreamtapeResolver,
        'streamtape2': StreamtapeResolver,
    }

    resolver_cls = resolvers.get(provider_key)
    if not resolver_cls:
        log(f"No resolver available for provider: {provider_key}", "warning")
        return None

    return resolver_cls().resolve(page_url)


class StreamtapeResolver:
    """
    Resolves Streamtape embed pages to direct MP4 URLs.

    Flow:
      1. Load the embed page at streamtape.com/e/{ID}
      2. Parse the `botlink` div which contains the Streamtape get_video URL
      3. Append &stream=1 to get the direct CDN redirect
      4. Return the URL (Kodi will follow the redirect)
    """

    EMBED_DOMAIN = "streamtape.com"

    def resolve(self, embed_url):
        """
        Resolve a Streamtape embed URL to a direct video URL.

        Args:
            embed_url: e.g. https://streamtape.com/e/wOakwJb6RKHGJd?c1_file=...

        Returns:
            {'url': 'https://streamtape.com/get_video?id=...&stream=1'}
        """
        log(f"Resolving Streamtape: {embed_url}", "debug")

        # Fetch the embed page
        html, code, _ = http_request(
            embed_url,
            headers={
                "User-Agent": USER_AGENT,
                "Referer": f"{PLAYER_URL}/",
            },
            timeout=30,
        )

        if not html or code != 200:
            log(f"Failed to fetch Streamtape embed (code={code})", "error")
            return None

        # The embed page constructs the get_video URL in JavaScript.
        # We parse the `botlink` div which is populated by JS but visible
        # in the raw HTML (lines setting innerHTML).
        direct_url = self._extract_get_video_url(html)
        if direct_url:
            # Normalize the URL to use https://
            if direct_url.startswith("//"):
                direct_url = "https:" + direct_url
            elif direct_url.startswith("/streamtape.com"):
                # Root-relative path on streamtape.com domain
                # /streamtape.com/get_video -> https://streamtape.com/get_video
                direct_url = "https://streamtape.com" + direct_url[len("/streamtape.com"):]
            elif direct_url.startswith("/get_video"):
                # Root-relative get_video path
                direct_url = "https://streamtape.com" + direct_url
            if not direct_url.endswith("&stream=1"):
                direct_url += "&stream=1"
            log(f"Resolved Streamtape URL: {direct_url}", "debug")
            return {"url": direct_url}

        # Fallback: try extracting from vidconfig JSON
        direct_url = self._extract_from_vidconfig(html)
        if direct_url:
            if direct_url.startswith("//"):
                direct_url = "https:" + direct_url
            elif direct_url.startswith("/streamtape.com"):
                direct_url = "https://streamtape.com" + direct_url[len("/streamtape.com"):]
            elif direct_url.startswith("/get_video"):
                direct_url = "https://streamtape.com" + direct_url
            log(f"Resolved Streamtape URL (fallback): {direct_url}", "debug")
            return {"url": direct_url}

        log("Streamtape resolution: no video URL found", "error")
        return None

    def _extract_get_video_url(self, html):
        """
        Extract the direct get_video URL from the Streamtape embed page.

        Streamtape obfuscates the video URL using JavaScript string operations.
        The page contains:
        1. HTML divs with initial (decoy) token values
        2. JavaScript that overwrites these with correct URLs via substring()

        We parse the JavaScript to get the correct token.
        """
        # Strategy 1: Parse the JS that sets botlink innerHTML
        # The botlink is what srclink reads: var srclink = $('#botlink').text() + '&stream=1'
        url = self._parse_js_innerhtml(html, 'botlink')
        if url:
            log(f"Extracted URL via JS parse (botlink): {url[:80]}...", "debug")
            return url

        # Strategy 2: Try ideoolink (it has a JS-assigned value too)
        url = self._parse_js_innerhtml(html, 'ideoolink')
        if url:
            # ideoolink may have a root-relative path; normalize
            if url.startswith("/streamtape.com"):
                url = "//" + url[len("/"):].lstrip("/")
            log(f"Extracted URL via JS parse (ideoolink): {url[:80]}...", "debug")
            return url

        # Strategy 3: Parse the HTML div/span content (may have decoy token)
        for elem_id in ('botlink', 'ideoolink', 'robotlink'):
            pattern = rf'id="{elem_id}"[^>]*>([^<]+)</(?:div|span)>'
            match = re.search(pattern, html)
            if match:
                url = match.group(1).strip()
                if 'streamtape.com' in url or 'get_video' in url:
                    log(f"Extracted URL from #{elem_id} (HTML): {url[:80]}...", "debug")
                    return url

        # Strategy 4: vidconfig + page params
        vidconfig_match = re.search(r'vidconfig\s*=\s*({.+?});', html)
        if vidconfig_match:
            import json
            try:
                config = json.loads(vidconfig_match.group(1))
                video_id = config.get('id', '')
                if video_id:
                    gv_match = re.search(
                        r'get_video\?id=([^&]+)&expires=(\d+)&ip=([^&]+)&token=([^\'"&]+)',
                        html
                    )
                    if gv_match:
                        v_id, expires, ip, token = gv_match.groups()
                        url = f"//streamtape.com/get_video?id={v_id}&expires={expires}&ip={ip}&token={token}"
                        log(f"Extracted URL from vidconfig+params: {url[:80]}...", "debug")
                        return url
            except Exception as e:
                log(f"vidconfig parse error: {e}", "error")

        # Strategy 5: Search for any //streamtape.com/get_video URL
        gv_match = re.search(
            r'(//streamtape\.com/get_video\?id=[^\s"\'<>]+)', html
        )
        if gv_match:
            url = gv_match.group(1)
            log(f"Extracted URL from regex: {url[:80]}...", "debug")
            return url

        return None

    def _parse_js_innerhtml(self, html, elem_id):
        """
        Parse JavaScript that sets an element's innerHTML to construct the URL.

        Handles patterns like:
          'prefix' + ('obfuscated').substring(N)
          'prefix' + ''+ ('obfuscated').substring(N1).substring(N2)
          '//streamtape.com' + 'xyza/get_video...'.substring(4)
        """
        # Find the JS assignment: getElementById('elem_id').innerHTML = ...;
        js_pattern = (
            r"getElementById\(\s*['\"]" + re.escape(elem_id) + r"['\"]\s*\)"
            r"\.innerHTML\s*=\s*(.+?);"
        )
        match = re.search(js_pattern, html, re.DOTALL)
        if not match:
            return None

        js_expr = match.group(1).strip()
        log(f"JS expression for #{elem_id}: {js_expr[:120]}...", "debug")

        # Extract all quoted strings from the expression
        strings = re.findall(r"""['"]([^'"]*)['"]""", js_expr)
        if len(strings) < 2:
            return None

        # The first string is the prefix; the second is the obfuscated part
        # (there may be empty strings in between from ''+)
        prefix = strings[0]
        # Find the obfuscated string (the non-empty one after the prefix)
        obfuscated = None
        for s in strings[1:]:
            if s:  # Skip empty strings
                obfuscated = s
                break

        if not obfuscated:
            return None

        # Find all substring arguments: .substring(N1).substring(N2)...
        substrings = re.findall(r'\.substring\((\d+)\)', js_expr)

        # Apply substrings in order
        result = obfuscated
        for n in substrings:
            result = result[int(n):]

        # Combine prefix + processed string
        url = prefix + result
        return url

    def _extract_from_vidconfig(self, html):
        """Extract video URL from vidconfig JSON."""
        match = re.search(r'vidconfig\s*=\s*({.+?});', html)
        if not match:
            return None

        import json
        try:
            config = json.loads(match.group(1))
            video_id = config.get('id')
            if video_id:
                # Look for expires and token in the page
                expires_match = re.search(r'expires=(\d+)', html)
                token_match = re.search(r'token=([^\s"\'<>&]+)', html)
                ip_match = re.search(r'ip=([^\s"\'<>&]+)', html)

                if expires_match and token_match:
                    expires = expires_match.group(1)
                    token = token_match.group(1)
                    ip = ip_match.group(1) if ip_match else ""
                    url = f"//streamtape.com/get_video?id={video_id}&expires={expires}&ip={ip}&token={token}"
                    return url
        except Exception as e:
            log(f"vidconfig extraction error: {e}", "error")
        return None
