#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TugaFlix Kodi Addon - Entry Point"""

from __future__ import absolute_import

import sys

# Ensure addon root is in path (fixes import issues in some Kodi environments)
try:
    import os
    _addon_path = os.path.dirname(os.path.abspath(__file__))
    if _addon_path not in sys.path:
        sys.path.insert(0, _addon_path)
except Exception:
    pass

Router = None
try:
    from resources.lib.router import Router
    from resources.lib.common import log
    log("TugaFlix addon loaded successfully", "info")
except Exception as e:
    try:
        import xbmc
        xbmc.log(f"[plugin.video.tugaflix] FATAL: Failed to import: {e}", xbmc.LOGERROR)
    except Exception:
        print(f"[plugin.video.tugaflix] FATAL: Failed to import: {e}", file=sys.stderr)

if Router is not None:
    Router().run()
