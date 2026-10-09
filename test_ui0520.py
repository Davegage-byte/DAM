"""DAM v0.5.20: transparente Navigation ohne Layout-Spruenge."""
from pathlib import Path
import unittest

SOURCE = Path(__file__).with_name('dam.py').read_text(encoding='utf-8')


class NavigationAppearanceTests(unittest.TestCase):
    def test_inactive_buttons_are_transparent(self):
        css = SOURCE.split('/* Alle vier Navigationsbuttons', 1)[1].split('/* Alle drei Suchfelder', 1)[0]
        self.assertIn('.dam-navigation button:not(:checked)', css)
        self.assertIn('.dam-navigation button:not(:checked)', css)
        self.assertIn('background-color: transparent;', css)
        self.assertNotIn('background-color: #393b3f;', css)
        self.assertIn('background-color: alpha(@window_fg_color, 0.08);', css)

    def test_button_geometry_does_not_change_with_selection(self):
        css = SOURCE.split('/* Alle vier Navigationsbuttons', 1)[1].split('/* Alle drei Suchfelder', 1)[0]
        common = css.split('/* Alle nicht aktiven Reiter', 1)[0]
        for declaration in ('min-height: 43px;', 'padding: 7px 16px;',
                            'font-weight: 700;', 'border: 1px solid transparent;',
                            'box-shadow: none;'):
            self.assertIn(declaration, common)
        self.assertIn('border-left-color: alpha(@window_fg_color, 0.28);', css)
        self.assertIn('border-left-width: 1px;', css)

    def test_info_button_rgb_preserved(self):
        self.assertIn('@keyframes dam-info-button-rgb', SOURCE)
        self.assertIn('animation-duration: 15s;', SOURCE)
        self.assertIn('.dam-mode-info button.dam-info-toggle:checked', SOURCE)


if __name__ == '__main__':
    unittest.main()
