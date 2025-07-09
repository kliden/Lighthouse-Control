import platform, asyncio, sys, pathlib, bisect

from PyQt6.QtGui import *
from PyQt6.QtCore import *
from PyQt6.QtWidgets import *
import qasync

import lighthouse


class QtLighthouse(QObject):
    powerStateChanged = pyqtSignal(bool)

    def __init__(self, lh: lighthouse.Lighthouse):
        super().__init__()
        self._lh = lh
    
    @property
    def address(self):
        return self._lh.address
    
    @property
    def is_on(self):
        return self._lh.is_on

    async def init(self):
        is_on = await self._lh.read()
        self.powerStateChanged.emit(is_on)

    async def write(self, is_on: bool):
        await self._lh.write(is_on)
        self.powerStateChanged.emit(is_on)
    
    def __hash__(self):
        return hash(self.address)
    
    def __eq__(self, other):
        return (
            isinstance(other, QtLighthouse) and 
            self.address == other.address
        )


class Scanner(QObject):
    started = pyqtSignal()
    stopped = pyqtSignal()
    lighthouseDetected = pyqtSignal(QtLighthouse)

    def __init__(self):
        super().__init__()
        self._task = None

    async def scan(self):
        async def task_func():
            self.started.emit()
            try:
                async for lh in lighthouse.Lighthouse.iter():
                    light = QtLighthouse(lh)
                    self.lighthouseDetected.emit(light)
            except TimeoutError:
                pass
            finally:
                self.stopped.emit()
        self._task = asyncio.create_task(task_func())
    
    @qasync.asyncSlot()
    async def scanSlot(self):
        await self.scan()

    def cancel(self):
        if self._task:
            self._task.cancel()


class LighthouseSetModel(QObject):
    lighthouseAdded = pyqtSignal(QtLighthouse)

    def __init__(self, lighthouses=set()):
        super().__init__()
        self._lighthouses = lighthouses

    @property
    def lighthouses(self):
        return set(self._lighthouses)

    def __len__(self):
        return len(self._lighthouses)

    def add(self, lh: QtLighthouse):
        if lh not in self._lighthouses:
            self._lighthouses.add(lh)
            self.lighthouseAdded.emit(lh)


class WorkButton(QPushButton):
    finished = pyqtSignal()

    def __init__(self, button_text: str=""):
        super().__init__(button_text)
        self.pressed.connect(self.doWork)

    @qasync.asyncSlot()
    async def doWork(self):
        await self._work()
        self.finished.emit()

    async def _work(self):
        raise NotImplementedError()


class AllPowerButton(WorkButton):
    def __init__(self, lh_model: LighthouseSetModel, is_on: bool):
        super().__init__("All On" if is_on else "All Off")
        self._lighthouse_model = lh_model
        self._is_on = is_on  

    async def _work(self):
        lighthouses = set(self._lighthouse_model._lighthouses)
        async with asyncio.TaskGroup() as tg:
            for lh in lighthouses:
                tg.create_task(lh.write(self._is_on))


class TogglePowerButton(WorkButton):
    def __init__(self, lh: QtLighthouse):
        super().__init__()
        self.setFixedWidth(100)
        self._update_text(lh.is_on)
        lh.powerStateChanged.connect(self._update_text)
        self._lh = lh
    
    def _update_text(self, is_on: bool):
        self.setText("Turn Off" if is_on else "Turn On")
    
    async def _work(self):
        await self._lh.write(not self._lh.is_on)


