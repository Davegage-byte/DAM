"""DAM v0.5.19: RGB-Animation synchron, inaktive Navigationsbuttons identisch."""
from pathlib import Path
from unittest import TestCase

SRC = Path(__file__).with_name('dam.py').read_text(encoding='utf-8')

class InfoButtonThemeTests(TestCase):
    def test_button_rgb_cycle_matches_background(self):
        self.assertIn('@keyframes dam-info-ambient', SRC)
        self.assertIn('@keyframes dam-info-button-rgb', SRC)
        for pct in ('0%', '20%', '40%', '60%', '80%', '100%'):
            bg = SRC.split('@keyframes dam-info-ambient', 1)[1].split('}', 6)
            active = SRC.split('@keyframes dam-info-button-rgb', 1)[1].split('}', 6)
            self.assertIn(pct, ''.join(bg))
            self.assertIn(pct, ''.join(active))
        active_block = SRC.split('@keyframes dam-info-button-rgb', 1)[1].split('/* Barrierefreiheit', 1)[0]
        self.assertIn('animation-duration: 15s;', active_block)
        self.assertIn('animation-iteration-count: infinite;', active_block)
    def test_unselected_info_and_nav_share_css(self):
        styles = SRC.split('/* Alle vier Navigationsbuttons', 1)[1].split('/* Alle drei Suchfelder', 1)[0]
        self.assertIn('.dam-navigation button:not(:checked)', styles)
        self.assertIn('.dam-navigation button:not(:checked):hover', styles)
        self.assertIn('background-color: transparent;', styles)
        self.assertIn('border-left-color: alpha(@window_fg_color, 0.28);', SRC)
    def test_reduce_motion_disables_both(self):
        reduced = SRC.split('@media (prefers-reduced-motion: reduce)', 1)[1].split('}', 1)[0]
        self.assertIn('.dam-mode-info button.dam-info-toggle:checked', reduced)
        self.assertIn('.dam-mode-info headerbar', reduced)
