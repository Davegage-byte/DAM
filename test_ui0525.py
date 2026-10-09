"""DAM v0.5.25: reduced vertical whitespace and safer button spacing."""
from pathlib import Path
import ast
from unittest import TestCase

SRC = Path(__file__).with_name('dam.py').read_text(encoding='utf-8')
TREE = ast.parse(SRC)
APP = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == 'DAM')

def method(name):
    return ast.get_source_segment(SRC, next(node for node in APP.body
                                  if isinstance(node, ast.FunctionDef) and node.name == name))

class LayoutRefinementTests(TestCase):
    def test_overlay_center_shift_up(self):
        start = method('start')
        assert 'panel.set_margin_top(58)' in start
        assert 'panel.set_margin_bottom(168)' in start

    def test_result_messages_shift_up_as_well(self):
        assert 'self.update_empty_label.set_margin_bottom(76)' in method('add_page')

    def test_actions_have_more_bottom_clearance(self):
        page = method('add_page')
        assert 'page.set_margin_bottom(20)' in page
        assert 'footer.append(progress_row)' in page
        assert 'footer.append(actions)' in page

    def test_window_stays_at_previous_dimensions(self):
        assert 'self.window.set_default_size(1000, 640)' in method('start')
