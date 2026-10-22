# -*- coding: utf-8 -*-
"""
TugaFlix Kodi Addon - Router / Dispatch
Handles plugin:// URL routing for Kodi.
"""

from __future__ import absolute_import

import sys
import re
import urllib.parse

try:
    import xbmc
    import xbmcplugin
    import xbmcgui
    _HAS_KODI = True
except ImportError:
    _HAS_KODI = False

from resources.lib.constants import ADDON_NAME, ADDON_ID
from resources.lib.common import log
from resources.lib.tugaflix import TugaFlixScraper


def get_params():
    """Parse plugin:// URL parameters from sys.argv[2]."""
    params = {}
    if len(sys.argv) > 2 and sys.argv[2]:
        for pair in sys.argv[2].split('&'):
            if '=' in pair:
                key, val = pair.split('=', 1)
                params[urllib.parse.unquote(key)] = urllib.parse.unquote(val)
    return params


def build_plugin_url(query):
    """Build a plugin:// URL with query parameters."""
    qs = urllib.parse.urlencode(query)
    return f"plugin://{ADDON_ID}/?{qs}"


def _slugify(title):
    """Convert a title to a URL-safe slug."""
    slug = title.lower().strip()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_-]+', '-', slug)
    return slug


def add_dir(handle, label, query, iconimage=None, isfolder=True):
    if not _HAS_KODI:
        return
    url = build_plugin_url(query)
    listitem = xbmcgui.ListItem(label=label)
    listitem.setArt({'icon': iconimage or "DefaultFolder.png",
                     'thumb': iconimage or "DefaultFolder.png"})
    xbmcplugin.addDirectoryItem(handle, url, listitem, isfolder)


def add_movie_item(handle, title, year, poster, info=None):
    if not _HAS_KODI:
        return
    query = {'action': 'play_movie', 'title': title, 'year': str(year),
             'slug': info.get('slug', '') if info else ''}
    url = build_plugin_url(query)
    listitem = xbmcgui.ListItem(label=f"{title} ({year})")
    listitem.setArt({'thumb': poster or "DefaultVideo.png", 'icon': poster or "DefaultVideo.png",
                     'poster': poster or '', 'fanart': poster or ''})
    listitem.setInfo('video', {
        'title': title, 'year': year,
        'plot': info.get('plot', '') if info else '',
        'rating': float(info.get('rating', 0)) if info and info.get('rating') else 0,
    })
    listitem.setProperty('isplayable', 'true')
    xbmcplugin.addDirectoryItem(handle, url, listitem, isfolder=False)


def add_tvshow_item(handle, title, poster, info=None):
    if not _HAS_KODI:
        return
    query = {'action': 'seasons', 'title': title,
             'slug': info.get('slug', '') if info else ''}
    url = build_plugin_url(query)
    listitem = xbmcgui.ListItem(label=title)
    listitem.setArt({'thumb': poster or "DefaultTVShows.png", 'icon': poster or "DefaultTVShows.png",
                     'poster': poster or '', 'fanart': poster or ''})
    listitem.setInfo('video', {'title': title, 'tvshowtitle': title,
                               'plot': info.get('plot', '') if info else ''})
    xbmcplugin.addDirectoryItem(handle, url, listitem, isfolder=True)


def add_episode_item(handle, title, season, episode, poster, info=None):
    if not _HAS_KODI:
        return
    query = {'action': 'play_episode', 'title': title,
             'season': str(season), 'episode': str(episode),
             'slug': info.get('slug', '') if info else '',
             'series_title': info.get('series_title', '') if info else ''}
    url = build_plugin_url(query)
    listitem = xbmcgui.ListItem(label=title)
    listitem.setArt({'thumb': poster or "DefaultVideo.png", 'icon': poster or "DefaultVideo.png",
                     'poster': poster or '', 'fanart': poster or ''})
    listitem.setInfo('video', {
        'title': title,
        'tvshowtitle': info.get('series_title', '') if info else title,
        'season': season, 'episode': episode,
        'plot': info.get('plot', '') if info else '',
    })
    listitem.setProperty('isplayable', 'true')
    xbmcplugin.addDirectoryItem(handle, url, listitem, isfolder=False)


def set_content_and_sort(handle, content_type):
    if not _HAS_KODI:
        return
    xbmcplugin.setContent(handle, content_type)
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_LABEL)


def end_directory(handle):
    if _HAS_KODI:
        xbmcplugin.endOfDirectory(handle, succeeded=True)


