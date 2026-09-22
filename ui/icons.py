"""
Lucide icons (ISC licence, https://lucide.dev) rendered as tinted QIcons.

    icon("heart")                 -> QIcon in the default text colour
    icon("heart", C["accent"], 18)-> tinted, 18 px
    pixmap("search", color, size) -> QPixmap for labels

Every emoji / unicode glyph the old UI used maps to one of these names.
Add icons by dropping the SVG body (the elements inside <svg>) in ICONS.
"""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QSize, Qt, QRectF
from PySide6.QtGui import QIcon, QPixmap, QPainter, QImage
from PySide6.QtSvg import QSvgRenderer

# name -> inner SVG (24x24 viewBox, stroke-based)
ICONS: dict[str, str] = {
    "arrow-left": "<path d='m12 19-7-7 7-7' /> <path d='M19 12H5' />",
    "arrow-right": "<path d='M5 12h14' /> <path d='m12 5 7 7-7 7' />",
    "arrow-up-right": "<path d='M7 7h10v10' /> <path d='M7 17 17 7' />",
    "badge-check": "<path d='M3.85 8.62a4 4 0 0 1 4.78-4.77 4 4 0 0 1 6.74 0 4 4 0 0 1 4.78 4.78 4 4 0 0 1 0 6.74 4 4 0 0 1-4.77 4.78 4 4 0 0 1-6.75 0 4 4 0 0 1-4.78-4.77 4 4 0 0 1 0-6.76Z' /> <path d='m16 9-5.5 5.5L8 12' />",
    "bell": "<path d='M10.268 21a2 2 0 0 0 3.464 0' /> <path d='M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326' />",
    "bookmark": "<path d='M17 3a2 2 0 0 1 2 2v15a1 1 0 0 1-1.496.868l-4.512-2.578a2 2 0 0 0-1.984 0l-4.512 2.578A1 1 0 0 1 5 20V5a2 2 0 0 1 2-2z' />",
    "calculator": "<rect width='16' height='20' x='4' y='2' rx='2' /> <line x1='8' x2='16' y1='6' y2='6' /> <line x1='16' x2='16' y1='14' y2='18' /> <path d='M16 10h.01' /> <path d='M12 10h.01' /> <path d='M8 10h.01' /> <path d='M12 14h.01' /> <path d='M8 14h.01' /> <path d='M12 18h.01' /> <path d='M8 18h.01' />",
    "calendar": "<path d='M8 2v3' /> <path d='M16 2v3' /> <rect x='3' y='3' width='18' height='18' rx='2' /> <path d='M3 9h18' />",
    "chart-bar": "<path d='M3 3v16a2 2 0 0 0 2 2h16' /> <path d='M7 16h8' /> <path d='M7 11h12' /> <path d='M7 6h3' />",
    "chart-column": "<path d='M3 3v16a2 2 0 0 0 2 2h16' /> <path d='M18 17V9' /> <path d='M13 17V5' /> <path d='M8 17v-3' />",
    "chart-line": "<path d='M3 3v16a2 2 0 0 0 2 2h16' /> <path d='m19 9-5 5-4-4-3 3' />",
    "chart-pie": "<path d='M21 12c.552 0 1.005-.449.95-.998a10 10 0 0 0-8.953-8.951c-.55-.055-.998.398-.998.95v8a1 1 0 0 0 1 1z' /> <path d='M21.21 15.89A10 10 0 1 1 8 2.83' />",
    "check": "<path d='M20 6 9 17l-5-5' />",
    "chevron-down": "<path d='m6 9 6 6 6-6' />",
    "chevron-left": "<path d='m15 18-6-6 6-6' />",
    "chevron-right": "<path d='m9 18 6-6-6-6' />",
    "chevron-up": "<path d='m18 15-6-6-6 6' />",
    "circle-check": "<circle cx='12' cy='12' r='10' /> <path d='m16 9-5.5 5.5L8 12' />",
    "circle-question-mark": "<circle cx='12' cy='12' r='10' /> <path d='M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3' /> <path d='M12 17h.01' />",
    "circle-x": "<circle cx='12' cy='12' r='10' /> <path d='m15 9-6 6' /> <path d='m9 9 6 6' />",
    "clipboard-list": "<rect width='8' height='4' x='8' y='2' rx='1' ry='1' /> <path d='M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2' /> <path d='M12 11h4' /> <path d='M12 16h4' /> <path d='M8 11h.01' /> <path d='M8 16h.01' />",
    "clock-fading": "<path d='M12 2a10 10 0 0 1 7.38 16.75' /> <path d='M12 6v6l4 2' /> <path d='M2.5 8.875a10 10 0 0 0-.5 3' /> <path d='M2.83 16a10 10 0 0 0 2.43 3.4' /> <path d='M4.636 5.235a10 10 0 0 1 .891-.857' /> <path d='M8.644 21.42a10 10 0 0 0 7.631-.38' />",
    "clock": "<circle cx='12' cy='12' r='10' /> <path d='M12 6v6l4 2' />",
    "cloud-off": "<path d='M10.94 5.274A7 7 0 0 1 15.71 10h1.79a4.5 4.5 0 0 1 4.222 6.057' /> <path d='M18.796 18.81A4.5 4.5 0 0 1 17.5 19H9A7 7 0 0 1 5.79 5.78' /> <path d='m2 2 20 20' />",
    "cloud": "<path d='M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z' />",
    "coins": "<path d='M13.744 17.736a6 6 0 1 1-7.48-7.48' /> <path d='M15 6h1v4' /> <path d='m6.134 14.768.866-.5 2 3.464' /> <circle cx='16' cy='8' r='6' />",
    "crown": "<path d='M11.562 3.266a.5.5 0 0 1 .876 0L15.39 8.87a1 1 0 0 0 1.516.294L21.183 5.5a.5.5 0 0 1 .798.519l-2.834 10.246a1 1 0 0 1-.956.734H5.81a1 1 0 0 1-.957-.734L2.02 6.02a.5.5 0 0 1 .798-.519l4.276 3.664a1 1 0 0 0 1.516-.294z' /> <path d='M5 21h14' />",
    "dollar-sign": "<line x1='12' x2='12' y1='2' y2='22' /> <path d='M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6' />",
    "crosshair": "<circle cx='12' cy='12' r='10' /> <line x1='22' x2='18' y1='12' y2='12' /> <line x1='6' x2='2' y1='12' y2='12' /> <line x1='12' x2='12' y1='6' y2='2' /> <line x1='12' x2='12' y1='22' y2='18' />",
    "download": "<path d='M12 15V3' /> <path d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4' /> <path d='m7 10 5 5 5-5' />",
    "ellipsis": "<circle cx='12' cy='12' r='1' /> <circle cx='19' cy='12' r='1' /> <circle cx='5' cy='12' r='1' />",
    "external-link": "<path d='M15 3h6v6' /> <path d='M10 14 21 3' /> <path d='M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6' />",
    "eye-off": "<path d='M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 10.747 10.747 0 0 1-1.444 2.49' /> <path d='M14.084 14.158a3 3 0 0 1-4.242-4.242' /> <path d='M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696 10.75 10.75 0 0 1 4.446-5.143' /> <path d='m2 2 20 20' />",
    "eye": "<path d='M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0' /> <circle cx='12' cy='12' r='3' />",
    "file-spreadsheet": "<path d='M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z' /> <path d='M14 2v5a1 1 0 0 0 1 1h5' /> <path d='M8 13h2' /> <path d='M14 13h2' /> <path d='M8 17h2' /> <path d='M14 17h2' />",
    "flame": "<path d='M12 3q1 4 4 6.5t3 5.5a1 1 0 0 1-14 0 5 5 0 0 1 1-3 1 1 0 0 0 5 0c0-2-1.5-3-1.5-5q0-2 2.5-4' />",
    "flower": "<circle cx='12' cy='12' r='3' /> <path d='M12 16.5A4.5 4.5 0 1 1 7.5 12 4.5 4.5 0 1 1 12 7.5a4.5 4.5 0 1 1 4.5 4.5 4.5 4.5 0 1 1-4.5 4.5' /> <path d='M12 7.5V9' /> <path d='M7.5 12H9' /> <path d='M16.5 12H15' /> <path d='M12 16.5V15' /> <path d='m8 8 1.88 1.88' /> <path d='M14.12 9.88 16 8' /> <path d='m8 16 1.88-1.88' /> <path d='M14.12 14.12 16 16' />",
    "folder-open": "<path d='m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2' />",
    "funnel": "<path d='M10 20a1 1 0 0 0 .553.895l2 1A1 1 0 0 0 14 21v-7a2 2 0 0 1 .517-1.341L21.74 4.67A1 1 0 0 0 21 3H3a1 1 0 0 0-.742 1.67l7.225 7.989A2 2 0 0 1 10 14z' />",
    "gamepad-2": "<line x1='6' x2='10' y1='11' y2='11' /> <line x1='8' x2='8' y1='9' y2='13' /> <line x1='15' x2='15.01' y1='12' y2='12' /> <line x1='18' x2='18.01' y1='10' y2='10' /> <path d='M17.32 5H6.68a4 4 0 0 0-3.978 3.59c-.006.052-.01.101-.017.152C2.604 9.416 2 14.456 2 16a3 3 0 0 0 3 3c1 0 1.5-.5 2-1l1.414-1.414A2 2 0 0 1 9.828 16h4.344a2 2 0 0 1 1.414.586L17 18c.5.5 1 1 2 1a3 3 0 0 0 3-3c0-1.545-.604-6.584-.685-7.258-.007-.05-.011-.1-.017-.151A4 4 0 0 0 17.32 5z' />",
    "ghost": "<path d='M15 10v1' /> <path d='M7.528 20.472a1.6 1.6 0 012.277 0l1.057 1.056a1.6 1.6 0 002.276 0l1.057-1.056a1.6 1.6 0 012.277 0l1.114 1.114a1.4 1.4 0 002.414-1V10a8 8 0 00-16 0v10.586a1.4 1.4 0 002.414 1z' /> <path d='M9 10v1' />",
    "gift": "<path d='M12 7v14' /> <path d='M20 11v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-8' /> <path d='M7.5 7a1 1 0 0 1 0-5A4.8 8 0 0 1 12 7a4.8 8 0 0 1 4.5-5 1 1 0 0 1 0 5' /> <rect x='3' y='7' width='18' height='4' rx='1' />",
    "globe": "<circle cx='12' cy='12' r='10' /> <path d='M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20' /> <path d='M2 12h20' />",
    "hash": "<line x1='4' x2='20' y1='9' y2='9' /> <line x1='4' x2='20' y1='15' y2='15' /> <line x1='10' x2='8' y1='3' y2='21' /> <line x1='16' x2='14' y1='3' y2='21' />",
    "heart": "<path d='M2 9.5a5.5 5.5 0 0 1 9.591-3.676.56.56 0 0 0 .818 0A5.49 5.49 0 0 1 22 9.5c0 2.29-1.5 4-3 5.5l-5.492 5.313a2 2 0 0 1-3 .019L5 15c-1.5-1.5-3-3.2-3-5.5' />",
    "hourglass": "<path d='M5 22h14' /> <path d='M5 2h14' /> <path d='M17 22v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22' /> <path d='M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2' />",
    "image": "<rect width='18' height='18' x='3' y='3' rx='2' ry='2' /> <circle cx='9' cy='9' r='2' /> <path d='m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21' />",
    "info": "<circle cx='12' cy='12' r='10' /> <path d='M12 16v-4' /> <path d='M12 8h.01' />",
    "key-round": "<path d='M2.586 17.414A2 2 0 0 0 2 18.828V21a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h1a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h.172a2 2 0 0 0 1.414-.586l.814-.814a6.5 6.5 0 1 0-4-4z' /> <circle cx='16.5' cy='7.5' r='.5' fill='currentColor' />",
    "lamp": "<path d='M12 12v6' /> <path d='M4.077 10.615A1 1 0 0 0 5 12h14a1 1 0 0 0 .923-1.385l-3.077-7.384A2 2 0 0 0 15 2H9a2 2 0 0 0-1.846 1.23Z' /> <path d='M8 20a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v1a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1z' />",
    "languages": "<path d='m5 8 6 6' /> <path d='m4 14 6-6 2-3' /> <path d='M2 5h12' /> <path d='M7 2h1' /> <path d='m22 22-5-10-5 10' /> <path d='M14 18h6' />",
    "layers": "<path d='M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z' /> <path d='M2 12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 12' /> <path d='M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 17' />",
    "layout-dashboard": "<rect width='7' height='9' x='3' y='3' rx='1' /> <rect width='7' height='5' x='14' y='3' rx='1' /> <rect width='7' height='9' x='14' y='12' rx='1' /> <rect width='7' height='5' x='3' y='16' rx='1' />",
    "leaf": "<path d='M11 20a10 10 0 0010-10 25.9 25.9 0 00-1.04-7.281 1 1 0 00-1.755-.325C15.833 5.5 13 5.5 9.8 6.1A7 7 0 0011 20' /> <path d='M2 21a5 5 0 012.911-4.544C7.613 15.212 8.351 15.24 11 13' />",
    "library-big": "<rect width='8' height='18' x='3' y='3' rx='1' /> <path d='M7 3v18' /> <path d='M20.4 18.9c.2.5-.1 1.1-.6 1.3l-1.9.7c-.5.2-1.1-.1-1.3-.6L11.1 5.1c-.2-.5.1-1.1.6-1.3l1.9-.7c.5-.2 1.1.1 1.3.6Z' />",
    "link": "<path d='M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71' /> <path d='M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71' />",
    "loader-circle": "<path d='M21 12a9 9 0 1 1-6.219-8.56' />",
    "log-out": "<path d='m16 17 5-5-5-5' /> <path d='M21 12H9' /> <path d='M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4' />",
    "map-pin": "<path d='M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0' /> <circle cx='12' cy='10' r='3' />",
    "medal": "<path d='M7.21 15 2.66 7.14a2 2 0 0 1 .13-2.2L4.4 2.8A2 2 0 0 1 6 2h12a2 2 0 0 1 1.6.8l1.6 2.14a2 2 0 0 1 .14 2.2L16.79 15' /> <path d='M11 12 5.12 2.2' /> <path d='m13 12 5.88-9.8' /> <path d='M8 7h8' /> <circle cx='12' cy='17' r='5' /> <path d='M12 18v-2h-.5' />",
    "message-circle-question-mark": "<path d='M2.992 16.342a2 2 0 0 1 .094 1.167l-1.065 3.29a1 1 0 0 0 1.236 1.168l3.413-.998a2 2 0 0 1 1.099.092 10 10 0 1 0-4.777-4.719' /> <path d='M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3' /> <path d='M12 17h.01' />",
    "minus": "<path d='M5 12h14' />",
    "moon": "<path d='M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 8.268c.344-.215.825-.004.803.401' />",
    "newspaper": "<path d='M15 18h-5' /> <path d='M18 14h-8' /> <path d='M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-4 0v-9a2 2 0 0 1 2-2h2' /> <rect width='8' height='4' x='10' y='6' rx='1' />",
    "package": "<path d='M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z' /> <path d='M12 22V12' /> <polyline points='3.29 7 12 12 20.71 7' /> <path d='m7.5 4.27 9 5.15' />",
    "pause": "<rect x='14' y='3' width='5' height='18' rx='1' /> <rect x='5' y='3' width='5' height='18' rx='1' />",
    "percent": "<line x1='19' x2='5' y1='5' y2='19' /> <circle cx='6.5' cy='6.5' r='2.5' /> <circle cx='17.5' cy='17.5' r='2.5' />",
    "piggy-bank": "<path d='M11 17h3v2a1 1 0 0 0 1 1h2a1 1 0 0 0 1-1v-3a3.16 3.16 0 0 0 2-2h1a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1h-1a5 5 0 0 0-2-4V3a4 4 0 0 0-3.2 1.6l-.3.4H11a6 6 0 0 0-6 6v1a5 5 0 0 0 2 4v3a1 1 0 0 0 1 1h2a1 1 0 0 0 1-1z' /> <path d='M16 10h.01' /> <path d='M2 8v1a2 2 0 0 0 2 2h1' />",
    "play": "<path d='M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z' />",
    "plus": "<path d='M5 12h14' /> <path d='M12 5v14' />",
    "radio": "<path d='M16.247 7.761a6 6 0 0 1 0 8.478' /> <path d='M19.075 4.933a10 10 0 0 1 0 14.134' /> <path d='M4.925 19.067a10 10 0 0 1 0-14.134' /> <path d='M7.753 16.239a6 6 0 0 1 0-8.478' /> <circle cx='12' cy='12' r='2' />",
    "receipt": "<path d='M12 17V7' /> <path d='M16 8h-6a2 2 0 0 0 0 4h4a2 2 0 0 1 0 4H8' /> <path d='M4 3a1 1 0 0 1 1-1 1.3 1.3 0 0 1 .7.2l.933.6a1.3 1.3 0 0 0 1.4 0l.934-.6a1.3 1.3 0 0 1 1.4 0l.933.6a1.3 1.3 0 0 0 1.4 0l.933-.6a1.3 1.3 0 0 1 1.4 0l.934.6a1.3 1.3 0 0 0 1.4 0l.933-.6A1.3 1.3 0 0 1 19 2a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1 1.3 1.3 0 0 1-.7-.2l-.933-.6a1.3 1.3 0 0 0-1.4 0l-.934.6a1.3 1.3 0 0 1-1.4 0l-.933-.6a1.3 1.3 0 0 0-1.4 0l-.933.6a1.3 1.3 0 0 1-1.4 0l-.934-.6a1.3 1.3 0 0 0-1.4 0l-.933.6a1.3 1.3 0 0 1-.7.2 1 1 0 0 1-1-1z' />",
    "refresh-cw": "<path d='M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8' /> <path d='M21 3v5h-5' /> <path d='M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16' /> <path d='M8 16H3v5' />",
    "search": "<path d='m21 21-4.34-4.34' /> <circle cx='11' cy='11' r='8' />",
    "settings": "<path d='M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915' /> <circle cx='12' cy='12' r='3' />",
    "shopping-bag": "<path d='M16 10a4 4 0 0 1-8 0' /> <path d='M3.103 6.034h17.794' /> <path d='M3.4 5.467a2 2 0 0 0-.4 1.2V20a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6.667a2 2 0 0 0-.4-1.2l-2-2.667A2 2 0 0 0 17 2H7a2 2 0 0 0-1.6.8z' />",
    "shopping-cart": "<path d='m2.05 2.05 1.099-.028a1 1 0 0 1 1.008.815l2.69 14.347A1 1 0 0 0 7.83 18H18' /> <path d='M4.563 5h16.435a1 1 0 0 1 .981 1.204l-1.026 6.226A2 2 0 0 1 18.962 14H6.25' /> <circle cx='18' cy='20' r='2' /> <circle cx='8' cy='20' r='2' />",
    "sliders-horizontal": "<path d='M10 5H3' /> <path d='M12 19H3' /> <path d='M14 3v4' /> <path d='M16 17v4' /> <path d='M21 12h-9' /> <path d='M21 19h-5' /> <path d='M21 5h-7' /> <path d='M8 10v4' /> <path d='M8 12H3' />",
    "snowflake": "<path d='m10 20-1.25-2.5L6 18' /> <path d='M10 4 8.75 6.5 6 6' /> <path d='m14 20 1.25-2.5L18 18' /> <path d='m14 4 1.25 2.5L18 6' /> <path d='m17 21-3-6h-4' /> <path d='m17 3-3 6 1.5 3' /> <path d='M2 12h6.5L10 9' /> <path d='m20 10-1.5 2 1.5 2' /> <path d='M22 12h-6.5L14 15' /> <path d='m4 10 1.5 2L4 14' /> <path d='m7 21 3-6-1.5-3' /> <path d='m7 3 3 6h4' />",
    "sparkles": "<path d='M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z' /> <path d='M20 2v4' /> <path d='M22 4h-4' /> <circle cx='4' cy='20' r='2' />",
    "star": "<path d='M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z' />",
    "sun": "<circle cx='12' cy='12' r='4' /> <path d='M12 2v2' /> <path d='M12 20v2' /> <path d='m4.93 4.93 1.41 1.41' /> <path d='m17.66 17.66 1.41 1.41' /> <path d='M2 12h2' /> <path d='M20 12h2' /> <path d='m6.34 17.66-1.41 1.41' /> <path d='m19.07 4.93-1.41 1.41' />",
    "tag": "<path d='M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z' /> <circle cx='7.5' cy='7.5' r='.5' fill='currentColor' />",
    "trash": "<path d='M10 11v6' /> <path d='M14 11v6' /> <path d='M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6' /> <path d='M3 6h18' /> <path d='M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2' />",
    "trending-up": "<path d='M16 7h6v6' /> <path d='m22 7-8.5 8.5-5-5L2 17' />",
    "triangle-alert": "<path d='m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3' /> <path d='M12 9v4' /> <path d='M12 17h.01' />",
    "trophy": "<path d='M10 14.66V17a1 1 0 0 1-1 1 2 2 0 0 0-2 2v2' /> <path d='M14 14.66V17a1 1 0 0 0 1 1 2 2 0 0 1 2 2v2' /> <path d='M17.916 10H19.5A2.5 2.5 0 0 0 22 7.5V5a1 1 0 0 0-1-1h-3' /> <path d='M4 22h16' /> <path d='M6 9a6 6 0 0 0 12 0V3a1 1 0 0 0-1-1H7a1 1 0 0 0-1 1z' /> <path d='M6.084 10H4.5A2.5 2.5 0 0 1 2 7.5V5a1 1 0 0 1 1-1h3' />",
    "upload": "<path d='M12 3v12' /> <path d='m17 8-5-5-5 5' /> <path d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4' />",
    "user": "<path d='M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2' /> <circle cx='12' cy='7' r='4' />",
    "wallet": "<path d='M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1' /> <path d='M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4' />",
    "x": "<path d='M18 6 6 18' /> <path d='m6 6 12 12' />",
    "zap": "<path d='M15.914 4a1.5 1.5 0 00-2.474-1.561l-9 9A1.5 1.5 0 005.5 14h4.002a.5.5 0 01.471.666L8.086 20a1.5 1.5 0 002.475 1.56l9-9A1.5 1.5 0 0018.5 10h-3.997a.5.5 0 01-.472-.667z' />",
}

