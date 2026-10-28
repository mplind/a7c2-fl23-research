"""Six explicit workflows, background workers and a complete diagnostic log."""
from .i18n import configure, translate_qt, tr
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import html
import uuid
from PySide6 import QtCore, QtGui, QtWidgets as W
from . import VERSION
from . import jobs
from .engine_text import display  # worker and engine text, shown in English when the interface is English
from .engine_text import source as catalogue_entry
from .en_engine import NEXT_STEP
from . import presets
from . import reloadguide

DRIVER_HINT = ('\n驱动或连接没有成功：先在“连接与驱动”页卸载驱动后重装；仍不行，'
               '可点该页的“Zadig 指南…”，按说明给 0E8A 和 0336 两个身份分别装 libusbK。')
from . import connectionguide
from . import shell
from . import theme
from .shell import ask  # camera-write confirmations; tests patch desktopapp.window.ask
from .paths import APP_ICON, ROOT, data_root, load_settings, save_settings, write_json


SENTENCE_END = '.!?\u3002\uff01\uff1f'  # full stop, ! and ? in English and Chinese; compared, never shown


def joined(text, rest):
    """`text` then `rest`, which starts by closing the sentence: without a second full stop when `text`
    already ends one, in either language."""
    if text[-1:] and text[-1] in SENTENCE_END and rest[:1] and rest[0] in SENTENCE_END:
        return text + rest[1:]
    return text + rest


FIRMWARE = '2.01'  # the only firmware this release supports
# What a Vertical display or Shutter sound button writes, for the "Target:" line of the write
# confirmation. Their arguments name only a records folder, which says nothing about the write.
WRITE_TARGETS = {'vertical_enable': '竖屏显示＋Fn／子菜单线框修正', 'vertical_disable': '关闭竖屏显示并撤销线框修正',
                 'sound_on': '电子快门声：开启', 'sound_off': '电子快门声：关闭',
                 'sound_audition': '临时试听当前转换的声音', 'sound_install': '保存当前转换的声音',
                 'sound_restore_sound': '恢复索尼原厂快门声'}
# The body of every write confirmation. The battery is the one check left to the user (the app can't
# read its level, so the click confirms it); the model and the firmware build are checked by the app
# before anything is written (transport.Session, devicesession's build gate).
WRITE_CHECKS = ('\n请确认电量至少 50%。本工具无法读取电量；点击“写入相机”即表示已确认。\n'
                '写入前，本工具会核对相机是 ILCE-7CM2 且为受支持的 2.01 固件版本，不符合时停止。\n'
                '在完整读回结束前，保持相机开机并连接 USB，不要关机或拔线。')
# Sidebar: (section title shown above the first page of a section, page label, icon).
NAVIGATION = (('安装与连接', '首页 · 一键安装', 'home'), (None, '连接与驱动', 'connection'), (None, '恢复原厂功能', 'restore'),
              ('相机功能', 'FL2 / FL3', 'film'), (None, '自定义创意外观', 'looks'), (None, '竖屏显示', 'vertical'),
              (None, '电子快门声音', 'sound'), ('实验性', '胶片配方（实验性）', 'recipes'))


