"""DAM v0.5.22: mittige Meldungen und flackerfreie Info-Navigation."""
import ast
from pathlib import Path
from unittest import TestCase

SOURCE = Path(__file__).with_name('dam.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)
CLASS = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == 'DAM')


def code(name):
    node = next(node for node in CLASS.body
                if isinstance(node, ast.FunctionDef) and node.name == name)
    return ast.get_source_segment(SOURCE, node)


class CenteringTests(TestCase):
    def test_all_update_messages_centered_in_list_area(self):
        page = code('add_page')
        self.assertIn('message_overlay.set_child(scroll)', page)
        self.assertIn('message_overlay.set_vexpand(True)', page)
        self.assertIn('self.update_empty_label.set_halign(Gtk.Align.CENTER)', page)
        self.assertIn('self.update_empty_label.set_valign(Gtk.Align.CENTER)', page)
        self.assertIn('self.update_empty_label.set_justify(Gtk.Justification.CENTER)', page)
        self.assertIn('message_overlay.set_measure_overlay(self.update_empty_label, False)', page)
        self.assertNotIn('page.append(self.update_empty_label)', page)

    def test_global_spinner_and_action_status_centered(self):
        self.assertIn('caption.set_justify(Gtk.Justification.CENTER)', code('start'))
        self.assertIn('status.set_xalign(0.5)', code('add_page'))
        self.assertIn('status.set_justify(Gtk.Justification.CENTER)', code('add_page'))


class NoFlickerTests(TestCase):
    def test_navigation_uses_no_gesture_or_idle_delay(self):
        start = code('start')
        nav = code('on_navigation_toggled')
        self.assertNotIn('Gtk.GestureClick', start)
        self.assertNotIn('finish_info_navigation', nav)
        self.assertIn("self.stack.set_visible_child_name(mode)", nav)
        self.assertIn("self.content_stack.set_visible_child_name('apps')", nav)

    def test_info_and_normal_tabs_are_exclusive(self):
        start = code('start')
        self.assertIn('button.set_group(first_button)', start)
        self.assertIn("self.info_button = self.nav_buttons['info']", start)
