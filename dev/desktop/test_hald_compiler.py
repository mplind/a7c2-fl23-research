"""HALD capture in the look compiler: TIFF sources, the identity image and the export check; no camera."""
import os
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
import pytest
import tifffile
from PySide6 import QtWidgets as W
from desktopapp import i18n
from desktopapp.actions import look_compiler
from desktopapp.window import Window
from looktool import hald
from looktool.references import Cube

LEVEL = 3


def export(path, function=lambda rgb: rgb ** 1.2, grain=0.0):
    image = hald.identity(LEVEL) / 65535.0
    values = function(image)
    values += np.random.default_rng(5).normal(0, grain / 255, values.shape) if grain else 0
    tifffile.imwrite(path, np.round(np.clip(values, 0, 1) * 65535).astype(np.uint16), photometric='rgb')
    return path


def test_a_tiff_source_is_converted_to_a_cube_and_compiled_as_st_srgb(tmp_path, monkeypatch):
    seen = {}
    def compile_main(argv):
        seen['argv'] = argv
        seen['cube'] = Cube(argv[0]).values.copy()
        return 0
    monkeypatch.setattr('looktool.compilelook.main', compile_main)
    result = look_compiler.run(dict(source=str(export(tmp_path / 'Kodak Gold.tif')), name='Gold',
                                    output=str(tmp_path / 'gold.a7look'), model='model.npz'))
    argv = seen['argv']
    assert argv[0].endswith('Kodak Gold.cube') and argv[argv.index('--input-space') + 1] == 'sony-st-srgb'
    assert np.allclose(seen['cube'].reshape(-1, 3), hald.lattice(LEVEL) ** 1.2, atol=1e-5)
    assert result['hald']['size'] == LEVEL ** 2 and result['output'] == str(tmp_path / 'gold.a7look')
    assert not os.path.exists(argv[0])  # the intermediate cube lives only for the compile


def test_a_tiff_with_grain_is_refused_before_compiling(tmp_path, monkeypatch):
    compile_main = Mock(return_value=0)
    monkeypatch.setattr('looktool.compilelook.main', compile_main)
    with pytest.raises(ValueError, match='grain'):
        look_compiler.run(dict(source=str(export(tmp_path / 'grainy.tif', grain=4)), name='G',
                               output=str(tmp_path / 'g.a7look'), model='model.npz'))
    compile_main.assert_not_called()


@pytest.fixture
def ui(tmp_path, monkeypatch):
    monkeypatch.setenv('A7C2_DESKTOP_DATA', str(tmp_path / 'data'))
    monkeypatch.setattr('desktopapp.window.QtCore.QProcess', Mock())
    W.QApplication.instance() or W.QApplication([])
    window = Window(); window.timer.stop()
    i18n.configure('en')
    yield window
    window.process = None; window.close()
    i18n.configure('zh_CN')


def test_the_compiler_dialog_accepts_tiffs_and_offers_the_hald_tools(ui):
    with patch.object(W.QDialog, 'exec'):
        ui.compiler_dialog()
    dialog = ui.findChildren(W.QDialog)[-1]
    names = {b.objectName(): b.text() for b in dialog.findChildren(W.QPushButton)}
    assert names['hald_identity'] == 'Save a HALD image for DxO…' and names['hald_check'] == 'Check a HALD export…'
    source = [b for b in dialog.findChildren(W.QPushButton) if b.text() == i18n.tr('选择…')][0]
    with patch.object(W.QFileDialog, 'getOpenFileName', return_value=('', '')) as chosen:
        source.click()
    assert '*.tif *.tiff' in chosen.call_args.args[3]


def test_saving_the_identity_image_writes_the_default_hald(ui, tmp_path):
    target = tmp_path / 'hald.tif'
    with patch.object(W.QFileDialog, 'getSaveFileName', return_value=(str(target), '')), \
            patch.object(W.QMessageBox, 'information') as told:
        ui.save_hald_identity()
    assert np.array_equal(tifffile.imread(target), hald.identity())
    assert 'uncompressed 16-bit TIFF' in told.call_args.args[2]


@pytest.mark.parametrize('function,expected', [
    (lambda rgb: rgb, 'matches the original HALD'),
    (lambda rgb: rgb ** 1.2, 'no grain or vignetting'),
])
def test_checking_an_export_explains_the_result(ui, tmp_path, function, expected):
    path = export(tmp_path / 'export.tif', function)
    with patch.object(W.QFileDialog, 'getOpenFileName', return_value=(str(path), '')), \
            patch.object(W.QMessageBox, 'information') as told:
        ui.check_hald_export()
    assert expected in told.call_args.args[2]


def test_checking_a_grainy_export_warns(ui, tmp_path):
    path = export(tmp_path / 'grainy.tif', grain=4)
    with patch.object(W.QFileDialog, 'getOpenFileName', return_value=(str(path), '')), \
            patch.object(W.QMessageBox, 'warning') as warned:
        ui.check_hald_export()
    assert 'grain' in warned.call_args.args[2]


def test_the_compiler_dialog_is_tall_enough_for_its_contents(ui):
    with patch.object(W.QDialog, 'exec'):
        ui.compiler_dialog()
    dialog = ui.findChildren(W.QDialog)[-1]
    assert dialog.height() >= dialog.sizeHint().height()
