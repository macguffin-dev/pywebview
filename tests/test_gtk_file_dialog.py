"""The GTK backend's save dialog asks before it replaces a file.

GTK 3's GtkFileChooser confirms an overwrite only when told to: its
``do-overwrite-confirmation`` property applies to
``GTK_FILE_CHOOSER_ACTION_SAVE`` alone and is FALSE by default. The save
dialog never set it, so choosing an existing file replaced it without a word,
where the Cocoa, Qt and WinForms save dialogs all ask by default.

A download picks its destination through the same dialog, and WebKitGTK fails
a download whose destination exists unless ``allow-overwrite`` is set (FALSE
by default), so a file the user has just agreed to replace is allowed to be.

There is no GTK here: the backend is loaded over a stand-in ``gi`` that
records what the dialog and the download are told.
"""

import collections
import importlib.util
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

import webview

GTK_BACKEND = Path(webview.__file__).parent / 'platforms' / 'gtk.py'


@pytest.fixture
def gtk_backend(monkeypatch):
    """``webview/platforms/gtk.py`` over a stand-in ``gi``, loaded under a
    private name so that no later import is handed this copy."""
    repository = types.ModuleType('gi.repository')
    for name in ('Gdk', 'Gio', 'GLib', 'Gtk', 'WebKit2'):
        setattr(repository, name, mock.MagicMock(name=name))
    gi = types.ModuleType('gi')
    gi.require_version = lambda *_args: None
    gi.repository = repository
    monkeypatch.setitem(sys.modules, 'gi', gi)
    monkeypatch.setitem(sys.modules, 'gi.repository', repository)
    spec = importlib.util.spec_from_file_location('_gtk_backend_under_test', GTK_BACKEND)
    backend = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backend)
    return backend


def view_of(backend):
    """A BrowserView with only what a file dialog touches."""
    view = backend.BrowserView.__new__(backend.BrowserView)
    view.window = object()
    view.localization = collections.defaultdict(str)
    return view


def chooser(backend):
    """The dialog the backend made (every FileChooserDialog() is this one)."""
    return backend.gtk.FileChooserDialog.return_value


def test_the_save_dialog_asks_before_it_replaces_a_file(gtk_backend):
    view_of(gtk_backend).create_file_dialog(webview.FileDialog.SAVE, '/tmp', False, 'a.txt', ())
    chooser(gtk_backend).set_do_overwrite_confirmation.assert_called_once_with(True)


def test_it_is_told_before_it_runs(gtk_backend):
    calls = []
    dialog = chooser(gtk_backend)
    dialog.set_do_overwrite_confirmation.side_effect = lambda value: calls.append(('confirm', value))
    dialog.run.side_effect = lambda: calls.append(('run',))
    view_of(gtk_backend).create_file_dialog(webview.FileDialog.SAVE, '/tmp', False, 'a.txt', ())
    assert calls == [('confirm', True), ('run',)]


def test_the_chosen_file_is_still_returned(gtk_backend):
    dialog = chooser(gtk_backend)
    dialog.run.return_value = gtk_backend.gtk.ResponseType.OK
    dialog.get_filename.return_value = '/tmp/a.txt'
    result = view_of(gtk_backend).create_file_dialog(
        webview.FileDialog.SAVE, '/tmp', False, 'a.txt', ()
    )
    assert result == ('/tmp/a.txt',)


@pytest.mark.parametrize('dialog_type', [webview.FileDialog.OPEN, webview.FileDialog.FOLDER])
def test_an_open_or_folder_dialog_is_left_alone(gtk_backend, dialog_type):
    view_of(gtk_backend).create_file_dialog(dialog_type, '/tmp', False, '', ())
    chooser(gtk_backend).set_do_overwrite_confirmation.assert_not_called()


def test_a_download_may_replace_the_file_the_user_agreed_to_replace(gtk_backend):
    view = view_of(gtk_backend)
    view.create_file_dialog = lambda *_args: ('/tmp/report.pdf',)
    download = mock.MagicMock()
    view.on_download_decide_destination(download, 'report.pdf')
    download.set_allow_overwrite.assert_called_once_with(True)
    download.set_destination.assert_called_once_with(
        gtk_backend.glib.filename_to_uri.return_value
    )


def test_a_cancelled_download_replaces_nothing(gtk_backend):
    view = view_of(gtk_backend)
    view.create_file_dialog = lambda *_args: None
    download = mock.MagicMock()
    view.on_download_decide_destination(download, 'report.pdf')
    download.cancel.assert_called_once_with()
    download.set_allow_overwrite.assert_not_called()
