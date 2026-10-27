"""Incremental custom-slot editor. This module never opens a camera."""
from .i18n import tr
from pathlib import Path
from PySide6 import QtCore, QtWidgets as W
from .lookviews import fit_help, fit_text

FIT_CHARS = 120  # two lines of the fit label at the window's minimum width; the tooltip has the rest


def label(text, *, muted=False):
    result=W.QLabel(text)
    result.setProperty('muted',muted)
    return result




class Operation(W.QFrame):
    changed=QtCore.Signal()
    remove_requested=QtCore.Signal(object)
    preview_requested=QtCore.Signal(str)

    def __init__(self,slot):
        super().__init__()
        self.setProperty('card',True)
        self.file_path=''
        box=W.QVBoxLayout(self);box.setContentsMargins(17,15,17,15);box.setSpacing(12)
        top=W.QHBoxLayout();box.addLayout(top)
        top.addWidget(label(tr('目标槽位'),muted=True))
        self.slot=W.QComboBox()
        for number in range(1,7):self.slot.addItem(tr('自订 %d') % number,number)
        self.slot.setCurrentIndex(slot-1);self.slot.setFixedWidth(130)
        top.addWidget(self.slot);top.addSpacing(18)
        top.addWidget(label(tr('本次操作'),muted=True))
        self.action=W.QComboBox();self.action.addItems([tr('恢复 ST 默认'),tr('写入 A7Look')])
        self.action.setFixedWidth(160);top.addWidget(self.action);top.addStretch()
        remove=W.QPushButton(tr('移除这项'));remove.setProperty('quiet',True)
        remove.setToolTip(tr('仅移除此操作项，该槽保持原样'))
        remove.clicked.connect(lambda:self.remove_requested.emit(self));top.addWidget(remove)
        self.details=W.QStackedWidget();self.details.setObjectName('operationStack');box.addWidget(self.details)
        restore=W.QWidget();restore.setObjectName('operationDetails');restore_box=W.QHBoxLayout(restore);restore_box.setContentsMargins(0,0,0,0)
        note=label(tr('此槽恢复为 ST 默认；不会找回导入前的旧配方。'),muted=True)
        restore_box.addWidget(note);restore_box.addStretch();self.details.addWidget(restore)
        write=W.QWidget();write.setObjectName('operationDetails');grid=W.QGridLayout(write);grid.setContentsMargins(0,0,0,0);grid.setHorizontalSpacing(12);grid.setVerticalSpacing(6)
        grid.addWidget(label(tr('A7Look 文件'),muted=True),0,0)
        grid.addWidget(label(tr('机内显示名称'),muted=True),0,2)
        self.file=W.QLineEdit();self.file.setReadOnly(True);self.file.setPlaceholderText(tr('请选择 .a7look 文件'))
        self.browse=W.QPushButton(tr('选择文件…'));self.browse.clicked.connect(self.choose_file)
        self.preview=W.QPushButton(tr('预览…'));self.preview.setEnabled(False)
        self.preview.clicked.connect(lambda:self.preview_requested.emit(self.file_path))
        self.name=W.QLineEdit();self.name.setPlaceholderText(tr('留空沿用文件内名称'))
        files=W.QHBoxLayout();files.setSpacing(6);files.addWidget(self.browse);files.addWidget(self.preview)
        grid.addWidget(self.file,1,0);grid.addLayout(files,1,1);grid.addWidget(self.name,1,2)
        self.fit=label('',muted=True);self.fit.setWordWrap(True);self.fit.hide()
        grid.addWidget(self.fit,2,0,1,3)
        grid.setColumnStretch(0,3);grid.setColumnStretch(2,2);self.details.addWidget(write)
        self.action.currentIndexChanged.connect(self.update_mode)
        self.slot.currentIndexChanged.connect(self.changed)
        self.name.textChanged.connect(self.changed)
        self.update_mode()

    def update_mode(self):
        self.details.setCurrentIndex(self.action.currentIndex())
        self.details.setFixedHeight(36 if self.action.currentIndex()==0 else 100)
        self.setFixedHeight(115 if self.action.currentIndex()==0 else 179)
        self.changed.emit()

    def choose_file(self):
        from .profilelibrary import location
        path=W.QFileDialog.getOpenFileName(self,tr('选择 A7Look 文件'),self.file_path or str(location()),'A7Look (*.a7look)')[0]
        if path:self.set_file(path)

    def set_file(self,path):
        from .looklibrary import file_fit,CONCERNS
        fit=file_fit(path);text=fit_text(fit)  # never raises, so the whole row updates together
        self.file_path=str(path);self.file.setText(Path(path).name);self.file.setToolTip(str(path))
        self.fit.setText(text if len(text)<=FIT_CHARS else text[:FIT_CHARS-1]+'…')
        self.fit.setToolTip(text+'\n\n'+fit_help());self.fit.setProperty('warning',fit['rating'] in CONCERNS)
        self.fit.style().unpolish(self.fit);self.fit.style().polish(self.fit);self.fit.show()
        self.preview.setEnabled(fit['preview']);self.changed.emit()

    def value(self):
        value=dict(slot=self.slot.currentData(),action='restore' if self.action.currentIndex()==0 else 'write')
        if value['action']=='write':value.update(path=self.file_path,name=self.name.text().strip())
        return value


