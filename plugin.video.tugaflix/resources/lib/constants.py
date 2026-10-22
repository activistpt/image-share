# -*- coding: utf-8 -*-
"""
TugaFlix Kodi Addon - Constants
"""

ADDON_ID = "plugin.video.tugaflix"
ADDON_NAME = "TugaFlix"
ADDON_VERSION = "1.0.7"

# Base URLs
BASE_URL = "https://tugaflix.site"
PLAYER_URL = "https://tuga.best"

# User-Agent for HTTP requests
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Sitemap URLs
SITEMAP_INDEX = f"{BASE_URL}/sitemap.xml"
SITEMAP_FILMES = f"{BASE_URL}/wp-sitemap-posts-filmes-"
SITEMAP_SERIES = f"{BASE_URL}/wp-sitemap-posts-series-"

# Content types
CONTENT_TYPE_MOVIE = "movie"
CONTENT_TYPE_SERIES = "tvshow"

# Providers (server names mapped to resolver keys)
PROVIDERS = {
    "st1": "streamtape",
    "st2": "streamtape2",
    "111movies": "vidsrc",
    "MoviesAPI": "vidsrc",
    "Peachify": "peach",
    "VidApi": "vidapi",
    "Vidzee": "vidzee",
    "Vidcore": "vidcore",
    "Vidfast": "vidfast",
    "Vidking": "vidking",
    "Vidlink": "vidlink",
    "Vidnest": "vidnest",
    "Vidsrc WTF": "vidsrc_wtf",
    "Vidrock": "vidrock",
    "vidcore": "vidcore",
    "vidy": "vidy",
    "Vidsrc": "vidsrc",
}

# Provider display names (for UI)
PROVIDER_NAMES = {
    "streamtape": "Streamtape",
    "streamtape2": "Player 2",
    "vidsrc": "Vidsrc",
    "peach": "Peachify",
    "vidapi": "VidApi",
    "vidzee": "Vidzee",
    "vidcore": "Vidcore",
    "vidfast": "Vidfast",
    "vidking": "Vidking",
    "vidlink": "Vidlink",
    "vidnest": "Vidnest",
    "vidsrc_wtf": "Vidsrc WTF",
    "vidrock": "Vidrock",
    "vidy": "Vidy",
}