class Window(W.QMainWindow):
    def __init__(self, *, demo=False):
        super().__init__()
        self.settings = load_settings()
        configure(self.settings.get('language', 'en'))
        self.setWindowTitle('A7C II Tools')
        self.resize(1130, 850)
        self.setMinimumSize(960, 730)
        self.fields, self.buttons = {}, []
        # Buttons that start a camera write, and whether the connection test found a build the tool
        # does not support: those buttons then stay disabled (apply_write_gate).
        self.write_buttons, self.build_unsupported = [], False
        self.current_job = None
        self.log_offset = 0
        self.process = None
        self.demo = demo
        self.camera_operation = False
        self.page_meta = []
        app = W.QApplication.instance()
        translate_qt(app)
        theme.apply(app)
        app.styleHints().colorSchemeChanged.connect(self.restyle)
        central = W.QWidget()
        central.setObjectName('content')
        self.setCentralWidget(central)
        layout = W.QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.nav = shell.sidebar([(tr(section) if section else None, tr(label) if label != 'FL2 / FL3' else label, icon)
                                  for section, label, icon in NAVIGATION])
        layout.addWidget(self.nav)
        right = W.QVBoxLayout()
        right.setContentsMargins(24, 20, 24, 0)
        right.setSpacing(12)
        layout.addLayout(right, 1)
        header = W.QVBoxLayout()
        header.setSpacing(4)
        self.page_title = shell.text_label('', 'title1')
        self.page_detail = shell.text_label('', 'callout')
        header.addWidget(self.page_title)
        header.addWidget(self.page_detail)
        right.addLayout(header)
        self.status_area = shell.StatusArea()
        self.status = self.status_area.banner.text
        self.status.setText(tr('就绪。选择左侧功能；启动软件不会访问相机。'))
        self.progress = self.status_area.banner.progress
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.log = self.status_area.log
        self.stop = self.status_area.stop
        self.stop.clicked.connect(self.cancel_offline)
        self.status_area.open_folder.clicked.connect(self.open_job)
        self.status_area.export.clicked.connect(self.export_logs)
        right.addWidget(self.status_area)
        self.pages = W.QStackedWidget()
        right.addWidget(self.pages, 1)
        self.language = W.QComboBox()
        self.language.setObjectName('interface_language')
        self.language.addItem('English', 'en')
        self.language.addItem(tr('简体中文'), 'zh_CN')  # Chinese (Simplified) when the interface is English
        self.language.setCurrentIndex(1 if self.settings.get('language') == 'zh_CN' else 0)
        self.language.currentIndexChanged.connect(self.save_language)
        self.buttons.append(self.language)
        build = tr('Windows 测试版') if sys.platform == 'win32' else tr('桌面开发版')
        self.settings_dialog = shell.SettingsDialog(self, self.language, FIRMWARE, tr('%s（%s）') % (VERSION, build))
        self.home_page()
        self.connection_page()
        self.recovery_page()
        self.fl23_page()
        self.look_page()
        self.vertical_page()
        self.sound_page()
        self.recipe_page()
        self.nav.currentRowChanged.connect(self.show_page)
        self.nav.setCurrentRow(0)
        self.menus()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.poll_job)
        self.timer.start(250)

    def menus(self):
        """Settings in the app menu (⌘,) on macOS, under Edit on Windows; guides under Help."""
        bar = self.menuBar()
        settings = QtGui.QAction(tr('设置…'), self)
        settings.setMenuRole(QtGui.QAction.PreferencesRole)
        settings.setShortcut(QtGui.QKeySequence.Preferences)
        settings.triggered.connect(self.settings_dialog.open)
        bar.addMenu(tr('编辑')).addAction(settings)
        help_menu = bar.addMenu(tr('帮助'))
        # The cold-restart steps alone: the Help menu works at any time, even during a write.
        for title, callback in ((tr('连接相机前须知…'), self.show_connection_notice),
                                (tr('断电重开步骤…'), lambda *_: self.show_reload_guide(manual=True)),
                                (tr('支持的 LUT 格式…'), self.show_look_format_guide)):
            action = QtGui.QAction(title, self)
            action.triggered.connect(callback)
            help_menu.addAction(action)

    def show_page(self, index):
        self.pages.setCurrentIndex(index)
        title, detail = self.page_meta[index]
        self.page_title.setText(title)
        self.page_detail.setText(detail)
        self.page_detail.setVisible(bool(detail))

    def restyle(self, *_):
        """The system appearance changed: restyle the app and everything drawn from tokens."""
        theme.apply(W.QApplication.instance())
        for banner in self.findChildren(shell.Banner):
            banner.refresh()
        self.nav.viewport().update()
        for dialog in self.findChildren(W.QDialog):
            if hasattr(dialog, 'restyle'):
                dialog.restyle()

    def set_state(self, kind):
        """The status banner's kind: '' (idle), info (running), success, warning or danger.
        The progress bar shows while a task runs and when one stopped partway (a restart is
        needed before it can go on); a failure opens the log."""
        self.status_area.banner.set_kind(kind)
        self.progress.setVisible(kind == 'info' or (kind == 'warning' and 0 < self.progress.value() < 100))
        self.stop.setVisible(kind == 'info')
        if kind == 'danger':
            self.status_area.show_log(True)

    def save_language(self):
        self.settings['language'] = self.language.currentData()
        for key, field in self.fields.items():
            self.settings[key] = field.text()
        save_settings(self.settings)
        W.QMessageBox.information(self, tr('语言设置已保存'),
            tr('下次启动软件时使用所选语言。当前输入和任务保持不变。'))

    def page(self, title, detail):
        """A scrolling page; its title and one-line description appear in the window header."""
        wrapper = W.QScrollArea()
        wrapper.setObjectName('page')
        wrapper.setWidgetResizable(True)
        wrapper.setFrameShape(W.QFrame.NoFrame)
        body = W.QWidget()
        layout = W.QVBoxLayout(body)
        layout.setContentsMargins(0, 4, 4, 20)
        layout.setSpacing(10)
        wrapper.setWidget(body)
        self.pages.addWidget(wrapper)
        self.page_meta.append((title, detail))
        return layout

    def box(self, layout, title):
        """A Settings-style group holding a form: the title above, labels leading, fields trailing."""
        group = shell.section(layout, title)
        holder = W.QWidget()
        form = W.QFormLayout(holder)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        form.setLabelAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        form.setFieldGrowthPolicy(W.QFormLayout.AllNonFixedFieldsGrow)
        group.add(holder)
        return form

    def advanced(self, layout, title):
        toggle = W.QToolButton()
        toggle.setText(title)
        toggle.setCheckable(True)
        toggle.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        toggle.setArrowType(QtCore.Qt.RightArrow)
        content = W.QWidget()
        content.setVisible(False)
        inner = W.QVBoxLayout(content)
        inner.setContentsMargins(0, 2, 0, 6)
        inner.setSpacing(10)
        toggle.toggled.connect(content.setVisible)
        toggle.toggled.connect(lambda open: toggle.setArrowType(QtCore.Qt.DownArrow if open else QtCore.Qt.RightArrow))
        layout.addWidget(toggle)
        layout.addWidget(content)
        return inner

    def direct_args(self, group, **values):
        work = self.work(group)
        return dict(self.common(), workspace=work, **{key: value for key, value in values.items() if key != 'mode'})

    def setup_saved(self):
        """(state, refusal): the saved one-click job, and the plain refusal text when a firmware refusal
        stopped it. That job is not continued, since the gate refuses before it writes: the page starts a
        new one and shows the refusal in its place, so `state` comes back empty."""
        root = self.settings.get('setup_work', '')
        path = Path(root, 'setup.private.json') if root else None
        state = json.loads(path.read_text(encoding='utf-8')) if path is not None and path.is_file() else {}
        refusal = self.firmware_refusal(state)
        return ({}, refusal) if refusal else (state, '')

    def show_setup_note(self, pending, refusal):
        """The note above the install button: why the last job was not continued (a firmware refusal),
        or that an unfinished one is."""
        self.setup_note.setText(refusal or self.setup_continue_note)
        self.setup_note.setVisible(pending or bool(refusal))

    def setup_args(self):
        saved, _ = self.setup_saved()
        if saved and saved['phase'] != 'COMPLETE':
            return dict(self.common(), workspace=self.settings['setup_work'], options=saved['options'])
        root = self.work('setup')
        tool = ROOT / ('desktop-assets/exiftool/exiftool.exe' if sys.platform=='win32' else 'desktop-assets/exiftool/exiftool')
        looks = [dict(slot=s, path=self.text('setup_look_' + str(s))) for s in range(1, 7) if self.text('setup_look_' + str(s))]
        options = dict(fl23=self.setup_fl23.isChecked(), sound=self.setup_sound.isChecked(),
            vertical=self.setup_vertical.isChecked(), plugin=self.setup_plugin.isChecked(),
            exiftool=str(tool), looks=[] if self.setup_presets.isChecked() else looks,
            preset_pack=presets.PACK if self.setup_presets.isChecked() else None)
        return dict(self.common(), workspace=root, options=options)

    def home_page(self):
        layout = self.page(tr('一键安装'), tr('一次安装所选功能。相机按提示重启后，再点同一个按钮完成核对；无需逐个槽位安装。'))
        self.setup_presets = W.QCheckBox(tr('安装内置六款外观（替换自订 1–6，原有创意外观保留）'))
        self.setup_presets.setChecked(True)
        self.setup_fl23 = W.QCheckBox(tr('启用 FL2／FL3')); self.setup_fl23.setChecked(True)
        self.setup_sound = W.QCheckBox(tr('启用索尼原生电子快门声音')); self.setup_sound.setChecked(True)
        self.setup_vertical = W.QCheckBox(tr('保存开启竖屏拍摄信息显示（重开后自动生效）')); self.setup_vertical.setChecked(True)
        self.setup_plugin = W.QCheckBox(tr('安装 Lightroom 自动识别插件（需要 Lightroom）'))
        prior,refused=self.setup_saved()
        pending=bool(prior) and prior.get('phase')!='COMPLETE'
        if pending:
            options=prior['options']
            self.setup_presets.setChecked(options.get('preset_pack') == presets.PACK)
            for box,key in ((self.setup_fl23,'fl23'),(self.setup_sound,'sound'),(self.setup_vertical,'vertical'),(self.setup_plugin,'plugin')):
                box.setChecked(bool(options.get(key,key!='plugin')))
            for box in (self.setup_presets,self.setup_fl23,self.setup_sound,self.setup_vertical,self.setup_plugin):box.setEnabled(False)

        self.setup_note=shell.text_label(tr('安装尚未结束，请点击“继续安装”，按弹窗完成下一步；需要断电时，接回 USB 后仍点击此按钮。'))
        self.setup_continue_note=self.setup_note.text()
        self.setup_note.setProperty('warning', True)
        self.show_setup_note(pending,refused)
        layout.addWidget(self.setup_note)
        self.setup_preset_summary = W.QLabel(tr(presets.SUMMARY))
        if pending:
            names = ['%s %s' % (r['slot'], r.get('name', Path(r['path']).stem)) for r in prior['options'].get('looks', [])]
            self.setup_preset_summary.setText(tr('本次已保存外观：') + (tr('、').join(names) if names else tr('未选择外观，不会新增六款')))
        else:
            self.setup_preset_summary.setEnabled(self.setup_presets.isChecked())
            self.setup_presets.toggled.connect(self.setup_preset_summary.setEnabled)
        group = shell.section(layout, tr('安装内容'))
        group.add(shell.CheckRow(self.setup_presets, self.setup_preset_summary))
        group.add(shell.CheckRow(self.setup_fl23, tr('在相机的创意外观列表中加入 FL2 和 FL3。')))
        group.add(shell.CheckRow(self.setup_sound, tr('使用电子快门拍摄时播放索尼原生快门声。')))
        group.add(shell.CheckRow(self.setup_vertical, tr('竖握相机时，拍摄信息跟随转向。')))
        group.add(shell.CheckRow(self.setup_plugin, tr('让 Lightroom Classic 为每张照片自动选择对应的配置文件。')))
        actions = W.QHBoxLayout()
        layout.addLayout(actions)
        self.setup_result_button=W.QPushButton(tr('查看上次安装结果（不连接相机）'))
        self.setup_result_button.clicked.connect(self.show_setup_result)
        self.setup_result_button.setVisible(prior.get('phase')=='COMPLETE')
        actions.addWidget(self.setup_result_button);self.buttons.append(self.setup_result_button)
        actions.addStretch()
        # The button's own entry, apart from the page title: it opens the write confirmation, hence the ellipsis.
        self.setup_button=self.button(actions, tr('开始新的一键安装') if prior.get('phase')=='COMPLETE' else tr('继续安装') if prior else tr('一键安装…'),
                                      'setup_all', self.setup_args, primary=True)
        look_section=self.advanced(layout,tr('改用自己的 A7Look 文件（先取消勾选内置六款）'))
        custom_container = self.setup_custom_container = look_section.parentWidget()
        custom_container.setEnabled(not self.setup_presets.isChecked() and not pending)
        self.setup_presets.toggled.connect(lambda enabled: custom_container.setEnabled(not enabled))
        form = self.box(look_section, tr('选择 A7Look 文件'))
        for slot in range(1, 7):
            self.field(form, 'setup_look_' + str(slot), tr('自订 ') + str(slot), kind='file', filter=tr('Compiled looks (*.a7look)'))
        compile_button = W.QPushButton(tr('从 DCP／LUT 生成 A7Look…'))
        compile_button.clicked.connect(self.compiler_dialog); look_section.addWidget(compile_button, 0, QtCore.Qt.AlignLeft); self.buttons.append(compile_button)
        layout.addWidget(shell.text_label(tr('恢复出厂、卸载驱动和删除外观不会混入安装流程。自定义声音请在“电子快门声音”中转换后直接保存，试听可选。'), 'callout'))
        layout.addStretch()

    def drivers_first(self, arguments):
        """Suggest the connection page before a first one-click install on Windows."""
        if (sys.platform != 'win32' or self.settings.get('connection_verified')
                or Path(arguments.get('workspace', ''), 'setup.private.json').is_file()):
            return True
        choice = self.ask_drivers_first()
        if choice == 'drivers':
            self.nav.setCurrentRow(1)
        return choice == 'continue'

    def ask_drivers_first(self):
        box = W.QMessageBox(self)
        box.setWindowTitle(tr('建议先安装驱动'))
        box.setText(tr('这台电脑还没有成功连接过相机。建议先到“连接与驱动”页，点“准备两阶段驱动并测试连接”，'
                    '看到连接成功后再回来一键安装。'))
        box.setInformativeText(tr('一键安装也会自动尝试安装驱动，但驱动失败时排查更麻烦。'
                               '驱动反复装不上，可点该页的“Zadig 指南…”，按说明操作。'))
        go = box.addButton(tr('先去安装驱动'), W.QMessageBox.AcceptRole)
        box.addButton(tr('直接一键安装'), W.QMessageBox.DestructiveRole)
        cancel = box.addButton(W.QMessageBox.Cancel)
        box.setDefaultButton(go)
        shell.modal(box)
        return 'drivers' if box.clickedButton() is go else 'cancel' if box.clickedButton() is cancel else 'continue'

    def driver_step_failed(self, action):
        if action in ('usb_prepare', 'connect', 'driver_install'):
            return True
        if action != 'setup_all':
            return False
        try:
            state = json.loads(Path(self.settings.get('setup_work', ''), 'setup.private.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return False
        return 'drivers' not in state.get('completed_steps', [])

    def direct_verify_args(self, group, accepted=False):
        workspace=self.settings.get(group + '_direct_work', '')
        args={'workspace': workspace, 'accepted': accepted}
        if group=='factory':args.update(factory_verify=True,factory_preferred=self.text('factory_failed_work'))
        return args

    def show_setup_result(self):
        from .completion import archive_error,text
        path=Path(self.settings.get('setup_work',''),'setup.private.json')
        if not path.is_file():return
        state=json.loads(path.read_text(encoding='utf-8'))
        if state.get('phase')!='COMPLETE':
            W.QMessageBox.information(self,tr('安装尚未结束'),tr('请点首页“继续安装”，按提示完成后续步骤。'))
            return
        if archive_error(state):write_json(path,state)
        W.QMessageBox.information(self,tr('安装完成'),text(state))

    def refresh_setup_controls(self):
        state,refused=self.setup_saved()
        pending=bool(state) and state.get('phase')!='COMPLETE'
        self.setup_button.setText(tr('继续安装') if pending else tr('开始新的一键安装') if state else tr('一键安装…'))
        self.setup_result_button.setVisible(state.get('phase')=='COMPLETE')
        self.show_setup_note(pending,refused)
        self.setup_custom_container.setEnabled(not pending and not self.setup_presets.isChecked() and self.process is None)
        if not state:
            self.setup_preset_summary.setText(tr(presets.SUMMARY))
            self.setup_preset_summary.setEnabled(self.setup_presets.isChecked())
        for box in (self.setup_presets,self.setup_fl23,self.setup_sound,self.setup_vertical,self.setup_plugin):
            box.setEnabled(not pending and self.process is None)

    def clear_installation_state(self, verified=True):
        # Clear active navigation/resume pointers, not diagnostic evidence or
        # user source files. A verified factory reset invalidates these plans.
        # Before verification only the sound records are retired: the restore
        # has already returned every sound program window to stock.
        if verified:
            for key in ('setup_work','fl23_direct_work','look_direct_work',
                        'look_resume_source','look_job_dir'):
                self.settings.pop(key,None)
            self._look_displayed_pending=None
            self.look_editor.set_operations([])
            self.fl23_accept.setChecked(False)
        self.sound_accept.setChecked(False)
        # The old sound workspace describes the pre-reset camera installation.
        # Start fresh while retaining its files and the selected source clip.
        sound=self.work('sound')
        for key,value in (('sound_work',sound),('sound_backup',sound+'-backup')):
            self.fields[key].setText(value);self.settings[key]=value
        save_settings(self.settings)
        self.log.appendPlainText(tr('原厂恢复已核对通过；已清除旧安装状态。历史诊断日志保留，新安装从头开始。') if verified else
                                 tr('原厂恢复写入已完成；旧的声音记录已停用（文件保留），之后的声音操作不再受它们影响。'))

    def reload_controls(self, group, checks):
        """The restart confirmation as a row of group: the checkbox, and the steps one click away."""
        guide = W.QPushButton(tr('如何断电重开？查看详细步骤'))
        guide.setProperty('quiet', True)
        guide.clicked.connect(lambda: self.show_reload_guide(manual=True))
        self.buttons.append(guide)
        confirm = W.QCheckBox(tr('已拔 USB、等灯停、关机，取下电池至少 1 分钟后重开；\n已确认') + checks)
        confirm.setToolTip(reloadguide.text())
        row = W.QWidget()
        line = W.QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(confirm, 1)
        line.addWidget(guide, 0, QtCore.Qt.AlignTop)
        group.add(row)
        return confirm

    def show_reload_guide(self, *, setup=False, mode=None, manual=False):
        """The cold-restart dialog after a task (titled by what it ended in), or with `manual`, the steps
        alone under their own title: the Help menu and the "How to cold restart…" buttons open it at any
        time, even while a write runs, so it never says that reading and writing have ended."""
        if manual:
            W.QMessageBox.information(self, tr('断电重开步骤'), tr(reloadguide.STEPS))
            return
        title = (tr('恢复尚未开始，请断电后重试') if mode=='factory_prewrite_temporary' else
                 tr('恢复尚未完成，请重启后核对') if mode=='factory_reset' else
                 tr('试听结果已记录，请断电恢复原声') if mode=='sound_confirm' else tr('读写已结束，请断电重开'))
        W.QMessageBox.information(self, title, reloadguide.text(setup=setup, mode=mode))

    def connection_notice_due(self):
        """True only the first time the app opens; afterwards the guide stays in the Help menu and on
        the Connection page, so no alert interrupts every launch."""
        if self.settings.get('connection_notice_seen'):
            return False
        self.settings['connection_notice_seen'] = True
        save_settings(self.settings)
        return True

    def show_connection_notice(self):
        W.QMessageBox.information(self,tr(connectionguide.TITLE),tr(connectionguide.TEXT))

    def field(self, form, key, label, *, kind=None, filter=tr('All files (*)'), value=''):
        line = W.QLineEdit(str(self.settings.get(key, value)))
        line.setObjectName(key)
        self.fields[key] = line
        if kind:
            row = W.QHBoxLayout()
            row.setSpacing(8)
            row.addWidget(line, 1)
            button = W.QPushButton(tr('选择…'))
            button.clicked.connect(lambda: self.browse(line, kind, filter))
            row.addWidget(button)
            form.addRow(label, row)
        else:
            form.addRow(label, line)
        return line

    def browse(self, field, kind, filter):
        if kind == 'folder':
            path = W.QFileDialog.getExistingDirectory(self, tr('选择目录'), field.text())
        elif kind == 'save':
            path = W.QFileDialog.getSaveFileName(self, tr('保存文件'), field.text(), filter)[0]
        else:
            path = W.QFileDialog.getOpenFileName(self, tr('选择文件'), field.text(), filter)[0]
        if path:
            field.setText(path)

    def action_button(self, text, action, arguments=lambda: {}, *, primary=False):
        """A button that launches a worker action; disabled with the others while a task runs."""
        button = W.QPushButton(text)
        button.setObjectName('action_' + action)
        button.setProperty('primary', primary)
        button.clicked.connect(lambda: self.launch(action, arguments()))
        self.buttons.append(button)
        if action in jobs.POWER_ACTIONS:
            self.write_buttons.append(button)
        return button

    def button(self, layout, text, action, arguments=lambda: {}, *, primary=False):
        """An action button sized to its label, placed in layout."""
        button = self.action_button(text, action, arguments, primary=primary)
        if isinstance(layout, W.QVBoxLayout):
            layout.addWidget(button, 0, QtCore.Qt.AlignLeft)
        else:
            layout.addWidget(button)
        return button

    def act(self, group, title, help_text, verb, action, arguments=lambda: {}, *, primary=False):
        """A Settings-style row: what the action does on the leading side, a verb button trailing."""
        return self.act_each(group, title, help_text, [(verb, action, arguments, primary)])[0]

    def act_each(self, group, title, help_text, buttons):
        """One Settings-style row with a button for each (verb, action, arguments, primary), leading to
        trailing: a feature's two opposite writes (Remove…/Enable…, Turn off…/Turn on…) share the row
        that describes them, the undo first and the primary action last, as on the Mac."""
        made = [self.action_button(verb, action, arguments, primary=primary) for verb, action, arguments, primary in buttons]
        group.add(shell.ActionRow(title, help_text, made))
        return made

    def text(self, key):
        return self.fields[key].text().strip()

    def common(self):
        return {'firmware': FIRMWARE}

    def work(self, label):
        return str(data_root() / 'work' / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + label + '-' + uuid.uuid4().hex[:5]))

    def connection_page(self):
        layout = self.page(tr('连接与驱动'), tr('相机开机并选择“海量存储／Mass Storage”，使用可传数据的 USB 线。一次只连接一台相机。'))
        guide = shell.Banner()
        guide.set_kind('info')
        guide.text.setText(tr('相机显示“请检查所连接的设备”是正常现象，以本工具的结果为准。相机操作开始后，不要关机或拔线。') +
                           (tr('相机操作会打开终端窗口，请在其中输入 Mac 登录密码；程序不读取也不保存密码。') if sys.platform == 'darwin' else ''))
        read = W.QPushButton(tr('连接相机前须知…'))
        read.setProperty('quiet', True)
        read.clicked.connect(self.show_connection_notice)
        guide.actions.addWidget(read, 0, QtCore.Qt.AlignVCenter)
        layout.addWidget(guide)
        # macOS needs no driver. There the driver install only repeats Detect's listing (usb_drivers.install
        # returns scan()) and ignores the driver target, and Prepare only opens and closes the service
        # connection, as Test does: the Mac shows neither row, nor the target picker.
        mac = sys.platform == 'darwin'
        form = self.box(layout, tr('USB 连接'))
        if mac:
            self.field(form, 'mac_volume', tr('macOS 相机存储卷'), kind='folder', value='/Volumes/')
        else:
            self.driver_identity = W.QComboBox()
            self.driver_identity.addItems([tr('普通连接 · 054C:0E8A'), tr('服务连接 · 054C:0336')])
            form.addRow(tr('驱动目标'), self.driver_identity)
        group = shell.section(layout, tr('检查与准备'))
        self.act(group, tr('检测相机与驱动'), tr('只读。列出电脑在 USB 上看到的相机和驱动。'), tr('检测'), 'driver_scan', primary=True)
        if sys.platform == 'win32':
            # Manual Zadig installation sits beside the automatic one: many
            # computers where the automatic install fails succeed with it.
            zadig = W.QPushButton(tr('Zadig 指南…'))
            zadig.setObjectName('zadig_guide')
            zadig.clicked.connect(self.show_zadig_guide)
            self.buttons.append(zadig)
            group.add(shell.ActionRow(tr('准备两阶段驱动并测试连接（自动）'),
                                      tr('安装两个连接身份所需的驱动，然后测试连接。自动安装失败时，许多电脑改用 Zadig 手动安装即可成功。'),
                                      [zadig, self.action_button(tr('准备'), 'usb_prepare')]))
        elif not mac:
            self.act(group, tr('准备 USB 服务连接'), tr('让相机进入服务连接，以便读取和写入。'), tr('准备'), 'usb_prepare')
        if not mac:
            self.act(group, tr('单独安装所选身份的驱动（高级）') if sys.platform == 'win32' else tr('检查 USB 访问（macOS 无需 Zadig）'),
                     tr('只为上方选择的连接身份安装驱动。') if sys.platform == 'win32' else tr('确认本机可以访问相机的 USB 接口。'),
                     tr('安装') if sys.platform == 'win32' else tr('检查'), 'driver_install',
                     lambda: {'pid': ['0e8a', '0336'][self.driver_identity.currentIndex()]})
        if mac:
            self.act(group, tr('推出选中的相机存储卷'), tr('在建立服务连接前推出上方选择的存储卷。'), tr('推出'), 'mac_unmount',
                     lambda: {'volume': self.text('mac_volume')})
        self.act(group, tr('测试服务连接（不写固件）'), tr('连接后读取固件版本，然后断开，不写入任何内容。'), tr('测试'), 'connect')
        # What the last connection test found; show_firmware_build keeps it up to date.
        self.build_label = shell.text_label(tr('尚未检测'))
        self.build_label.setObjectName('firmware_build')
        group.add(shell.ActionRow(tr('相机固件版本'), self.build_label))
        self.act(group, tr('检测 USB 连接稳定性（只读）'), tr('反复读取相同文件以检测线缆和接口，只读。'), tr('检查'), 'usb_stability')
        if sys.platform == 'win32':
            self.act(group, tr('卸载相机驱动，恢复 Windows 默认连接'), tr('备份并移除第三方驱动，让 Windows 重新识别相机。'), tr('卸载…'),
                     'driver_uninstall', lambda: {'pids': ['0e8a', '0336']})
        layout.addWidget(shell.text_label(tr('连接中断后先查看完整日志。报错不会触发重新刷写或自动重装驱动。'), 'callout'))
        layout.addStretch()

    def recovery_page(self):
        layout = self.page(tr('恢复原厂功能'), tr('已内置本项目修改区域的原厂 2.01 基准。移除已支持的项目修改，六个自订栏位设为 ST 默认，保留机身校准。无需旧备份或下载完整固件；旧配方不找回。'))
        group = shell.section(layout, tr('原厂 2.01 功能'))
        self.factory_status=shell.text_label(tr('恢复写入后必须按弹窗重启，再接回核对；核对通过前不会标记恢复完成。'), 'callout')
        self.factory_button=self.action_button(tr('恢复／继续恢复原厂 2.01 功能（无需旧备份）'), 'direct_factory_reset',
                    lambda: self.direct_args('factory', mode='factory_reset', factory='builtin'), primary=True)
        self.factory_start_text=self.factory_button.text()
        group.add(shell.ActionRow(tr('移除本工具的修改，六个自订栏位恢复为 ST'), self.factory_status, [self.factory_button]))
        self.factory_accept = self.reload_controls(group, tr('取景、拍照和回放正常'))
        self.act(group, tr('重启后核对并完成恢复（恢复写入后必做）'), tr('恢复写入后必做：确认相机加载了原厂内容。'), tr('核对'), 'direct_verify',
                 lambda: self.direct_verify_args('factory', self.factory_accept.isChecked()))
        layout.addWidget(shell.text_label(tr('相机仍需能够进入 USB 服务通信；此操作不是索尼更新器的降级重刷。'), 'callout'))
        resume_section = self.advanced(layout, tr('恢复事务（自动识别；也可手动选择）'))
        resume_form = self.box(resume_section, '')
        self.field(resume_form, 'factory_failed_work', tr('恢复事务目录（通常自动）'), kind='folder',
                   value=self.settings.get('factory_direct_work', ''))
        expert = self.advanced(layout, tr('导入完整原厂 2.01 参考文件（高级、可选）'))
        reference = self.box(expert, tr('原厂文件'))
        self.field(reference, 'factory_file', 'Sony BODYDATA.DAT', kind='file', filter=tr('Sony firmware (*.DAT *.bin);;All files (*)'))
        steps = shell.section(expert, '')
        self.act(steps, tr('准备所选原厂文件（不连接相机）'), tr('只在电脑上处理文件，不连接相机。'), tr('准备'), 'factory_prepare',
                 lambda: {'source': self.text('factory_file') or str(data_root() / 'factory-2.01')})
        self.act(steps, tr('使用导入的完整原厂文件恢复'), tr('用导入的文件代替内置基准进行恢复。'), tr('恢复…'), 'direct_factory_reset',
                 lambda: self.direct_args('factory', mode='factory_reset', factory=str(data_root() / 'factory-2.01')))
        legacy = self.advanced(layout, tr('使用旧备份回到过去的状态（可选）'))
        self.backup_recovery_controls(legacy)
        layout.addStretch()
        self.refresh_factory_controls()

    def refresh_factory_controls(self):
        work=self.settings.get('factory_direct_work') or self.text('factory_failed_work')
        path=Path(work,'direct.private.json') if work else None
        try:state=json.loads(path.read_text(encoding='utf-8')) if path and path.is_file() else {}
        except (OSError,ValueError):return
        phase=state.get('phase')
        if phase=='AWAITING_RELOAD':
            # The finish button resumes the restore: it verifies first, and writes a fresh restore when the
            # camera has changed since (worker: direct_resume_factory), so it opens the write confirmation.
            self.factory_button.setText(tr('重启后核对并完成恢复'))
            self.factory_status.setText(tr('恢复尚未完成：写入与读回已结束。请断电重启、接回 USB，再点击“重启后核对并完成恢复”；'
                                           '只有相机内容已改变时才会重新写入。'))
        elif phase in ('LOADED','COMPLETE') and state.get('readonly_after_reload_verified'):
            self.factory_button.setText(tr('重新恢复原厂 2.01 功能（无需旧备份）'))
            self.factory_status.setText(tr('上次恢复核对已通过。程序、设置、加载状态及只读挂载已核对；当前功能和拍摄验收以机身为准。'))
        elif phase=='NEEDS_REVIEW':
            refusal=self.firmware_refusal(state)
            if refusal:
                # The gate refused this camera before writing, so there is no transaction to
                # continue. The button starts a new restore, which refuses again until the camera is
                # a supported build.
                self.factory_button.setText(self.factory_start_text)
                self.factory_status.setText(refusal)
                return
            from looktool.factoryrecover import connection_failed_before_restore,prewrite_temporary_conflict
            if prewrite_temporary_conflict(state):
                self.factory_button.setText(tr('断电后重试恢复（本次尚未写入）'))
                self.factory_status.setText(tr('本次恢复尚未写入，遇到相机临时文件冲突。请完整断电重开，接回 USB，再点击“断电后重试恢复”；'
                                               '不需要旧 LUT 记录。'))
                return
            if connection_failed_before_restore(state):
                self.factory_button.setText(tr('恢复原厂 2.01 功能（上次尚未开始）'))
                self.factory_status.setText(tr('上次在 USB 连接阶段停止，尚未开始恢复写入。点击“恢复原厂 2.01 功能（上次尚未开始）”，'
                                               '完成系统授权后重新连接。'))
                return
            self.factory_button.setText(tr('继续恢复／核对未完成事务'))
            self.factory_status.setText(tr('恢复尚未完成，请继续处理未完成事务；当前不代表已恢复成功。'))

    def backup_recovery_controls(self, layout):
        form = self.box(layout, tr('恢复来源'))
        self.field(form, 'restore_backup', tr('备份目录'), kind='folder')
        choose_zip = W.QPushButton(tr('或选择完整备份 ZIP…'))
        choose_zip.clicked.connect(lambda: self.browse(self.fields['restore_backup'], 'file', 'Backup (*.zip);;All files (*)'))
        form.addRow('', choose_zip)
        self.field(form, 'restore_work', tr('恢复任务目录'), kind='folder', value=self.work('recovery'))
        group = shell.section(layout, tr('还原步骤'))
        self.act(group, tr('检查所选备份（离线）'), tr('离线检查备份是否完整，不连接相机。'), tr('检查'), 'backup_inspect',
                 lambda: {'backup': self.text('restore_backup')})
        auto = W.QPushButton(tr('查找并还原…'))
        auto.setObjectName('one_click_restore')
        auto.clicked.connect(self.one_click_restore)
        self.buttons.append(auto)
        self.write_buttons.append(auto)  # launches restore_auto
        group.add(shell.ActionRow(tr('一键还原：查找并使用最初完整备份'), tr('自动找到这台相机最早的完整备份并还原。'), [auto]))
        self.act(group, tr('恢复所选备份并完整读回'), tr('写入上方选择的备份，并完整读回核对。'), tr('还原…'), 'restore',
                 lambda: dict(self.common(), backup=self.text('restore_backup'), workspace=self.text('restore_work')), primary=True)
        self.recovery_accept = self.reload_controls(group, tr('恢复后取景、拍照和回放正常'))
        self.act(group, tr('核对旧备份恢复后的加载状态'), tr('还原后重启相机，再确认它加载了备份内容。'), tr('核对'), 'restore_verify',
                 lambda: {'workspace': self.text('restore_work'), 'accepted': self.recovery_accept.isChecked()})
        layout.addWidget(shell.text_label(tr('相机需要仍可进入服务通信。此入口使用机身备份；不把官方 BODYDATA.DAT 当作备份刷入。'), 'callout'))

    def fl23_page(self):
        layout = self.page('FL2 / FL3', tr('直接启用／移除，不要求创建备份。移除只关闭 FL2／FL3 的列表入口，保留自定义外观所需的共用色彩代码；之后可以重新启用。'))
        group = shell.section(layout, tr('创意外观列表'))
        self.act_each(group, tr('启用／重新启用 FL2 / FL3'),
                      tr('启用会把 FL2 和 FL3 加入相机的创意外观列表，再次启用可修复它们；移除只从列表中隐藏，自定义外观照常可用。'
                         '移除前请先在相机选择 ST。'),
                      [(tr('移除'), 'direct_fl23_disable', lambda: self.direct_args('fl23', mode='fl23_disable'), False),
                       (tr('启用'), 'direct_fl23_enable', lambda: self.direct_args('fl23', mode='fl23_enable'), True)])
        layout.addWidget(shell.text_label(tr('写入读回后按弹窗断电重开，在相机确认即可使用；无需再接电脑核对。'), 'callout'))
        diagnostic = self.advanced(layout, tr('加载核对（可选诊断，不是使用前提）'))
        check = shell.section(diagnostic, '')
        self.fl23_accept = self.reload_controls(check, tr('菜单、拍照和回放正常'))
        self.act(check, tr('只读核对已加载的版本（可选）'), tr('只读：确认相机加载的是新写入的版本。'), tr('核对'), 'direct_verify',
                 lambda: self.direct_verify_args('fl23', self.fl23_accept.isChecked()))
        layout.addStretch()

    def look_page(self):
        from .lookeditor import LookEditor
        layout=self.page(tr('自定义创意外观'),tr('按需添加本次要改的槽位；未添加的槽位保持原样。可在同一批操作中写入外观和恢复 ST 默认。'))
        self.look_pending=shell.text_label('');self.look_pending.setProperty('warning',True);layout.addWidget(self.look_pending)
        self.look_editor=LookEditor();layout.addWidget(self.look_editor)
        actions=W.QHBoxLayout();layout.addLayout(actions)
        actions.addWidget(shell.text_label(tr('同一次操作自动检查当前状态、写入并完整读回。结束后按弹窗断电加载，无需单独点击核对。'),'callout'),1)
        self.look_button=W.QPushButton(tr('添加操作项后继续'));self.look_button.setProperty('primary',True)
        self.look_button.setObjectName('action_direct_looks_import');self.look_button.clicked.connect(self.launch_look_changes)
        actions.addWidget(self.look_button,0,QtCore.Qt.AlignTop);self.buttons.append(self.look_button);self.write_buttons.append(self.look_button)
        tools=shell.section(layout,tr('工具'))
        for title,detail,verb,callback in [
                (tr('打开内置 DCP／A7Look 配对库'),tr('内置的 DCP 配置文件和对应的相机外观文件。'),tr('打开'),self.open_profile_library),
                (tr('从 DCP、LUT 或 HALD 图像生成 A7Look'),tr('写入页选择 .a7look；.cube / .dcp 先用上方工具转换。仅更改清单内的槽位。'),tr('生成…'),self.compiler_dialog),
                (tr('安装 LrC 自动识别插件…'),tr('让 Lightroom Classic 为每张照片自动选择对应的配置文件。'),tr('安装…'),self.plugin_dialog),
                (tr('LUT 格式说明：ST / sRGB，不是 S-Log3…'),tr('哪些 LUT 可以直接转换，以及 Log LUT 怎么处理。'),tr('查看…'),self.show_look_format_guide)]:
            button=W.QPushButton(verb);button.clicked.connect(callback);self.buttons.append(button)
            tools.add(shell.ActionRow(title,detail,[button]))
        layout.addStretch()
        self._look_displayed_pending=None;self._look_refreshing=False
        self.look_editor.changed.connect(self.refresh_look_controls)
        self.look_editor.preview_requested.connect(self.preview_look)
        self.look_editor.library_requested.connect(self.film_library_dialog)
        self.refresh_look_controls()

    def open_profile_library(self):
        from .profilelibrary import location
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(location())))

    def film_library_dialog(self):
        from . import looklibrary
        from .lookviews import FilmLibraryDialog
        try:
            looks=looklibrary.catalog()
        except looklibrary.READ_ERRORS as exc:
            shell.warn(self, tr('胶片外观库无法读取'), exc);return
        if not looks:
            W.QMessageBox.information(self,tr('胶片外观库'),tr('此安装没有附带胶片外观库。'));return
        dialog=FilmLibraryDialog(looks,self,notices=looklibrary.location())
        dialog.add_requested.connect(self.add_library_look)
        dialog.preview_requested.connect(self.preview_look)
        shell.modal(dialog)

    def add_library_look(self,look,slot):
        """Write the library look to slot: update that slot's row, or add one."""
        if not self.look_editor.isEnabled():
            W.QMessageBox.information(self,tr('清单已锁定'),tr('上次操作尚未完成或正在运行，暂时不能修改清单。'));return False
        # A slot without a row is always free, so add_row cannot run out of slots here.
        row=next((r for r in self.look_editor.rows if r.slot.currentData()==slot),None) or self.look_editor.add_row(slot)
        row.action.setCurrentIndex(1);row.set_file(look['path']);row.name.clear()  # the old file's custom name does not apply
        return True

    def preview_look(self,path):
        from .looklibrary import READ_ERRORS
        from .lookviews import PreviewDialog
        try:
            dialog=PreviewDialog(path,cache=data_root()/'preview-cache',parent=self)
        except READ_ERRORS as exc:
            shell.warn(self, tr('无法预览此外观'), exc);return
        shell.modal(dialog)

    def setup_looks(self,arguments):
        """The looks a fresh one-click setup would install, the built-in six expanded, read and
        checked exactly as the worker will; raises on a missing or unreadable file. Needs
        setup_runtime() first."""
        from looktool import bundle
        options,_=bundle.documents(presets.resolve(arguments.get('options',{})))
        return options['looks']

    def confirm_fit(self,looks):
        from .looklibrary import fit_concerns
        from .lookviews import rating_word
        concerns=fit_concerns(looks)
        if not concerns:return True
        lines=[tr('自订 %s：%s（拟合%s）')%(c['slot'],c.get('name') or Path(c['path']).stem,rating_word(c['fit']['rating'])) for c in concerns]
        advice=tr('\n可以预览的外观，建议先预览。') if any(c['fit'].get('preview') for c in concerns) else ''
        return ask(self,tr('拟合提醒'),
            tr('以下外观在机内的拟合较差或未知，相机效果可能与原外观明显不同。\n')+'\n'.join(lines)+advice+tr('\n仍要继续？'),
            tr('仍然继续'))

    def look_pending_state(self):
        """(workspace, state) of the look job still to continue or review; None when there is none: it
        finished, or a firmware refusal stopped it, so there is nothing to continue and
        refresh_look_controls shows the refusal instead."""
        found=self.look_unfinished_state()
        return None if found and self.firmware_refusal(found[1]) else found

    def look_unfinished_state(self):
        prior=self.settings.get('look_direct_work')
        if not prior:return None
        try:
            job=self.settings.get('look_job_dir')
            if job and Path(job,'status.private.json').is_file():
                status=json.loads(Path(job,'status.private.json').read_text(encoding='utf-8'))
                request=json.loads(Path(job,'request.private.json').read_text(encoding='utf-8'))
                matches=prior in (request.get('arguments',{}).get('workspace'),status.get('result',{}).get('workspace'))
                if matches and status.get('phase')=='SUCCEEDED':
                    prior=status['result']['workspace']
                elif matches and status.get('phase') in ('RUNNING','QUEUED') and self.process is None:
                    return prior,dict(phase='BACKGROUND_UNCONFIRMED',error=tr('后台任务尚未确认结束，请等待原结果或查看日志，不重复写入。'))
            if not Path(prior,'direct.private.json').is_file():
                prior=self.settings.get('look_resume_source')
                if not prior or not Path(prior,'direct.private.json').is_file():return None
            state=json.loads(Path(prior,'direct.private.json').read_text(encoding='utf-8'))
            nested=Path(prior,'program-install/direct.private.json')
            if state.get('phase')=='RESOURCE_RELOAD_VERIFIED' and nested.is_file():
                prior=str(nested.parent);state=json.loads(nested.read_text(encoding='utf-8'))
        except (ValueError,OSError,KeyError) as exc:return str(prior),dict(phase='UNREADABLE',error=str(exc))
        return None if state.get('phase') in ('AWAITING_RELOAD','LOADED','COMPLETE') else (prior,state)

    def refresh_look_controls(self):
        if self._look_refreshing:return
        self._look_refreshing=True
        try:
            unfinished=self.look_unfinished_state();busy=self.process is not None
            refusal=self.firmware_refusal(unfinished[1]) if unfinished else ''
            pending=None if refusal else unfinished
            if pending:
                prior,state=pending;phase=state.get('phase')
                token=(prior,phase)
                if self._look_displayed_pending!=token:
                    options=state.get('bundle_options',{});by_slot={r['slot']:r for r in options.get('looks',[])}
                    operations=options.get('slot_operations') or [dict(r,action='write') for r in by_slot.values()]+[dict(slot=n,action='restore') for n in options.get('reset_slots',[])]
                    if not operations and state.get('mode')=='slot_default':operations=[dict(slot=state['slot'],action='restore')]
                    if not operations and state.get('mode')=='look_import':operations=[dict(slot=state['slot'],action='write',path=str(Path(prior)/'reference.a7look'),name=state.get('name') or '')]
                    operations=[dict(r,**{k:v for k,v in by_slot.get(r['slot'],{}).items() if k!='slot'}) if r.get('action')=='write' else r for r in operations]
                    self.look_editor.set_operations(operations);self._look_displayed_pending=token
                self.look_editor.setEnabled(False);self.look_button.setEnabled(not busy)
                if phase in ('AWAITING_RESOURCE_RELOAD','RESOURCE_RELOAD_VERIFIED') or (phase=='NEEDS_REVIEW' and state.get('forward_name_build',{}).get('stream_install') and 'readonly=-16' in state.get('error','')):
                    text=tr('上次操作正在等待资源续接，将沿用已保存的清单。')
                    self.look_button.setText(tr('继续槽位更改'))
                else:
                    from .lookbatch import read_only_failure
                    if read_only_failure(state):
                        text=tr('上次在写入前停止，旧记录已保留；可以调整清单后重试。')
                        self.look_editor.setEnabled(not busy)
                        self.look_button.setText(tr('重试本次更改（上次未写入）'))
                        self.look_button.setEnabled(not busy and bool(self.look_editor.values()) and not self.look_editor.errors())
                    else:
                        text=tr('上次操作尚未完成；请查看原任务记录，不自动重复写入。')
                        self.look_button.setText(tr('查看未完成任务记录'))
                self.look_pending.setText(text);self.look_pending.show()
            else:
                if self._look_displayed_pending is not None:
                    self._look_displayed_pending=None;self.look_editor.set_operations([])
                # A job a firmware refusal stopped is not continued: the plan stays editable beneath the refusal.
                self.look_pending.setText(refusal);self.look_pending.setVisible(bool(refusal));self.look_editor.setEnabled(not busy)
                rows=self.look_editor.values()
                self.look_button.setText(tr('查看并应用这 %d 项更改')%len(rows) if rows else tr('添加操作项后继续'))
                self.look_button.setEnabled(bool(rows) and not self.look_editor.errors() and not busy)
        finally:self._look_refreshing=False
        self.apply_write_gate()

    def look_batch_args(self):
        return self.direct_args('look',operations=self.look_editor.values())

    def launch_look_changes(self):
        pending=self.look_pending_state()
        if pending:
            prior,state=pending;phase=state.get('phase')
            if phase in ('AWAITING_RESOURCE_RELOAD','RESOURCE_RELOAD_VERIFIED') or (phase=='NEEDS_REVIEW' and state.get('forward_name_build',{}).get('stream_install') and 'readonly=-16' in state.get('error','')):
                self.launch('direct_resume_looks',dict(self.common(),workspace=self.work('look'),failed_workspace=prior));return
            from .lookbatch import read_only_failure
            if read_only_failure(state):
                self.launch('direct_looks_import',self.look_batch_args());return
            W.QMessageBox.warning(self,tr('上次任务尚未完成'),(display(state['error']) if state.get('error') else tr('请保留原记录，核对未知结果后再继续。'))+tr('\n任务目录：')+prior)
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(prior));return
        self.launch('direct_looks_import',self.look_batch_args())

    def vertical_page(self):
        layout = self.page(tr('竖屏显示'), tr('竖握相机时，拍摄信息、图标和布局跟随转向。开启会保存原生开关，断电重开后自动生效；不是整个 MENU 转向。'))
        args = lambda: dict(self.common(), workspace=self.text('vertical_work'))
        group = shell.section(layout, '')  # no heading: it would repeat the page title
        self.act_each(group, tr('开启竖屏显示'),
                      tr('开启会保存竖屏开关并应用当前的 Fn／子菜单显示修正；关闭会先关闭竖屏，再撤销显示修正。两个操作都支持重复覆盖。'),
                      [(tr('停用'), 'vertical_disable', args, False), (tr('开启'), 'vertical_enable', args, True)])
        layout.addWidget(shell.text_label(tr('已知显示问题：竖屏创意外观选择页的外框仍偏粗；刻度已横向显示，但橙色指针朝向尚未修正。'), 'callout'))
        layout.addWidget(shell.text_label(tr('开启／关闭会一次完成所选写入和读回，再统一弹窗提示断电加载。相同状态可重复点击，相同内容不重复写入。'), 'callout'))
        folders = self.advanced(layout, tr('显示任务'))
        form = self.box(folders, '')
        self.field(form, 'vertical_work', tr('任务目录'), kind='folder', value=str(data_root() / 'vertical'))
        layout.addStretch()

    def sound_page(self):
        layout = self.page(tr('电子快门声音'), tr('独立开关控制电子快门发声分支。音频转换后可直接保存，临时试听可选；写入后按弹窗断电加载。'))
        args = lambda: dict(self.common(), workspace=self.text('sound_work'), backup=self.text('sound_backup'))
        switch = shell.section(layout, tr('索尼原生快门声'))
        self.act_each(switch, tr('开启电子快门声'),
                      tr('开启后，使用电子快门拍摄时播放快门声（索尼原生声音或已保存的自定义声音），需要相机的“音频信号”设为开；'
                         '关闭后电子快门拍摄时保持静音。断电重开后生效。'),
                      [(tr('停用'), 'sound_off', args, False), (tr('开启'), 'sound_on', args, False)])
        media = self.box(layout, tr('导入音频／视频片段'))
        presets = self.sound_presets()
        if presets:
            self.sound_preset = W.QComboBox()
            self.sound_preset.setObjectName('sound_preset')
            self.sound_preset.addItem(tr('自己的文件'), None)
            for sound in presets:
                self.sound_preset.addItem(sound['name'], sound)
            media.addRow(tr('预设声音'), self.sound_preset)
            self.sound_credit = shell.text_label('', 'callout')
            self.sound_credit.setTextFormat(QtCore.Qt.RichText)
            self.sound_credit.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
            self.sound_credit.setOpenExternalLinks(True)
            media.addRow(self.sound_credit)
        self.field(media, 'sound_source', tr('声音文件'), kind='file', filter=tr('Audio / video (*.wav *.mp3 *.mp4 *.m4a *.flac *.ogg);;All files (*)'))
        self.sound_start = W.QDoubleSpinBox()
        self.sound_start.setRange(0, 86400)
        self.sound_start.setDecimals(3)
        media.addRow(tr('起点（秒）'), self.sound_start)
        self.sound_duration = W.QDoubleSpinBox()
        self.sound_duration.setRange(.01, 2)
        self.sound_duration.setDecimals(3)
        self.sound_duration.setValue(.5)
        media.addRow(tr('长度（秒）'), self.sound_duration)
        if presets:
            self.sound_preset.currentIndexChanged.connect(self.choose_sound_preset)
            self.fields['sound_source'].textChanged.connect(self.match_sound_preset)
            self.match_sound_preset(self.text('sound_source'))
        custom = shell.section(layout, tr('自定义快门声'))
        self.act(custom, tr('转换所选片段'), tr('只在电脑上处理音频，不连接相机。'), tr('转换'), 'sound_import',
                 lambda: dict(args(), source=self.text('sound_source'), start=self.sound_start.value(),
                              duration=self.sound_duration.value(), peak=.4))
        volume = [self.action_button(tr('音量降低 −3 dB'), 'sound_volume', lambda: dict(args(), decibels=-3)),
                  self.action_button(tr('音量提高 +3 dB'), 'sound_volume', lambda: dict(args(), decibels=3)),
                  self.action_button(tr('还原转换时音量'), 'sound_volume', lambda: dict(args(), reset=True))]
        custom.add(shell.ActionRow(tr('音量'), tr('达到上限时自动限制以避免削波；保存时使用调整后的声音。重新转换会重置音量。'), volume))
        self.act(custom, tr('相机内临时试听'), tr('可选：保存前在相机上临时试听。'), tr('试听'), 'sound_audition', args)
        self.act(custom, tr('保存当前自定义声音'), tr('写入相机；工作区和电子快门声支援会自动准备。'), tr('保存到相机…'), 'sound_install', args, primary=True)
        # A write that itself needs a cold restart, so it sits with the sound it replaces, not under the check.
        self.act(custom, tr('恢复原厂音效'), tr('改回相机原来的快门声。'), tr('恢复…'), 'sound_restore_sound', args)
        check = shell.section(layout, tr('重启后'))
        self.sound_accept = self.reload_controls(check, tr('声音正确、拍摄和回放正常'))
        self.act(check, tr('重开后核对声音'), tr('确认相机加载了新的快门声。'), tr('核对'), 'sound_verify',
                 lambda: dict(args(), accepted=self.sound_accept.isChecked()))
        optional=self.advanced(layout,tr('试听确认与恢复记录（可选，不影响保存）'))
        records = shell.section(optional, '')
        self.act(records, tr('确认试听正确'), tr('记录试听时的声音是正确的。'), tr('确认'), 'sound_confirm', lambda: dict(args(), result='correct'))
        self.act(records, tr('已断电恢复原声，记录恢复完成'), tr('试听后已断电恢复原声时，记录恢复完成。'), tr('记录'), 'sound_confirm_recovery', args)
        folders = self.advanced(layout, tr('声音工作区'))
        form = self.box(folders, '')
        self.field(form, 'sound_work', tr('工作目录'), kind='folder', value=str(data_root() / 'sound'))
        self.field(form, 'sound_backup', tr('第二份备份'), kind='folder', value=str(data_root() / 'sound-backup'))
        layout.addStretch()

    def sound_presets(self):
        """The bundled shutter sounds, most loved first; none (with a log line) if the library is unreadable."""
        from . import shuttersounds
        try:
            return shuttersounds.catalog()
        except (OSError, ValueError) as exc:
            self.log.appendPlainText(tr('内置快门声库无法读取，已隐藏预设：') + display(str(exc)))
            return []

    def choose_sound_preset(self, index):
        """A preset fills the clip fields: the bundled file, from its start, for its full length.
        'Your own file' clears a bundled file from the field so the menu and the field agree."""
        sound, source = self.sound_preset.itemData(index), self.fields['sound_source']
        if sound:
            source.setText(str(sound['path']))
            self.sound_start.setValue(0)
            self.sound_duration.setValue(sound['seconds'])
        elif self.preset_index(source.text()):
            source.clear()
        self.show_sound_credit()

    def preset_index(self, path):
        """Index of the preset whose bundled clip path names, however the path is written and from
        whichever copy of the app it was saved (the disk image, Applications); 0 for any other file."""
        chosen = Path(os.path.normpath(path.strip())) if path.strip() else None
        for index in range(1, self.sound_preset.count()):
            bundled = self.sound_preset.itemData(index)['path']
            if chosen is not None and (chosen.parent.name, chosen.name) == (bundled.parent.name, bundled.name):
                return index
        return 0

    def match_sound_preset(self, path):
        """Typing or choosing a file selects its preset, or 'Your own file'. A preset's clip saved
        from another copy of the app is pointed at this copy's."""
        index = self.preset_index(path)
        self.sound_preset.blockSignals(True)
        self.sound_preset.setCurrentIndex(index)
        self.sound_preset.blockSignals(False)
        if index and path != str(self.sound_preset.itemData(index)['path']):
            self.fields['sound_source'].setText(str(self.sound_preset.itemData(index)['path']))
        self.show_sound_credit()

    def show_sound_credit(self):
        """The selected preset's author, licence and source link (the formal attribution with the
        changes made is in the library's CREDITS.txt), or how the presets work."""
        sound = self.sound_preset.currentData()
        if sound is None:
            self.sound_credit.setText(tr('预设按摄影师的喜爱程度排序。选择一款即可自动填入下方的文件、起点和长度。'))
            return
        from .shuttersounds import SOURCE
        source = {key: html.escape(sound['source'][key], quote=True) for key in SOURCE}
        self.sound_credit.setText(tr('“%(title)s”，作者 %(author)s，%(licence)s，来自 <a href="%(url)s">Freesound</a>。') % source)

    def recipe_page(self):
        from . import recipes
        layout=self.page(tr('胶片配方（实验性）'),tr('通过 USB 把创意外观配方（基础外观、八项微调、白平衡偏移和 DRO）写入相机设置；不修改固件。'))
        warning=shell.Banner();warning.set_kind('warning')
        warning.text.setText(tr('实验功能：使用索尼 PC 遥控协议，尚未在 α7C II 实机上验证。每次先只读读取相机并列出全部更改，确认后才写入，写入后逐项读回核对。'))
        layout.addWidget(warning)
        layout.addWidget(shell.text_label(tr('相机设置：菜单 > 设置 > USB > USB 连接模式选“PC 遥控”，模式拨盘置于 P／A／S／M。先退出“照片”、“图像捕获”、Lightroom 和 Imaging Edge。'),'callout'))
        form=self.box(layout,tr('配方'))
        self.recipe_preset=W.QComboBox()
        for preset in recipes.PRESETS:self.recipe_preset.addItem(preset.name)
        form.addRow(tr('预设'),self.recipe_preset)
        self.recipe_target=W.QComboBox();self.recipe_target.addItem(tr('直接调整基础外观'),None)
        for slot in range(1,7):self.recipe_target.addItem(tr('存入自订外观 %d')%slot,slot)
        form.addRow(tr('写入位置'),self.recipe_target)
        self.recipe_details=shell.text_label('','callout');self.recipe_details.setTextFormat(QtCore.Qt.RichText)
        self.recipe_details.setOpenExternalLinks(True);form.addRow(self.recipe_details)
        self.recipe_preset.currentIndexChanged.connect(self.show_recipe);self.show_recipe()
        self.recipe_ptpcamerad=W.QCheckBox(tr('允许暂时停止 macOS 相机服务 ptpcamerad（仅限当前用户，系统会自动重新启动它）'))
        self.recipe_ptpcamerad.setToolTip(tr('ptpcamerad 会占用相机的 PC 遥控接口。勾选后，本工具连接前先结束它；不需要管理员密码。'))
        connection=shell.section(layout,tr('连接'))
        consent=connection.add(shell.CheckRow(self.recipe_ptpcamerad,tr('ptpcamerad 会占用相机的 PC 遥控接口。勾选后，本工具连接前先结束它；不需要管理员密码。')))
        consent.parentWidget().setVisible(sys.platform=='darwin')
        self.recipe_ptpcamerad.setVisible(sys.platform=='darwin')
        self.recipe_windows_note=shell.text_label(tr('Windows 需要为 PC 遥控接口安装 WinUSB 驱动，本工具暂不提供，因此此功能在 Windows 上停用。'),'callout')
        self.recipe_windows_note.setVisible(sys.platform=='win32')
        connection.add(self.recipe_windows_note).parentWidget().setVisible(sys.platform=='win32')
        actions=W.QHBoxLayout();layout.addLayout(actions)
        actions.addWidget(shell.text_label(tr('只读：先列出全部更改，确认后才写入。'),'callout'),1)
        self.recipe_button=self.button(actions,tr('读取相机并列出更改（只读）'),'recipe_plan',self.recipe_args,primary=True)
        if sys.platform=='win32':
            self.buttons.remove(self.recipe_button);self.recipe_button.setEnabled(False)
        layout.addStretch()

    def selected_recipe(self):
        import dataclasses
        from . import recipes
        return dataclasses.replace(recipes.PRESETS[self.recipe_preset.currentIndex()],target=self.recipe_target.currentData())

    def show_recipe(self):
        import html
        from . import recipes
        recipe=recipes.PRESETS[self.recipe_preset.currentIndex()]
        def text(value):return html.escape(value,quote=False)
        sliders=tr('、').join('%s %s'%(s.label,recipes.display_value(s.code,v)) for s,v in recipe.slider_values())
        balance=recipe.white_balance+(' %d K'%recipe.kelvin if recipe.kelvin else '') if recipe.white_balance else tr('保持相机当前模式')
        shifts=tr('白平衡偏移 %s · %s')%(recipes.display_value(recipes.WB_SHIFT_AB,recipes.wb_shift_wire(recipe.wb_shift_ab)),
                                      recipes.display_value(recipes.WB_SHIFT_GM,recipes.wb_shift_wire(recipe.wb_shift_gm)))
        source=text(recipe.source)+(text(tr('；'))+'<a href="%s">%s</a>'%(html.escape(recipe.source_url),text(recipe.source_url)) if recipe.source_url else '')
        lines=[text(tr('基础外观 %s')%recipe.base_look+tr('；')+sliders),
               text(tr('白平衡：%s')%balance+tr('；')+shifts+tr('；')+tr('DRO：%s')%(recipe.dro or tr('不变'))),
               text(tr('来源：'))+source]
        if recipe.note:lines.append(text(tr('说明：')+recipe.note))
        self.recipe_details.setText('<br>'.join(lines))

    def recipe_args(self):
        from .actions.recipe import recipe_args
        return dict(recipe=recipe_args(self.selected_recipe()),stop_ptpcamerad=self.recipe_ptpcamerad.isChecked())

    @staticmethod
    def recipe_change(row):
        from .recipes import change_text
        return change_text(row['label'],None if row['provisional'] else row['before'],row['after'])

    @staticmethod
    def bullets(rows):
        return '\n'.join('• '+row for row in rows)

    def review_recipe_plan(self,result):
        lines=self.bullets
        notes=['%s: %s'%(p['label'],p['reason']) for p in result['problems'] if not p['blocking']]
        if not result['ok']:
            blockers=['%s: %s'%(p['label'],p['reason']) for p in result['problems'] if p['blocking']]
            W.QMessageBox.warning(self,tr('无法写入此配方'),tr('相机不接受以下设置，未写入任何内容：\n')+lines(blockers));return
        if not result['writes']:
            W.QMessageBox.information(self,tr('无需写入'),tr('相机设置已与此配方一致。'));return
        now=[self.recipe_change(r) for r in result['writes'] if not r['provisional']]
        later=[self.recipe_change(r) for r in result['writes'] if r['provisional']]
        text=tr('将写入以下 %d 项相机设置：\n')%len(result['writes'])+lines(now)
        if later:text+=tr('\n\n切换外观或白平衡后，先重新读取相机，再写入：\n')+lines(later)
        if notes:text+=tr('\n\n说明：\n')+lines(notes)
        text+=tr('\n\n这是实验功能，尚未在 α7C II 实机上验证。每项写入后读回核对；如有设置未生效或其他设置被改变，会停止并报告。写入期间不要操作相机或拔线。\n现在写入？')
        if ask(self,tr('写入配方（实验性）'),text,tr('写入配方')):
            self.launch('recipe_apply',dict(recipe=result['recipe'],stop_ptpcamerad=result['stop_ptpcamerad'],reviewed=result['steps']))

    def show_zadig_guide(self):
        from .zadigguide import TITLE, TEXT, URL
        dialog = W.QDialog(self); dialog.setWindowTitle(tr(TITLE)); dialog.resize(820, 680)
        layout = W.QVBoxLayout(dialog)
        content = W.QTextBrowser(); content.setPlainText(tr(TEXT)); layout.addWidget(content)
        row = W.QHBoxLayout(); layout.addLayout(row)
        download = W.QPushButton(tr('打开 Zadig 下载页')); download.setProperty('primary', True)
        download.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl(URL)))
        close = W.QPushButton(tr('关闭')); close.clicked.connect(dialog.accept)
        row.addWidget(download); row.addWidget(close)
        shell.modal(dialog)

    def show_look_format_guide(self):
        from .lookguide import TITLE,TEXT
        dialog=W.QDialog(self);dialog.setWindowTitle(tr(TITLE));dialog.resize(800,650)
        layout=W.QVBoxLayout(dialog)
        content=W.QTextBrowser();content.setPlainText(tr(TEXT));layout.addWidget(content)
        close=W.QPushButton(tr('关闭'));close.clicked.connect(dialog.accept);layout.addWidget(close)
        shell.modal(dialog)

    def compiler_dialog(self):
        from looktool.compilelook import DEFAULT_CALIBRATION
        dialog = W.QDialog(self)
        dialog.setWindowTitle(tr('生成 A7Look'))
        layout = W.QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        layout.addWidget(shell.text_label(tr('CUBE：输入必须是 Sony ST / sRGB，输出 sRGB；不能直接使用 S-Log3 / S-Gamut3.Cine 或其他 Log LUT。\nDCP：内置离线解析与拟合，不需要 Lightroom、插件或联网。转换 LookTable／色调曲线，机内效果为拟合近似。\nTIFF：在 DxO PhotoLab／FilmPack 等软件中处理过的 HALD 图像（用下方按钮生成和检查）。此工具只生成 .a7look，不写相机。'), 'callout'))
        form = self.box(layout, tr('源文件与输出'))
        self.field(form, 'compile_source', 'DCP / CUBE / TIFF', kind='file', filter=tr('Reference (*.dcp *.cube *.tif *.tiff)'))
        self.field(form, 'compile_name', tr('外观名称'))
        self.field(form, 'compile_output', tr('输出 A7Look'), kind='save', filter='A7Look (*.a7look)')
        self.field(form, 'compile_model', tr('响应文件'), kind='file', filter=tr('Response (*.npz)'),
                   value=str(DEFAULT_CALIBRATION))
        tools = []
        for name, title, callback in (('hald_identity', tr('保存用于 DxO 的 HALD 图像…'), self.save_hald_identity),
                                      ('hald_check', tr('检查 HALD 导出…'), self.check_hald_export)):
            button = W.QPushButton(title)
            button.setObjectName(name)
            button.clicked.connect(callback)
            tools.append(button)
        shell.section(layout, tr('用 DxO 制作外观')).add(shell.ActionRow(
            tr('HALD 图像'), tr('保存 HALD 图像，在 DxO 中只加胶片渲染后导出 TIFF，再把导出的 TIFF 选为上方的源文件。'), tools))
        layout.addStretch()
        # Apple order: the supporting action leading; Cancel, then the verb, trailing.
        actions = W.QHBoxLayout()
        actions.setSpacing(8)
        layout.addLayout(actions)
        formats = W.QPushButton(tr('支持的 LUT 格式…'))
        formats.setObjectName('compile_formats')
        formats.clicked.connect(self.show_look_format_guide)
        actions.addWidget(formats)
        actions.addStretch()
        cancel = W.QPushButton(tr('取消'))
        cancel.setObjectName('compile_cancel')
        cancel.clicked.connect(dialog.reject)
        actions.addWidget(cancel)
        run = W.QPushButton(tr('开始生成'))
        run.setObjectName('compile_run')
        run.setProperty('primary', True)
        run.clicked.connect(lambda: (dialog.accept(), self.launch('compile_look', {
            'source': self.text('compile_source'), 'name': self.text('compile_name'),
            'output': self.text('compile_output'), 'model': self.text('compile_model'),
            'input_space': 'sony-st-srgb', 'passes': 3})))
        actions.addWidget(run)
        dialog.resize(760, max(420, dialog.sizeHint().height()))  # long translations need more height
        try:
            shell.modal(dialog)
        finally:
            self.release_fields(dialog)

    def release_fields(self, dialog):
        """Keep a closing dialog's field values in the settings and forget its fields: the dialog is
        deleted, and the window reads every field it knows whenever a task starts or ends."""
        for key in [key for key, field in self.fields.items() if dialog.isAncestorOf(field)]:
            self.settings[key] = self.fields.pop(key).text()
        save_settings(self.settings)

    def save_hald_identity(self):
        from looktool import hald
        path=W.QFileDialog.getSaveFileName(self,tr('保存 HALD 图像'),'a7c2-hald.tif','TIFF (*.tif)')[0]
        if not path:return
        try:hald.write_identity(path)
        except (OSError,ValueError) as exc:
            shell.warn(self, tr('保存失败'), exc);return
        W.QMessageBox.information(self,tr('HALD 图像已保存'),
            tr('在 DxO PhotoLab 中打开此图像，先应用“无校正”预设，再只应用 FilmPack 胶片渲染；不要加颗粒、暗角、锐化或其他效果。以原尺寸导出为未压缩的 16 位 TIFF（sRGB），再把导出的 TIFF 选为这里的源文件。'))

    def check_hald_export(self):
        from looktool import hald
        path=W.QFileDialog.getOpenFileName(self,tr('选择导出的 HALD'),'',tr('TIFF (*.tif *.tiff)'))[0]
        if not path:return
        try:
            _,report=hald.accept(hald.read(path))
        except ValueError as exc:
            shell.warn(self, tr('HALD 导出有问题'), exc);return
        if report['identity_error_max']<=hald.CLEAN:
            text=tr('导出与原始 HALD 一致（最大差 %.2f 级）：没有开启任何自动校正。用同样的设置导出胶片外观。')%report['identity_error_max']
        else:
            text=tr('两份副本一致，没有颗粒或暗角。导出与原始 HALD 最多相差 %.2f 级（已应用外观时属正常）。')%report['identity_error_max']
        W.QMessageBox.information(self,tr('HALD 检查结果'),text)

    def plugin_dialog(self):
        self.launch('plugin_install', {})

    def one_click_restore(self):
        roots = [str(data_root() / 'backups'), str(data_root() / 'initial-checkpoints')]
        for key in ('fl23_backup', 'look_backup', 'restore_backup'):
            if key in self.fields and self.text(key):
                roots.append(self.text(key))
        self.fields['restore_work'].setText(self.work('recovery'))
        self.launch('restore_auto', dict(self.common(), roots=roots, workspace=self.text('restore_work')))

    def launch(self, action, arguments):
        if self.process is not None:
            return
        factory_finished = False
        fit_looks = []  # looks a fresh write would install, for the fit warning
        if action == 'setup_all' and not Path(arguments['workspace'], 'setup.private.json').is_file():
            from .worker import setup_runtime
            setup_runtime()  # looktool becomes importable only here
            from .looklibrary import READ_ERRORS
            try:
                fit_looks = self.setup_looks(arguments)
            except READ_ERRORS as exc:  # before any driver, fit, power or administrator prompt
                shell.warn(self, tr('请检查所选外观'), exc); return
        if action == 'setup_all' and not self.drivers_first(arguments):
            return
        if action=='direct_looks_import' and arguments.get('failed_workspace'):
            action='direct_resume_looks'
        if action=='direct_looks_import':
            from .worker import setup_runtime
            setup_runtime()  # looktool becomes importable only here
            from .looklibrary import READ_ERRORS
            try:
                from .lookbatch import options
                chosen=options(arguments.get('operations',arguments.get('looks',[])))
                arguments=dict(arguments,operations=chosen['slot_operations'])
                fit_looks=[r for r in arguments['operations'] if r['action']=='write']
            except READ_ERRORS as exc:
                shell.warn(self, tr('请检查操作清单'), exc);return
        if action == 'sound_audition':
            from .actions.sound import has_conversion
            try:
                ready = has_conversion(arguments['workspace'])
            except (ValueError, OSError, KeyError) as exc:
                shell.warn(self, tr('声音工作区需要核对'), exc);return
            if not ready:
                W.QMessageBox.information(self, tr('请先转换片段'), tr('还没有转换好的声音。请先选择声音文件、设置起点和长度，点「转换所选片段」，成功后再试听。'));return
        if action == 'restore_verify' and not Path(arguments.get('workspace', ''), 'rollback.private.json').is_file():
            # This button checks a backup restore only. A built-in or firmware
            # file restore is checked by the factory verification button.
            if not ask(self, tr('这里没有旧备份恢复记录'),
                tr('“核对旧备份恢复后的加载状态”只用于“使用旧备份回到过去的状态”。\n'
                '用内置原厂基准或固件文件恢复后，应点“重启后核对并完成恢复”。\n现在改为核对原厂恢复？'),
                tr('核对原厂恢复')):
                return
            action, arguments = 'direct_verify', self.direct_verify_args('factory', bool(arguments.get('accepted')))
        if action == 'direct_factory_reset':
            # A failed fresh attempt must not hide the original interrupted
            # transaction. Resolve the explicitly selected evidence locally,
            # before the power/write confirmation and before any USB access.
            from .worker import setup_runtime
            setup_runtime()
            from looktool.factoryrecover import pending, FINISHED
            try:
                found = pending(data_root() / 'work', self.text('factory_failed_work'))
            except (ValueError, OSError):
                found = None  # Records are evidence only; the worker re-plans.
            if found:
                # A finished restore is verified first; the worker re-plans
                # from current bytes if the camera changed since then.
                original, prior = found
                factory_finished = prior['phase'] in FINISHED
                action = 'direct_resume_factory'
                arguments = dict(arguments, failed_workspace=str(original), accepted=self.factory_accept.isChecked())
        if action == 'driver_uninstall':
            if not ask(self, tr('卸载相机驱动'),
                tr('将备份并卸载 Sony 054C:0E8A／0336 的第三方驱动，让 Windows 重新识别相机。\n'
                '完成后可能需要拔插 USB，重新选择海量存储模式。此操作不修改相机固件。\n现在卸载？'),
                tr('卸载驱动')):
                return
        if fit_looks and not self.confirm_fit(fit_looks):
            return
        writing = action in jobs.POWER_ACTIONS
        if writing:
            target = ((tr('首页勾选的功能；替换自订 1–6：') + tr(presets.SUMMARY) if arguments.get('options', {}).get('preset_pack') else tr('首页勾选的功能及所选 A7Look 槽位')) if action == 'setup_all' else
                      tr('自动选择已连接机身最早可用的完整备份') if action == 'restore_auto' else
                      arguments.get('backup') if action == 'restore' else
                      tr(WRITE_TARGETS[action]) if action in WRITE_TARGETS else arguments.get('look') or arguments.get('workspace'))
            if action in jobs.DIRECT_ACTIONS:
                target = (tr('；').join(tr('自订 %s → %s') % (r['slot'], tr('恢复 ST 默认') if r['action']=='restore' else tr('写入 ')+r['name']) for r in arguments.get('operations', []))
                          if action == 'direct_looks_import' else
                          tr('继续已写好名称的外观安装：')+arguments.get('failed_workspace','') if action=='direct_resume_looks' else
                          (tr('核对上次恢复；相机内容若已改变，则按当前字节重新恢复：') if factory_finished else
                           tr('继续完成名称／设置恢复：')) + arguments.get('failed_workspace', '') if action == 'direct_resume_factory' else
                          tr('原厂 2.01 功能') if action == 'direct_factory_reset' else
                          tr('FL2／FL3：启用') if action == 'direct_fl23_enable' else
                          tr('FL2／FL3：从列表移除') if action == 'direct_fl23_disable' else
                          tr('自订 %s：%s') % (arguments.get('slot'), tr('ST 默认') if action == 'direct_slot_default'
                                           else arguments.get('name') or Path(arguments.get('look', '')).stem))
            scope = (tr('一次应用清单内的写入和恢复，未添加的槽位保持原样；保留 FL23、声音和竖屏。写入读回完成后统一提示断电重开。\n') if action=='direct_looks_import' else
                     tr('自动准备 USB 连接并安装首页勾选的功能。断电重开必须由你按提示完成；结果不明时停止，不自动重复刷写。\n') if action == 'setup_all' else
                     tr('先只读核对；只有相机内容已改变时才按当前字节写入，已符合原厂的内容不重复写入。\n') if action == 'direct_resume_factory' and factory_finished else
                     tr('根据当前字节继续未完成阶段，已恢复的内容不重复写入；原失败事务保留，结果不明时先读取报告核对。\n') if action == 'direct_resume_factory' else
                     tr('将移除项目程序修改、将六个自订栏位设为 ST 默认；旧配方不找回。请先在相机选择 ST。\n') if action == 'direct_factory_reset' else
                     tr('只关闭 FL2／FL3 列表入口，保留 LUT 与共用代码。请先在相机选择 ST。\n') if action == 'direct_fl23_disable' else
                     tr('将所选自订栏位设为 ST 默认，保留其他栏位。\n') if action == 'direct_slot_default' else '')
            if not ask(self, tr('开始相机写入'),
                scope + tr('目标：') + str(target) + tr(WRITE_CHECKS),
                tr('写入相机')):
                return
            arguments = dict(arguments, power_confirmed=True)
            arguments.pop('battery', None)
        if action in jobs.DIRECT_ACTIONS:
            group = 'factory' if action in ('direct_factory_reset', 'direct_resume_factory') else 'fl23' if 'fl23' in action else 'look'
            self.settings[group + '_direct_work'] = arguments['workspace']
            if group=='look':
                self.settings['look_resume_source']=arguments.get('failed_workspace','')
            if group!='look':getattr(self, group + '_accept').setChecked(False)
        if action == 'setup_all':
            self.settings['setup_work'] = arguments['workspace']
            self.setup_button.setText(tr('正在安装…'))
            for box in (self.setup_presets,self.setup_fl23,self.setup_sound,self.setup_vertical,self.setup_plugin):box.setEnabled(False)
        for key, field in self.fields.items():
            self.settings[key] = field.text()
        save_settings(self.settings)
        self.current_job = jobs.new_job(action, arguments)
        if action in ('direct_looks_import','direct_resume_looks') or (action=='direct_verify' and arguments.get('workspace')==self.settings.get('look_direct_work')):
            self.settings['look_job_dir']=str(self.current_job)
            save_settings(self.settings)
        self.log_offset = 0
        self.log.clear()
        self.camera_operation = action in jobs.CAMERA_ACTIONS or action in jobs.REMOTE_ACTIONS or action == 'driver_install'
        for button in self.buttons:
            button.setEnabled(False)
        self.look_editor.setEnabled(False)
        self.stop.setEnabled(not self.camera_operation)
        self.progress.setRange(0, 0)
        self.status.setText(tr('正在操作相机。完成前不要关机或拔线。') if self.camera_operation else
                            tr('正在电脑上处理，不写入相机。'))
        self.stop.setToolTip('' if not self.camera_operation else tr('相机任务不能安全中途停止；请等待它完成。'))
        self.set_state('info')
        self.process = QtCore.QProcess(self)
        self.process.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        env = QtCore.QProcessEnvironment.systemEnvironment()
        env.insert('PYTHONUTF8', '1')
        env.insert('PYTHONIOENCODING', 'utf-8')
        self.process.setProcessEnvironment(env)
        command = jobs.worker_command(self.current_job / 'request.private.json')
        self.process.readyReadStandardOutput.connect(self.process_output)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        self.process.start(command[0], command[1:])

    def process_output(self):
        text = bytes(self.process.readAllStandardOutput()).decode('utf-8', errors='replace')
        if text:
            with (self.current_job / 'process.log').open('a', encoding='utf-8') as stream:
                stream.write(text)
            self.append_log(text.rstrip())

    def append_log(self, text):
        """Worker output in the log pane, in the interface language; worker.log and process.log keep it
        as written."""
        self.log.appendPlainText(display(text))

    def tail_log(self):
        if not self.current_job:
            return
        path = self.current_job / 'worker.log'
        if path.exists():
            with path.open('rb') as stream:
                stream.seek(self.log_offset)
                text = stream.read()
                self.log_offset = stream.tell()
            if text:
                self.append_log(text.decode('utf-8', errors='replace').rstrip())

    def poll_job(self):
        self.tail_log()
        if self.process is None and (self._look_displayed_pending is not None or self.look_pending_state()):self.refresh_look_controls()
        # The status file also recovers completion if Qt missed its signal.
        if self.process is not None and self.process.state() == QtCore.QProcess.NotRunning:
            self.finished(self.process.exitCode(), self.process.exitStatus())

    def finished(self, code, exit_status):
        if self.process is None:
            return
        self.tail_log()
        status_path = self.current_job / 'status.private.json'
        status = json.loads(status_path.read_text(encoding='utf-8')) if status_path.exists() else {}
        success = code == 0 and status.get('phase') == 'SUCCEEDED'
        result = status.get('result') or {}
        connection_checked = success and status.get('action') == 'connect' and 'firmware_build' in result
        if connection_checked:
            self.show_firmware_build(result['firmware_build'])
        elif success and status.get('action') == 'connect':
            self.show_firmware_unchecked()  # the worker named no build: an earlier answer no longer holds
        elif not success and status.get('error_type') == 'UnsupportedFirmware':
            self.show_firmware_build(None)  # the gate refused this camera: it is no build the tool supports
        if success and (status.get('action') in ('usb_prepare', 'connect') or
                        (status.get('action') == 'setup_all' and 'drivers' in status.get('result', {}).get('completed_steps', []))):
            self.settings['connection_verified'] = True
        if success and status.get('action') == 'restore_auto':
            self.fields['restore_backup'].setText(status['result']['backup'])
            self.fields['restore_work'].setText(status['result']['workspace'])
        if success and status.get('action') == 'look_restore' and 'look_work' in self.fields:
            self.fields['look_work'].setText(status['result']['workspace'])
        if success and status.get('action') in ('direct_factory_reset', 'direct_resume_factory'):
            self.settings['factory_direct_work'] = status['result']['workspace']
            self.fields['factory_failed_work'].setText(status['result']['workspace'])
        if success and status.get('action')=='direct_verify' and status['result'].get('mode')=='factory_reset':
            self.settings['factory_direct_work']=status['result']['workspace']
        if success and (status.get('action') in ('direct_looks_import','direct_resume_looks') or
                (status.get('action')=='direct_verify' and status['result'].get('mode') in ('install_all','look_import','slot_default'))):
            self.settings['look_direct_work']=status['result']['workspace']
            self.settings.pop('look_resume_source',None)
        if success and status.get('action') == 'setup_all':
            for key in ('sound_workspace','sound_backup'):
                target='sound_work' if key=='sound_workspace' else 'sound_backup'
                if status['result'].get(key):self.fields[target].setText(status['result'][key])
        for key, field in self.fields.items():
            self.settings[key] = field.text()
        save_settings(self.settings)
        waiting=success and reloadguide.required(status.get('action'),status.get('result',{}))
        sound_notice=reloadguide.sound_notice(status.get('action'),status.get('result',{})) if success else None
        factory_wait=success and status.get('result',{}).get('mode')=='factory_reset' and status['result'].get('phase')=='AWAITING_RELOAD'
        factory_done=success and status.get('result',{}).get('mode')=='factory_reset' and status['result'].get('phase') in ('LOADED','COMPLETE')
        if factory_done:self.clear_installation_state()
        elif factory_wait:self.clear_installation_state(verified=False)
        resource_wait=status.get('result',{}).get('phase') in ('WAIT_RESOURCE_RELOAD','AWAITING_RESOURCE_RELOAD')
        resource_ready=success and status.get('result',{}).get('phase')=='RESOURCE_RELOAD_VERIFIED'
        setup_wait=waiting and status.get('action')=='setup_all'
        self.status.setText((tr('名称已写好，程序尚未写入。按弹窗断电重开、接回 USB，再点击首页“继续安装”。') if resource_wait and setup_wait else
                             tr('名称已写好，程序尚未写入。按弹窗断电重开、接回 USB，再点自定义外观页“继续槽位更改”。') if resource_wait else
                             tr('批量外观写入完成，已完整读回；按弹窗统一断电重开即可加载。') if status.get('action')=='direct_looks_import' else
                             tr('FL2／FL3 已启用：写入并完整读回。重开相机后生效，无需再点核对。') if
                             status.get('result',{}).get('mode')=='fl23_enable' else
                             tr('FL2／FL3 已从列表移除：写入并完整读回。重开相机后生效，无需再点核对。') if
                             status.get('result',{}).get('mode')=='fl23_disable' else
                             tr('读写已结束。拔 USB → 等灯停 → 关机并等灯灭 → 取电池至少 1 分钟 → 开机 → 接回 USB → 点击首页“继续安装”。详见弹窗。') if setup_wait else
                             tr('读写已结束。拔 USB → 等灯停 → 关机并等灯灭 → 取电池至少 1 分钟 → 开机；详见弹窗。')) if waiting else
                           tr('名称与只读挂载已确认；程序尚未安装，请点首页“继续安装”。') if resource_ready and status.get('action')=='setup_all' else
                           tr('名称与只读挂载已确认；程序尚未安装，请点自定义外观页“继续槽位更改”。') if resource_ready else
                           tr('完成。详情见日志。') if success else
                           self.stopped_text(status, code))
        if success and status.get('action')=='recipe_apply':self.status.setText(tr('配方已写入并读回核对。'))
        refused_build=connection_checked and self.build_unsupported
        if refused_build:self.status.setText(self.build_label.text())
        if not success and sys.platform == 'win32' and self.driver_step_failed(status.get('action')):
            self.status.setText(self.status.text() + tr(DRIVER_HINT))
        if sound_notice:self.status.setText(sound_notice['status'])
        if factory_wait:self.status.setText(tr('恢复尚未完成：写入和读回已结束，必须断电重启、接回 USB，再点“重启后核对并完成恢复”。'))
        elif factory_done:self.status.setText(tr('原厂恢复核对通过，旧安装状态已清除。请继续检查机身拍摄和回放；重新安装请点首页“一键安装”。'))
        self.progress.setRange(0, 100)
        self.progress.setValue(70 if factory_wait else 0 if sound_notice and status.get('action')=='sound_install' else
                              40 if success and (resource_wait or resource_ready) else 70 if waiting and status.get('action')=='setup_all' else 100 if success else 0)
        for button in self.buttons:
            button.setEnabled(True)
        self.stop.setEnabled(False)
        self.set_state('danger' if not success else 'warning' if (waiting or resource_wait or resource_ready or factory_wait or sound_notice or refused_build)
                       else 'success')
        self.process.deleteLater()
        self.process = None
        if success and status.get('action') in ('direct_looks_import','direct_resume_looks','direct_verify') and status.get('result',{}).get('mode') in ('install_all','look_import','slot_default') and status['result'].get('phase') in ('COMPLETED','AWAITING_RELOAD','LOADED','COMPLETE') and (status['action']!='direct_verify' or self._look_displayed_pending is not None):
            self.look_editor.set_operations([])
        self.refresh_look_controls()
        self.refresh_setup_controls()
        self.refresh_factory_controls()
        self.apply_write_gate()
        if not success and status.get('action')=='direct_factory_reset':
            from looktool.factoryrecover import prewrite_temporary_conflict
            work=self.settings.get('factory_direct_work')
            path=Path(work,'direct.private.json') if work else None
            try:state=json.loads(path.read_text(encoding='utf-8')) if path and path.is_file() else {}
            except (OSError,ValueError):state={}
            if prewrite_temporary_conflict(state) and state.get('error')==status.get('error'):
                self.status.setText(tr('本次恢复尚未写入。按弹窗完整断电、接回 USB，再点“断电后重试恢复”。'))
                self.show_reload_guide(mode='factory_prewrite_temporary')
        if sound_notice:
            W.QMessageBox.information(self,sound_notice['title'],sound_notice['text'])
        elif success and status.get('action')=='recipe_plan':
            self.review_recipe_plan(status['result'])
        elif success and status.get('action')=='recipe_apply':
            W.QMessageBox.information(self,tr('配方已写入'),tr('已写入并读回核对：\n')+self.bullets(self.recipe_change(row) for row in status['result']['written']))
        elif status.get('action')=='usb_stability':
            if success:
                result=status['result']
                W.QMessageBox.information(self,tr('USB 只读检测通过'),
                    tr('已完成 %d 轮、共 %.1f MB 程序文件只读传输，持续 %.0f 秒，每轮字节一致。\n\n没有写入固件、设置或运行原生写入程序。\n\n%s')%
                    (len(result['rounds']),result['total_bytes']/1024/1024,result.get('seconds',0),display(result['note'])))
            else:
                error=status.get('error',tr('请查看日志并换线后重测。'))
                W.QMessageBox.warning(self,tr('USB 连接检测未完成') if '未完成' in error else tr('USB 连接检测未通过'),display(error))
        elif waiting:
            self.show_reload_guide(setup=status.get('action')=='setup_all', mode=('resource_reload' if resource_wait else status.get('action') if
                status.get('action','').startswith('sound_') else status.get('result',{}).get('mode')))
        elif success and status.get('action')=='setup_all' and status.get('result',{}).get('phase')=='COMPLETE':
            self.status.setText(tr('安装完成。可查看上次安装结果，无需再次刷写。'))
            self.setup_button.setText(tr('开始新的一键安装'))
            self.setup_result_button.setVisible(True)
            for box in (self.setup_presets,self.setup_fl23,self.setup_sound,self.setup_vertical,self.setup_plugin):box.setEnabled(True)
            self.show_setup_result()

    def stopped_text(self, status, code):
        """The banner for a job that stopped: its error, then "Export diagnostics to report it" unless the
        error gives its own next step already (en_engine.NEXT_STEP), such as a click or a cold restart. A
        worker that quit without a status has an unknown result, so it always gets the suffix."""
        stopped = tr('操作停止：') + (self.error_text(status) if 'error' in status else tr('进程异常退出，退出码 ') + str(code))
        if 'error' in status and catalogue_entry(status['error']) in NEXT_STEP:
            return joined(stopped, tr('。'))
        return joined(stopped, tr('。请导出诊断包。'))

    def show_firmware_build(self, key):
        """The Connection page's line for what the connection test found: the supported build named by
        `key`, or no supported build (key None, or one this release does not know). The latter disables
        every button that writes to the camera, until a later test finds a supported one."""
        from looktool.buildprofile import by_key
        build = by_key(key) if key else None
        self.set_build_line(tr(build.label_zh) if build else tr('固件版本不受支持：已禁用更改'), unsupported=build is None)

    def show_firmware_unchecked(self):
        """The Connection page's line as at launch: no build checked yet. As before any test, the write
        buttons are no longer held disabled; the worker's gate still refuses an unsupported camera."""
        self.set_build_line(tr('尚未检测'), unsupported=False)

    def set_build_line(self, text, *, unsupported):
        """The build line's text, styled as a warning for an unsupported build (apply_write_gate then keeps
        the write buttons disabled)."""
        self.build_unsupported = unsupported
        self.build_label.setText(text)
        self.build_label.setProperty('warning', unsupported)
        theme.repolish(self.build_label)

    def apply_write_gate(self):
        """Keep every button that writes to the camera disabled while its build is unsupported. Called
        after anything that enables buttons. The worker's own gate refuses these writes as well."""
        if self.build_unsupported:
            for button in self.write_buttons:
                button.setEnabled(False)

    @staticmethod
    def firmware_refusal(state):
        """The plain text, in the interface language, of the UnsupportedFirmware refusal that stopped the
        saved job `state` (NEEDS_REVIEW with the gate's message as its error); '' for any other state.
        The gate refuses before it writes, so a job so stopped has nothing to continue."""
        error = state.get('error')
        if state.get('phase') != 'NEEDS_REVIEW' or not isinstance(error, str):
            return ''
        # looktool is imported only for a stopped job: a window with no saved job opens without it.
        from looktool.buildprofile import unsupported_digests
        from looktool.devicesession import UNIDENTIFIED
        if error != UNIDENTIFIED and unsupported_digests(error) is None:
            return ''
        return Window.error_text({'error': error})

    @staticmethod
    def error_text(status):
        """The worker's error in the interface language: a recipe job's with its outcome hint, any
        other through the engine catalogue (a firmware-build refusal names the digests or builds it saw)."""
        from .actions.catalog import RECIPE_ACTIONS
        if status.get('action') in RECIPE_ACTIONS:
            from .actions.recipe import localized
            return localized(status['error'],tr)
        return display(status['error'])

    def process_error(self, error):
        if self.process and error == QtCore.QProcess.FailedToStart:
            self.log.appendPlainText(self.process.errorString())
            self.finished(-1, None)

    def open_job(self):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self.current_job or data_root())))

    def export_logs(self):
        if not self.current_job:
            return
        path = W.QFileDialog.getSaveFileName(self, tr('导出诊断包'), 'a7c2-diagnostics.zip', 'ZIP (*.zip)')[0]
        if path:
            try:
                jobs.export_support(self.current_job, path)
            except Exception as exc:
                shell.warn(self, tr('导出失败'), exc)

    def cancel_offline(self):
        if self.process and not self.camera_operation:
            self.process.terminate()

    def closeEvent(self, event):
        if self.process:
            W.QMessageBox.information(self, tr('任务仍在运行'), tr('请等待当前任务结束后关闭。相机写入期间不要结束程序或拔线。'))
            event.ignore()
        else:
            event.accept()