class LighthouseView(QFrame):
    ON_COLOR = "SpringGreen"
    OFF_COLOR = "DodgerBlue"
    UNKNOWN_STATE_COLOR = "grey"

    SELECTED_COLOR = "#ffbf00"

    selectStateChanged = pyqtSignal(bool)

    def __init__(self, lh: QtLighthouse, toggle_power_button: TogglePowerButton):
        super().__init__()
        self._is_selected = False
        self._lh = lh

        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Plain)
        self.setLineWidth(2)
        self.setStyleSheet("QFrame { background-color: rgb(15, 15, 15); }")

        view_layout = QHBoxLayout(self)
        self._power_state_label = QLabel()
        view_layout.addWidget(self._power_state_label)
        self._power_state_label.setStyleSheet(self._update_power_indicator(None))

        self._address_label = QLabel(lh.address)
        view_layout.addWidget(self._address_label, alignment=Qt.AlignmentFlag.AlignLeft)

        def on_power_state_changed(is_on: bool):
            self._power_state_label.setStyleSheet(self._update_power_indicator(is_on))
        lh.powerStateChanged.connect(on_power_state_changed)

        view_layout.addWidget(toggle_power_button, alignment=Qt.AlignmentFlag.AlignRight)

    @property
    def address(self):
        return self._lh.address

    def mousePressEvent(self, e: QMouseEvent):
        self.select(not self._is_selected)
        return super().mousePressEvent(e)

    def _update_power_indicator(self, power_state: bool):
        if power_state is None:
            color = self.UNKNOWN_STATE_COLOR
        elif power_state:
            color = self.ON_COLOR
        else:
            color = self.OFF_COLOR
        return self._power_indicator_sheet(color)
    
    def _power_indicator_sheet(self, color: str):
        return f"""
        background-color: {color};
        border-radius: 6px;
        min-width: 12px;
        max-width: 12px;
        min-height: 12px;
        max-height: 12px;
        """

    def select(self, is_selected: bool=True):
        if self._is_selected == is_selected:
            return

        self._is_selected = is_selected
        self._address_label.setStyleSheet(f"color: {self.SELECTED_COLOR}" if is_selected else "")
        self.selectStateChanged.emit(self._is_selected)
    

class LighthouseListView(QGroupBox):
    def __init__(self):
        super().__init__("Detected Lighthouses")

        self.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setFixedHeight(400)

        layout = QVBoxLayout(self)

        list_scroll_widget = QScrollArea()
        list_scroll_widget.setStyleSheet("QScrollArea { background: transparent; border-radius: 0px; }")
        list_scroll_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(list_scroll_widget)
        list_widget = QWidget()
        list_widget.setFixedWidth(400)
        list_scroll_widget.setWidget(list_widget)
        self._list_layout = QVBoxLayout(list_widget)
        self._list_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        self._list_layout.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignTop)
        self._list_layout.setContentsMargins(0, 0, 0, 0)

        self._addresses = []

    def addLighthouseView(self, lh_view):
        index = bisect.bisect(self._addresses, lh_view.address)
        self._addresses.insert(index, lh_view.address)
        self._list_layout.insertWidget(index, lh_view)


