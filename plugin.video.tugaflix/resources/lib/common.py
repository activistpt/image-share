# -*- coding: utf-8 -*-
"""
TugaFlix Kodi Addon - Common utilities
HTTP session, HTML parsing helpers, logging
"""

from __future__ import absolute_import

import re
import urllib.parse
import urllib.request
import urllib.error

try:
    import xbmc
    import xbmcaddon
    _HAS_KODI = True
except ImportError:
    _HAS_KODI = False

from resources.lib.constants import USER_AGENT, BASE_URL


def log(msg, level="info"):
    """Log a message to Kodi log (or stderr if no Kodi)."""
    full_msg = f"[plugin.video.tugaflix] {msg}"
    if _HAS_KODI:
        levels = {
            "info": xbmc.LOGINFO,
            "warning": xbmc.LOGWARNING,
            "error": xbmc.LOGERROR,
            "debug": xbmc.LOGDEBUG,
        }
        xbmc.log(full_msg, levels.get(level, xbmc.LOGINFO))
    else:
        import sys
        print(full_msg, file=sys.stderr)


def get_addon():
    """Return the Kodi addon instance or None."""
    if _HAS_KODI:
        return xbmcaddon.Addon("plugin.video.tugaflix")
    return None


def http_request(url, method="GET", data=None, headers=None, timeout=30, cookies=None):
    """
    Perform an HTTP request and return (response_text, status_code, final_url).

    Uses only Python stdlib so it works in both Kodi's Python environment and
    in standalone testing.
    """
    merged_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
    }
    if headers:
        merged_headers.update(headers)

    # Add Referer header if not present
    if "Referer" not in merged_headers and url.startswith("https://tuga.best"):
        merged_headers["Referer"] = f"{BASE_URL}/"

    if cookies:
        merged_headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())

    encoded_data = None
    if data is not None:
        if isinstance(data, dict):
            encoded_data = urllib.parse.urlencode(data).encode("utf-8")
            if method == "GET":
                # Append to URL for GET requests
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}{encoded_data.decode('utf-8')}"
                encoded_data = None
            else:
                merged_headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            encoded_data = data.encode("utf-8") if isinstance(data, str) else data

    req = urllib.request.Request(url, data=encoded_data, headers=merged_headers, method=method)

    try:
        # No redirects by default; caller can follow manually if needed
        opener = urllib.request.build_opener(NoRedirectHandler)
        response = opener.open(req, timeout=timeout)
        content = response.read()
        # Handle gzip
        if response.headers.get("Content-Encoding") == "gzip":
            import gzip
            import io
            content = gzip.GzipFile(fileobj=io.BytesIO(content)).read()
        text = content.decode("utf-8", errors="replace")
        return text, response.getcode(), response.geturl()
    except urllib.error.HTTPError as e:
        content = e.read()
        text = content.decode("utf-8", errors="replace")
        # For redirects, expose the absolute Location so callers can follow it.
        location = e.headers.get("Location") if e.headers else None
        final = urllib.parse.urljoin(url, location) if location else e.url
        return text, e.code, final
    except urllib.error.URLError as e:
        log(f"URL Error for {url}: {e}", "error")
        return None, 0, url
    except Exception as e:
        log(f"Request error for {url}: {e}", "error")
        return None, 0, url


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Prevent automatic redirects so we can capture 302 Location headers."""
    def redirect_request(self, req, fp, code, msg, hdrs, newurl):
        return None  # Don't follow redirects


def http_request_follow(url, headers=None, timeout=30):
    """HTTP GET that follows redirects (used for sitemaps)."""
    merged_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
    }
    if headers:
        merged_headers.update(headers)
    req = urllib.request.Request(url, headers=merged_headers, method="GET")
    try:
        opener = urllib.request.build_opener()  # Default handler follows redirects
        response = opener.open(req, timeout=timeout)
        content = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            import gzip
            import io
            content = gzip.GzipFile(fileobj=io.BytesIO(content)).read()
        text = content.decode("utf-8", errors="replace")
        return text, response.getcode(), response.geturl()
    except Exception as e:
        log(f"http_request_follow error: {e}", "error")
        return None, 0, url


def follow_redirects(url, headers=None, timeout=30, max_redirects=5):
    """Follow redirects and return the final URL."""
    current = url
    for _ in range(max_redirects):
        _text, code, final_url = http_request(current, headers=headers, timeout=timeout)
        if code in (301, 302, 303, 307, 308) and final_url and final_url != current:
            current = final_url
        else:
            break
    return current


def extract_json_from_script(html, var_name):
    """
    Extract a JSON object from a JavaScript variable assignment.
    e.g. var vidconfig = {...};
    """
    pattern = rf'var\s+{re.escape(var_name)}\s*=\s*({{.*?}});'
    match = re.search(pattern, html, re.DOTALL)
    if match:
        import json
        try:
            return json.loads(match.group(1))
        except Exception as e:
            log(f"JSON parse error for {var_name}: {e}", "error")
    return None


def extract_text_between(text, start_marker, end_marker, after=False):
    """Extract text between two markers in an HTML string."""
    idx = text.find(start_marker)
    if idx == -1:
        return None
    if after:
        start = idx + len(start_marker)
    else:
        start = idx
    end_idx = text.find(end_marker, start)
    if end_idx == -1:
        return None
    return text[start:end_idx].strip()


def find_iframe_src(html, keyword=None):
    """
    Find iframe src in HTML, optionally filtering by keyword.
    Returns the src URL or None.
    """
    pattern = r'<iframe[^>]+src=["\']([^"\']+)["\']'
    for match in re.finditer(pattern, html, re.IGNORECASE):
        src = match.group(1)
        # Decode HTML entities (&amp;, &#038;, &#039;, ...)
        src = clean_html_entities(src)
        if keyword is None or keyword.lower() in src.lower():
            # Handle protocol-relative URLs
            if src.startswith("//"):
                src = "https:" + src
            return src
    return None


def clean_html_entities(text):
    """Decode HTML entities in text."""
    import html as html_module
    return html_module.unescape(text)


def build_url(path, query=None):
    """Build a plugin URL for Kodi routing."""
    if not path:
        path = "/"
    url = f"plugin://{path}"
    if query:
        qs = urllib.parse.urlencode(query)
        url = f"{url}?{qs}"
    return url