def configure_application(app):
    """The running app's name, version and icon: the Dock and every window show APP_ICON."""
    app.setApplicationName('A7C2Tools')
    app.setApplicationVersion(VERSION)
    app.setOrganizationName('QAQLeonard')
    app.setWindowIcon(QtGui.QIcon(str(APP_ICON)))


def main():
    app = W.QApplication.instance() or W.QApplication(sys.argv)
    if '--smoke-test' in sys.argv and sys.platform == 'win32':
        # Qt's headless test platform does not enumerate Windows system fonts.
        import os
        font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
        if font.is_file():
            QtGui.QFontDatabase.addApplicationFont(str(font))
    configure_application(app)
    window = Window()
    window.show()
    if '--smoke-test' in sys.argv:
        data_root().mkdir(parents=True, exist_ok=True)
        for index in range(window.pages.count()):
            window.nav.setCurrentRow(index)
            app.processEvents()
            if not window.grab().save(str(data_root() / ('desktop-page-' + str(index + 1) + '.png'))):
                raise OSError('Could not save desktop smoke screenshot')
        window.nav.setCurrentRow(0)
        QtCore.QTimer.singleShot(800, app.quit)
    else:
        if window.connection_notice_due():
            QtCore.QTimer.singleShot(0,window.show_connection_notice)
    return app.exec()