class Router:
    def __init__(self):
        self.handle = int(sys.argv[1]) if _HAS_KODI and len(sys.argv) > 1 else 0

    def run(self):
        params = get_params()
        action = params.get('action', 'root')
        log(f"Routing to action: {action}", "debug")
        try:
            {
                'root': self.show_root,
                'movies_browse': lambda: self.list_movies(params),
                'series_browse': lambda: self.list_series(params),
                'genres': self.list_genres,
                'years': self.list_years,
                'countries': self.list_countries,
                'search': self.search,
                'seasons': lambda: self.list_seasons(params),
                'episodes': lambda: self.list_episodes(params),
                'play_movie': lambda: self.play_movie(params),
                'play_episode': lambda: self.play_episode(params),
            }.get(action, self.show_root)()
        except Exception as e:
            log(f"Router error: {e}", "error")
            if _HAS_KODI:
                xbmcgui.Dialog().notification("TugaFlix", f"Erro: {str(e)}",
                                              xbmcgui.NOTIFICATION_ERROR)

    def show_root(self):
        add_dir(self.handle, "Filmes", {'action': 'movies_browse'}, "DefaultMovies.png")
        add_dir(self.handle, "Series", {'action': 'series_browse'}, "DefaultTVShows.png")
        add_dir(self.handle, "Generos", {'action': 'genres'}, "DefaultGenre.png")
        add_dir(self.handle, "Anos", {'action': 'years'}, "DefaultYear.png")
        add_dir(self.handle, "Paises", {'action': 'countries'}, "DefaultCountry.png")
        add_dir(self.handle, "Pesquisar", {'action': 'search'}, "DefaultSearch.png")
        set_content_and_sort(self.handle, "movies")
        end_directory(self.handle)

    def list_movies(self, params):
        scraper = TugaFlixScraper()
        items = scraper.get_movies_listing(params.get('page', '1'),
                                          genre=params.get('genre'),
                                          year=params.get('year'),
                                          country=params.get('country'))
        for item in items:
            add_movie_item(self.handle, item['title'], item['year'],
                           item.get('poster'), info=item)
        if items:
            np = int(params.get('page', '1')) + 1
            add_dir(self.handle, "Pagina Seguinte",
                    {'action': 'movies_browse', 'page': str(np)}, "DefaultFolder.png")
        set_content_and_sort(self.handle, "movies")
        end_directory(self.handle)

    def list_series(self, params):
        scraper = TugaFlixScraper()
        items = scraper.get_series_listing(params.get('page', '1'))
        for item in items:
            add_tvshow_item(self.handle, item['title'],
                            item.get('poster'), info=item)
        if items:
            np = int(params.get('page', '1')) + 1
            add_dir(self.handle, "Pagina Seguinte",
                    {'action': 'series_browse', 'page': str(np)}, "DefaultFolder.png")
        set_content_and_sort(self.handle, "tvshows")
        end_directory(self.handle)

    def list_genres(self):
        scraper = TugaFlixScraper()
        for name, slug in scraper.get_genres():
            add_dir(self.handle, name, {'action': 'movies_browse', 'genre': slug}, "DefaultGenre.png")
        end_directory(self.handle)

    def list_years(self):
        scraper = TugaFlixScraper()
        for year in scraper.get_years():
            add_dir(self.handle, str(year), {'action': 'movies_browse', 'year': str(year)}, "DefaultYear.png")
        end_directory(self.handle)

    def list_countries(self):
        scraper = TugaFlixScraper()
        for name, slug in scraper.get_countries():
            add_dir(self.handle, name, {'action': 'movies_browse', 'country': slug}, "DefaultCountry.png")
        end_directory(self.handle)

    def search(self):
        if _HAS_KODI:
            query = xbmcgui.Dialog().input("Pesquisar no TugaFlix:", type=xbmcgui.INPUT_TEXT)
            if query:
                self._search_results(query)
        else:
            log("Search not available outside Kodi", "warning")

    def _search_results(self, query):
        scraper = TugaFlixScraper()
        for item in scraper.search(query):
            if item.get('type') == 'movie':
                add_movie_item(self.handle, item['title'], item['year'],
                               item.get('poster'), info=item)
            else:
                add_tvshow_item(self.handle, item['title'],
                                item.get('poster'), info=item)
        set_content_and_sort(self.handle, "movies")
        end_directory(self.handle)

    def list_seasons(self, params):
        scraper = TugaFlixScraper()
        slug = params.get('slug', '')
        title = params.get('title', '')
        for season_num in scraper.get_seasons(slug):
            add_dir(self.handle, f"Temporada {season_num}",
                    {'action': 'episodes', 'slug': slug,
                     'season': str(season_num), 'series_title': title}, "DefaultTVSeason.png")
        end_directory(self.handle)

    def list_episodes(self, params):
        scraper = TugaFlixScraper()
        slug = params.get('slug', '')
        season = params.get('season', '1')
        series_title = params.get('series_title', '')
        for item in scraper.get_episodes(slug, season, series_title):
            add_episode_item(self.handle, item['title'],
                             item['season'], item['episode'],
                             item.get('poster'), info=item)
        set_content_and_sort(self.handle, "episodes")
        end_directory(self.handle)

    def play_movie(self, params):
        title = params.get('title', '')
        slug = params.get('slug', '')
        year = params.get('year', '')
        scraper = TugaFlixScraper()
        resolved = scraper.resolve_movie(slug, year)
        if resolved:
            self._play_url(resolved, title)
        else:
            self._show_error("Nao foi possivel resolver o URL do filme.")

    def play_episode(self, params):
        title = params.get('title', '')
        slug = params.get('slug', '')
        season = params.get('season', '1')
        episode = params.get('episode', '1')
        scraper = TugaFlixScraper()
        resolved = scraper.resolve_episode(slug, season, episode)
        if resolved:
            self._play_url(resolved, title)
        else:
            self._show_error("Nao foi possivel resolver o URL do episodio.")

    def _play_url(self, url, title):
        if not _HAS_KODI:
            log(f"PLAY URL: {url}", "info")
            return
        from resources.lib.constants import USER_AGENT as UA, BASE_URL as BU
        listitem = xbmcgui.ListItem(label=title, path=url)
        listitem.setInfo('video', {'title': title})
        listitem.setProperty('playable', 'true')
        listitem.setMimeType('video/mp4')
        listitem.setProperty('User-Agent', UA)
        listitem.setProperty('Referer', f"{BU}/")
        xbmcplugin.setResolvedUrl(self.handle, True, listitem)
        log(f"Playing: {url}", "info")

    def _show_error(self, message):
        if _HAS_KODI:
            xbmcgui.Dialog().notification("TugaFlix", message, xbmcgui.NOTIFICATION_ERROR)
        else:
            log(message, "error")


if __name__ == '__main__':
    Router().run()