class LookEditor(W.QWidget):
    changed=QtCore.Signal()
    preview_requested=QtCore.Signal(str)
    library_requested=QtCore.Signal()

    def __init__(self):
        super().__init__();self.rows=[];self._loading=False
        box=W.QVBoxLayout(self);box.setContentsMargins(0,0,0,0);box.setSpacing(12)
        top=W.QHBoxLayout();self.add=W.QPushButton(tr('+ 添加操作项'))
        self.add.clicked.connect(lambda:self.add_row());top.addWidget(self.add)
        self.library=W.QPushButton(tr('从胶片外观库添加…'))
        self.library.clicked.connect(self.library_requested);top.addWidget(self.library)
        top.addWidget(label(tr('新增项默认“恢复 ST 默认”，可切换为写入。'),muted=True));top.addStretch();box.addLayout(top)
        self.row_box=W.QVBoxLayout();self.row_box.setSpacing(12);box.addLayout(self.row_box)
        self.empty=W.QFrame();self.empty.setProperty('card',True)
        empty_box=W.QVBoxLayout(self.empty);empty_box.setContentsMargins(20,25,20,25)
        empty_title=label(tr('尚未添加操作项'));empty_title.setAlignment(QtCore.Qt.AlignCenter)
        empty_title.setProperty('role','title3');empty_box.addWidget(empty_title)
        note=label(tr('点击“添加操作项”，选择目标槽位和操作。当前六个槽位均保持原样。'),muted=True)
        note.setWordWrap(True);note.setAlignment(QtCore.Qt.AlignCenter);empty_box.addWidget(note)
        self.row_box.addWidget(self.empty)
        summary=W.QFrame();summary.setProperty('card',True)
        summary_box=W.QVBoxLayout(summary);summary_box.setContentsMargins(15,12,15,12)
        self.summary=label('');self.summary.setProperty('role','headline');summary_box.addWidget(self.summary)
        self.preserved=label('',muted=True);self.preserved.setWordWrap(True);summary_box.addWidget(self.preserved)
        self.validation=label('');self.validation.setProperty('warning',True);self.validation.setWordWrap(True);summary_box.addWidget(self.validation)
        box.addWidget(summary);self.update_summary()

    def add_row(self,slot=None):
        occupied={r.slot.currentData() for r in self.rows};free=[n for n in range(1,7) if n not in occupied]
        if not free:return None
        row=Operation(slot if slot is not None else free[0]);self.rows.append(row)
        row.changed.connect(self.update_summary);row.remove_requested.connect(self.remove_row)
        row.preview_requested.connect(self.preview_requested)
        self.row_box.addWidget(row);self.update_summary();return row

    def remove_row(self,row):
        self.rows.remove(row);self.row_box.removeWidget(row);row.setParent(None);row.deleteLater();self.update_summary()

    def values(self):return [row.value() for row in self.rows]

    def set_operations(self,operations):
        self._loading=True
        try:
            for row in list(self.rows):self.remove_row(row)
            for value in operations:
                row=self.add_row(value['slot'])
                if value.get('action','write')=='write':
                    row.action.setCurrentIndex(1);row.set_file(value.get('path') or value.get('file',''))
                    row.name.setText(value.get('name') or '')
        finally:self._loading=False
        self.update_summary()

    def errors(self):
        values=self.values();slots=[r['slot'] for r in values];errors=[]
        if len(slots)!=len(set(slots)):errors.append(tr('同一槽位只能添加一个操作。'))
        missing=[str(r['slot']) for r in values if r['action']=='write' and not r['path']]
        if missing:errors.append(tr('请为自订 ')+tr('、').join(missing)+tr(' 选择 A7Look 文件。'))
        return errors

    def update_summary(self):
        values=self.values();used={r['slot'] for r in values};writes=sum(r['action']=='write' for r in values)
        self.empty.setVisible(not values);self.add.setEnabled(len(values)<6)
        for row in self.rows:
            for i in range(6):row.slot.model().item(i).setEnabled(i+1 not in used or i+1==row.slot.currentData())
        self.summary.setText(tr('本次更改 %d 个槽位：%d 项写入 · %d 项恢复')%(len(values),writes,len(values)-writes))
        kept=[str(n) for n in range(1,7) if n not in used]
        self.preserved.setText(tr('保持原样：')+(tr('自订 ')+tr('、').join(kept) if kept else tr('无（六个槽位均在本次清单中）')))
        self.validation.setText(' '.join(self.errors()));self.validation.setVisible(bool(self.errors()))
        if not self._loading:self.changed.emit()
