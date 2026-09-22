"""
GameCard — the one card used by Wishlist, Deals and History grids.

    card = GameCard(game, on_click=open_detail)      # 168 px wide, portrait cover
    card.update_game(game)                            # re-render in place

Layout: cover (144×192) · name (2 lines, elided) · genre/year (muted)
        · price row: current (mono) + discount pill, base struck when on sale
        · priority badge overlaid on the cover, "at low" tag when the current
          price is within 5 % of the all-time low.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QLabel, QWidget

import i18n
from data.models import Game
from ui import icons, image_cache
from ui.components import Card, CoverImage, Pill, PriorityBadge, hbox, label, vbox
from ui.format import discount, money
from ui.theme import C, SP, font

CARD_W  = 168
COVER_W = 144
COVER_H = 192


class GameCard(Card):
    def __init__(self, game: Game, on_click: Optional[Callable[[Game], None]] = None, parent=None):
        super().__init__(parent, padding=SP["md"], clickable=on_click is not None, spacing=SP["sm"])
        self.setFixedWidth(CARD_W)
        self.game = game
        self._on_click = on_click
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)

        # cover + overlays
        cover_wrap = QWidget()
        cover_wrap.setFixedSize(COVER_W, COVER_H)
        self.cover = CoverImage(COVER_W, COVER_H, parent=cover_wrap)
        self.badge = PriorityBadge(game.priority, parent=cover_wrap)
        self.badge.move(SP["sm"], SP["sm"])
        self.low_tag = Pill(i18n.t("game.at_low"), "green", parent=cover_wrap)
        self.low_tag.adjustSize()
        self.low_tag.move(COVER_W - self.low_tag.width() - SP["sm"], SP["sm"])
        self.disc = Pill("", "green", parent=cover_wrap)
        self.body.addWidget(cover_wrap, 0, Qt.AlignmentFlag.AlignHCenter)

        self.name = QLabel()
        self.name.setProperty("role", "body")
        self.name.setFont(font("base", QFont.Weight.Medium))
        self.name.setWordWrap(True)
        self.name.setFixedHeight(QFontMetrics(self.name.font()).lineSpacing() * 2 + 2)
        self.name.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.body.addWidget(self.name)

        self.meta = label("", "muted", elide=True)
        self.body.addWidget(self.meta)

        row = hbox(spacing=SP["xs"])
        self.price = label("", "mono", weight=QFont.Weight.Bold)
        row.addWidget(self.price)
        self.base = label("", "muted")
        self.base.setProperty("role", "mono")
        row.addWidget(self.base)
        row.addStretch()
        self.body.addLayout(row)

        if on_click:
            self.clicked.connect(lambda: self._on_click(self.game))
        self.update_game(game)

    # ── render ───────────────────────────────────────────────────────────────

    def update_game(self, game: Game) -> None:
        self.game = game
        self.cover.set_pixmap(image_cache.get(game.cover_path, (COVER_W, COVER_H)))
        self.badge.set_priority(game.priority)
        self.badge.adjustSize()

        self.name.setText(game.name)
        self.setToolTip(game.name)
        bits = [b for b in (game.genre, str(game.release_year) if game.release_year else "") if b]
        self.meta.setText(" · ".join(bits))

        p = game.price
        if p is None:
            self.price.setText("—")
            self.price.setStyleSheet(f"color: {C['text_dim']};")
            self.base.hide(); self.disc.hide()
        else:
            self.price.setText(money(p.current, p.currency))
            on_sale = p.is_on_sale and p.discount_pct > 0
            self.price.setStyleSheet(f"color: {C['green'] if on_sale else C['text']};")
            if on_sale:
                self.base.setText(money(p.base, p.currency))
                self.base.setStyleSheet(f"color: {C['text_muted']}; text-decoration: line-through;")
                self.disc.setText(discount(p.discount_pct))
                self.disc.adjustSize()
                self.disc.move(COVER_W - self.disc.width() - SP["sm"], COVER_H - self.disc.height() - SP["sm"])
                self.base.show(); self.disc.show()
            else:
                self.base.hide(); self.disc.hide()

        at_low = False
        h = game.price_history
        if p is not None and h is not None and h.all_time_low > 0:
            at_low = p.current <= h.all_time_low * 1.05
        self.low_tag.setVisible(at_low)

        if game.status == "Purchased":
            self.setProperty("dimmed", "true")
            self.cover.setGraphicsEffect(None)
            self.price.setText(i18n.t("filters.purchased"))
            self.price.setStyleSheet(f"color: {C['text_dim']};")
            self.base.hide(); self.disc.hide()