class Window(QMainWindow):
    writingPowerState = pyqtSignal()
    finishedWritingPowerState = pyqtSignal()

    def __init__(self, scanner: Scanner):
        super().__init__()

        self._scanner = scanner
        self._is_setting_power_state = False
        self._power_finish_event = asyncio.Event()

        def on_writing_power_state(is_writing: bool):
            self._is_setting_power_state = is_writing
        self.writingPowerState.connect(lambda: on_writing_power_state(True))
        self.finishedWritingPowerState.connect(lambda: on_writing_power_state(False))

        self.writingPowerState.connect(self._power_finish_event.clear)
        self.finishedWritingPowerState.connect(self._power_finish_event.set)

        self.setWindowTitle("Lighthouse Control")

        self._script_folder = lighthouse.default_script_folder()
        self._selected_addresses = []
        self._script_no_console_window = platform.system() == 'Windows' 

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        upper_widget = QWidget()
        main_layout.addWidget(upper_widget)
        upper_layout = QVBoxLayout(upper_widget)
        self._lighthouse_list_view = LighthouseListView()
        upper_layout.addWidget(self._lighthouse_list_view)

        self._lighthouse_model = LighthouseSetModel()
        self._lighthouse_model.lighthouseAdded.connect(self._on_lighthouse_added)
        scanner.lighthouseDetected.connect(self._lighthouse_model.add)

        control_button_holder = QWidget()
        main_layout.addWidget(control_button_holder)
        control_button_layout = QHBoxLayout(control_button_holder)

        self._scan_button = QPushButton("Scan")
        self._scan_button.setFixedWidth(100)
        control_button_layout.addWidget(self._scan_button)
        self._scan_button.pressed.connect(scanner.scanSlot)
        scanner.started.connect(lambda: self._scan_button.setEnabled(False))
        scanner.stopped.connect(self._on_scanner_stopped)

        self._on_button = AllPowerButton(self._lighthouse_model, is_on=True)
        self._off_button = AllPowerButton(self._lighthouse_model, is_on=False)

        self._global_power_buttons = [self._on_button, self._off_button]
        self._power_buttons = list(self._global_power_buttons)

        def set_power_buttons_enabled(is_enabled: bool):
            for b in self._power_buttons:
                b.setEnabled(is_enabled)
            self._scan_button.setEnabled(is_enabled)
        for b in self._global_power_buttons:
            b.pressed.connect(lambda: set_power_buttons_enabled(False))
            b.finished.connect(lambda: set_power_buttons_enabled(True))

        control_button_layout.addWidget(self._on_button)
        control_button_layout.addWidget(self._off_button)

        script_widget = QGroupBox("Quick Launcher Creation")
        main_layout.addWidget(script_widget)
        script_layout = QVBoxLayout(script_widget)
        script_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        folder_widget = QGroupBox("Destination Folder")
        script_layout.addWidget(folder_widget)
        folder_layout = QVBoxLayout(folder_widget)
        folder_value_button = QPushButton(str(self._script_folder))
        def folder_button_pressed():
            folder = QFileDialog.getExistingDirectory(folder_widget, "Select Script Destination Folder")
            folder_value_button.setText(folder)
            self._script_folder = pathlib.Path(folder)
        folder_value_button.pressed.connect(folder_button_pressed)
        folder_layout.addWidget(folder_value_button)
    
        if platform.system() == 'Windows':
            no_console_window_checkbox = QCheckBox("No Console Window")
            no_console_window_checkbox.setChecked(self._script_no_console_window)
            def check_changed():
                self._script_no_console_window = no_console_window_checkbox.isChecked()
            no_console_window_checkbox.checkStateChanged.connect(check_changed)
            script_layout.addWidget(no_console_window_checkbox)

        self._create_selected_button = QPushButton("Create For Selected")
        self._create_selected_button.setToolTip("Must have at least one lighthouse selected.")
        self._create_selected_button.setEnabled(False)
        def selected_button_pressed():
            lighthouse.create_scripts(self._script_folder, self._selected_addresses, self._script_no_console_window)
        self._create_selected_button.pressed.connect(selected_button_pressed)
        script_layout.addWidget(self._create_selected_button)

        create_all_button = QPushButton("Create For All")
        script_layout.addWidget(create_all_button)
        def set_global_buttons_enabled():
            all_addresses = [lh.address for lh in self._lighthouse_model._lighthouses]
            lighthouse.create_scripts(self._script_folder, all_addresses, self._script_no_console_window)
        create_all_button.pressed.connect(set_global_buttons_enabled)

        main_layout.addStretch(1)
        
        self.adjustSize()
        self.setFixedSize(self.size())

    @qasync.asyncSlot(QtLighthouse)
    async def _on_lighthouse_added(self, lh: QtLighthouse):
        toggle_power_button = TogglePowerButton(lh)
        self._init_power_button(toggle_power_button)
        self._power_buttons.append(toggle_power_button)

        view = LighthouseView(lh, toggle_power_button)
        self._lighthouse_list_view.addLighthouseView(view)
        def on_select_state_changed(is_selected: bool):
            if is_selected:
                if lh.address not in self._selected_addresses:
                    self._selected_addresses.append(lh.address)
            else:
                self._selected_addresses.remove(lh.address)
            self._create_selected_button.setEnabled(len(self._selected_addresses) > 0)
        view.selectStateChanged.connect(on_select_state_changed) 

        await lh.init()
    
    @qasync.asyncSlot()
    async def _on_scanner_stopped(self):
        if self._is_setting_power_state:
            await self._power_finish_event.wait()
        self._scan_button.setEnabled(True)
    
    def _init_power_button(self, button: WorkButton):
        button.pressed.connect(self.writingPowerState.emit)
        button.finished.connect(self.finishedWritingPowerState.emit)

        def set_buttons_enabled(is_enabled: bool):
            for b in self._global_power_buttons:
                b.setEnabled(is_enabled)
            button.setEnabled(is_enabled)
            self._scan_button.setEnabled(is_enabled)
        button.pressed.connect(lambda: set_buttons_enabled(False))
        button.finished.connect(lambda: set_buttons_enabled(True))

        self._power_buttons.append(button)


async def _main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Arial", 16))
    app_close_event = asyncio.Event()
    app.aboutToQuit.connect(app_close_event.set)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    scanner = Scanner()
    w = Window(scanner)
    w.show()
    with loop:
        loop.create_task(scanner.scan())
        app.aboutToQuit.connect(scanner.cancel)
        loop.run_until_complete(app_close_event.wait())


def main():
    asyncio.run(_main())