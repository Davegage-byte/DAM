"""GUI-unabhängige Regressionstests für DAMs automatische Listenneuladung."""
import ast
from pathlib import Path
import types
import unittest
from unittest.mock import Mock


class Label:
    def __init__(self, value=''):
        self.value = value
    def set_text(self, value):
        self.value = value
    def get_text(self):
        return self.value


class Search(Label):
    pass


class Toggle:
    def __init__(self, value=False):
        self.value = value
    def get_active(self):
        return self.value
    def set_active(self, value):
        self.value = value


class Sort:
    def __init__(self, value=0):
        self.value = value
    def get_selected(self):
        return self.value
    def set_selected(self, value):
        self.value = value


class Stack:
    def __init__(self):
        self.pages = {'install': object(), 'update': object(), 'remove': object()}
        self.visible = 'install'
    def get_visible_child_name(self):
        return self.visible
    def set_sensitive(self, enabled):
        self.sensitive = enabled
    def get_child_by_name(self, key):
        return self.pages.get(key)
    def remove(self, obj):
        del self.pages[next(k for k, v in self.pages.items() if obj is v)]
    def set_visible_child_name(self, key):
        assert key in self.pages
        self.visible = key


class StubGLib:
    calls = []
    @classmethod
    def timeout_add(cls, *args):
        cls.calls.append(args)
        return 12
    @classmethod
    def idle_add(cls, *args):
        cls.calls.append(('idle', *args))
        return 13


def methods_from_source(*method_names):
    """Liest echte DAM-Methoden per AST: keine GTK-Laufzeit für Logiktests nötig."""
    source = Path(__file__).with_name('dam.py').read_text()
    tree = ast.parse(source)
    dam = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'DAM')
    methods = [node for node in dam.body if isinstance(node, ast.FunctionDef) and node.name in method_names]
    assert len(methods) == len(method_names)
    code = compile(ast.Module(body=methods, type_ignores=[]), 'dam.py', 'exec')
    scope = {'GLib': StubGLib}
    exec(code, scope)
    return scope


class RefreshTests(unittest.TestCase):
    def setUp(self):
        StubGLib.calls = []
        self.methods = methods_from_source('finish_apt_install', 'finish_app_list_refresh', '_rebuild_refresh_step')

    def test_successful_install_starts_refresh(self):
        fake = types.SimpleNamespace(
            install_running=True,
            install_select_button=Mock(), install_all_button=Mock(), install_select_all=Mock(),
            refresh_app_lists=Mock(), stop_operation_indicator=Mock(),
            update_ui_lock=Mock()
        )
        item = dict(package='vlc', version=None, is_installed=False,
                    caption_widget=Label(), tile_widget=Mock())
        status = Label()
        result = self.methods['finish_apt_install'](fake, [item], {'vlc': '3.0.21'}, None, status)
        self.assertFalse(result)
        self.assertTrue(item['is_installed'])
        self.assertEqual(item['caption_widget'].value, 'Installiert\n3.0.21')
        self.assertEqual(fake.refresh_app_lists.call_args.args, (1,))
        self.assertIn('App-Liste wird aktualisiert', status.value)

    def test_error_keeps_old_list_and_does_not_refresh(self):
        fake = types.SimpleNamespace(
            install_running=True,
            install_select_button=Mock(), install_all_button=Mock(), install_select_all=Mock(),
            refresh_app_lists=Mock(), stop_operation_indicator=Mock(),
            update_ui_lock=Mock()
        )
        status = Label()
        self.methods['finish_apt_install'](fake, [], {}, 'Ein Fehler', status)
        fake.refresh_app_lists.assert_not_called()
        self.assertIn('nicht abgeschlossen', status.value)

    def test_refresh_rebuilds_all_tabs_preserving_view_search_and_sort(self):
        stack = Stack()
        stack.visible = 'remove'
        controls = {'install': (Search('vlc'), Sort(3), Toggle(True)),
                    'update': (Search('rust'), Sort(1), None),
                    'remove': (Search('fire'), Sort(5), Toggle(False))}
        previous = dict(controls)
        fake = types.SimpleNamespace(
            update_check_running=False, update_install_running=False, list_refresh_running=True,
            make_app_lists=Mock(return_value=(['installed'], ['available'])),
            stack=stack, page_controls=controls, install_status=Label(), remove_status=Label(),
            stop_operation_indicator=Mock(), set_list_loading=Mock(),
            apply_mode_theme=Mock(), check_updates=Mock(), _refresh_plan=None,
            update_ui_lock=Mock())
        def add_page(obj, stack_obj, key, name, apps, verb):
            stack.pages[key] = object()
            fake.page_controls[key] = Search(), Sort(), Toggle(False) if key in ('install','remove') else None
        fake.add_page = types.MethodType(add_page, fake)
        fake._rebuild_refresh_step = lambda: self.methods['_rebuild_refresh_step'](fake)
        self.methods['finish_app_list_refresh'](fake, ('p', 'd', 's', 'o'), 1, None)
        self.assertTrue(fake.list_refresh_running)
        self.assertEqual(fake._refresh_plan['index'], 0)
        for _ in range(3):
            fake._rebuild_refresh_step()
            self.assertTrue(fake.list_refresh_running)
        fake._rebuild_refresh_step()
        self.assertEqual(stack.visible, 'remove')
        self.assertEqual(set(stack.pages), {'install', 'update', 'remove'})
        for key in previous:
            old_search, old_sort, old_show = previous[key]
            search, sort, show = fake.page_controls[key]
            self.assertEqual(search.get_text(), old_search.get_text())
            self.assertEqual(sort.get_selected(), old_sort.get_selected())
            if old_show is not None:
                self.assertEqual(show.get_active(), old_show.get_active())
        self.assertIn('automatisch aktualisiert', fake.install_status.value)
        self.assertFalse(fake.list_refresh_running)
        fake.set_list_loading.assert_called_with(False)
        fake.apply_mode_theme.assert_called_once_with('remove')

    def test_refresh_waits_for_active_update_scan(self):
        fake = types.SimpleNamespace(update_check_running=True, update_install_running=False,
                                     list_refresh_running=True, install_status=Label(),
                                     finish_app_list_refresh=Mock())
        self.methods['finish_app_list_refresh'](fake, ('a', 'b', 'c', 'd'), 1, None)
        self.assertEqual(len(StubGLib.calls), 1)
        self.assertEqual(StubGLib.calls[0][0], 250)
        self.assertTrue(fake.list_refresh_running)


if __name__ == '__main__':
    unittest.main()