# Friendly aliases (old glyph → icon name)
ALIASES = {
    "history": "clock-fading", "trash-2": "trash", "filter": "funnel", "lantern": "lamp",
    "help": "circle-question-mark", "wishlist": "heart", "library": "library-big",
    "dashboard": "layout-dashboard", "deals": "tag", "non_steam": "globe", "recap": "sparkles",
    "news": "newspaper", "external": "arrow-up-right", "refresh": "refresh-cw", "close": "x",
    "warning": "triangle-alert", "purchased": "shopping-cart", "spinner": "loader-circle",
}

# Sale event key fragment → icon
SALE_ICONS = {
    "summer": "sun", "halloween": "ghost", "black_friday": "shopping-bag", "autumn": "leaf",
    "winter": "snowflake", "lunar": "lamp", "spring": "flower", "fps": "crosshair", "default": "tag",
}


def sale_icon(event_key: str) -> str:
    k = (event_key or "").lower()
    for frag, name in SALE_ICONS.items():
        if frag in k:
            return name
    return SALE_ICONS["default"]


def _svg(name: str, color: str, stroke_width: float) -> bytes:
    body = ICONS.get(ALIASES.get(name, name))
    if body is None:
        raise KeyError(f"unknown icon {name!r}")
    return (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
            f"stroke='{color}' stroke-width='{stroke_width}' stroke-linecap='round' "
            f"stroke-linejoin='round'>{body}</svg>").encode()


@lru_cache(maxsize=1024)
def pixmap(name: str, color: str = "#f4f4f5", size: int = 16, stroke_width: float = 1.75,
           dpr: float = 2.0) -> QPixmap:
    """Crisp tinted pixmap (rendered at 2x for HiDPI)."""
    r = QSvgRenderer(QByteArray(_svg(name, color, stroke_width)))
    px = int(size * dpr)
    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r.render(p, QRectF(0, 0, px, px))
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


@lru_cache(maxsize=512)
def icon(name: str, color: str = "#f4f4f5", size: int = 16, stroke_width: float = 1.75) -> QIcon:
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size, stroke_width))
    return ic


def has(name: str) -> bool:
    return ALIASES.get(name, name) in ICONS
