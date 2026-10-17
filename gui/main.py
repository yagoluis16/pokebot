# pokebot/gui/main.py
"""Main PySide6 GUI application."""

from __future__ import annotations
import sys
import logging
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QObject, QThread
from PySide6.QtGui import QFont, QColor, QPalette, QIcon, QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QGroupBox, QFormLayout,
    QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox, QComboBox,
    QTextEdit, QListWidget, QListWidgetItem, QTableWidget,
    QTableWidgetItem, QHeaderView, QSplitter, QScrollArea,
    QFileDialog, QMessageBox, QStatusBar, QProgressBar,
    QTreeWidget, QTreeWidgetItem, QMenu, QSystemTrayIcon,
)

from context import get_context, BotContext
from engine import create_engine
from navigator import Navigator, Waypoint
from gui.pokemon_selector import PokemonHealerSelector

log = logging.getLogger("pokebot.gui")


# ─── Theme ────────────────────────────────────────────────────────────────
DARK_PALETTE = {
    "bg": "#1a1a2e",
    "bg_secondary": "#16213e",
    "bg_tertiary": "#0f0f23",
    "fg": "#e0e0e0",
    "fg_muted": "#888888",
    "accent": "#00d4ff",
    "accent_hover": "#00eaff",
    "green": "#00ff88",
    "red": "#ff4444",
    "yellow": "#ffcc00",
    "border": "#2a2a4a",
    "input_bg": "#1e1e3a",
    "input_fg": "#ffffff",
}

def apply_dark_theme(app: QApplication):
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(DARK_PALETTE["bg"]))
    palette.setColor(QPalette.WindowText, QColor(DARK_PALETTE["fg"]))
    palette.setColor(QPalette.Base, QColor(DARK_PALETTE["input_bg"]))
    palette.setColor(QPalette.AlternateBase, QColor(DARK_PALETTE["bg_secondary"]))
    palette.setColor(QPalette.ToolTipBase, QColor(DARK_PALETTE["bg_tertiary"]))
    palette.setColor(QPalette.ToolTipText, QColor(DARK_PALETTE["fg"]))
    palette.setColor(QPalette.Text, QColor(DARK_PALETTE["input_fg"]))
    palette.setColor(QPalette.Button, QColor(DARK_PALETTE["bg_secondary"]))
    palette.setColor(QPalette.ButtonText, QColor(DARK_PALETTE["fg"]))
    palette.setColor(QPalette.BrightText, QColor(DARK_PALETTE["red"]))
    palette.setColor(QPalette.Highlight, QColor(DARK_PALETTE["accent"]))
    palette.setColor(QPalette.HighlightedText, QColor(DARK_PALETTE["bg"]))
    app.setPalette(palette)

    app.setStyleSheet(f"""
        QMainWindow, QWidget {{ background-color: {DARK_PALETTE['bg']}; color: {DARK_PALETTE['fg']}; }}
        QGroupBox {{ border: 1px solid {DARK_PALETTE['border']}; border-radius: 4px; margin-top: 8px; padding-top: 8px; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; color: {DARK_PALETTE['accent']}; }}
        QPushButton {{ background-color: {DARK_PALETTE['bg_secondary']}; border: 1px solid {DARK_PALETTE['border']}; border-radius: 4px; padding: 6px 12px; color: {DARK_PALETTE['fg']}; }}
        QPushButton:hover {{ background-color: {DARK_PALETTE['accent']}; color: {DARK_PALETTE['bg']}; border-color: {DARK_PALETTE['accent']}; }}
        QPushButton:pressed {{ background-color: {DARK_PALETTE['accent_hover']}; }}
        QPushButton:disabled {{ background-color: {DARK_PALETTE['bg_tertiary']}; color: {DARK_PALETTE['fg_muted']}; border-color: {DARK_PALETTE['border']}; }}
        QPushButton#startBtn {{ background-color: {DARK_PALETTE['green']}; color: {DARK_PALETTE['bg']}; font-weight: bold; }}
        QPushButton#startBtn:hover {{ background-color: #00ff99; }}
        QPushButton#stopBtn {{ background-color: {DARK_PALETTE['red']}; color: white; font-weight: bold; }}
        QPushButton#stopBtn:hover {{ background-color: #ff6666; }}
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background-color: {DARK_PALETTE['input_bg']}; border: 1px solid {DARK_PALETTE['border']}; border-radius: 3px; padding: 4px; color: {DARK_PALETTE['input_fg']}; }}
        QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {DARK_PALETTE['accent']}; }}
        QTabWidget::pane {{ border: 1px solid {DARK_PALETTE['border']}; background: {DARK_PALETTE['bg']}; }}
        QTabBar::tab {{ background: {DARK_PALETTE['bg_secondary']}; border: 1px solid {DARK_PALETTE['border']}; padding: 8px 16px; margin-right: 2px; }}
        QTabBar::tab:selected {{ background: {DARK_PALETTE['accent']}; color: {DARK_PALETTE['bg']}; }}
        QTabBar::tab:hover {{ background: {DARK_PALETTE['bg_tertiary']}; }}
        QTableWidget {{ background-color: {DARK_PALETTE['input_bg']}; border: 1px solid {DARK_PALETTE['border']}; gridline-color: {DARK_PALETTE['border']}; }}
        QHeaderView::section {{ background-color: {DARK_PALETTE['bg_secondary']}; color: {DARK_PALETTE['accent']}; padding: 4px; border: 1px solid {DARK_PALETTE['border']}; }}
        QListWidget {{ background-color: {DARK_PALETTE['input_bg']}; border: 1px solid {DARK_PALETTE['border']}; }}
        QTextEdit {{ background-color: {DARK_PALETTE['input_bg']}; border: 1px solid {DARK_PALETTE['border']}; color: {DARK_PALETTE['fg']}; }}
        QScrollBar:vertical {{ background: {DARK_PALETTE['bg']}; width: 10px; }}
        QScrollBar::handle:vertical {{ background: {DARK_PALETTE['border']}; border-radius: 5px; min-height: 30px; }}
        QProgressBar {{ border: 1px solid {DARK_PALETTE['border']}; border-radius: 3px; text-align: center; background: {DARK_PALETTE['input_bg']}; }}
        QProgressBar::chunk {{ background-color: {DARK_PALETTE['accent']}; border-radius: 2px; }}
        QStatusBar {{ background: {DARK_PALETTE['bg_tertiary']}; color: {DARK_PALETTE['fg_muted']}; }}
        QTreeWidget {{ background-color: {DARK_PALETTE['input_bg']}; border: 1px solid {DARK_PALETTE['border']}; }}
        QCheckBox::indicator {{ width: 16px; height: 16px; }}
    """)


# ─── Worker Thread ────────────────────────────────────────────────────────

class BotWorker(QObject):
    """Runs the engine in a background thread."""
    status_update = Signal(dict)
    log_message = Signal(str, str)  # level, message
    finished = Signal()

    def __init__(self, engine, resolver):
        super().__init__()
        self.engine = engine
        self.resolver = resolver
        self._running = False

    def run(self):
        self._running = True
        self.engine.start()
        self.log_message.emit("INFO", "Bot started")

        # Periodic status updates
        timer = QTimer()
        timer.timeout.connect(self._emit_status)
        timer.start(1000)  # 1 second

        # Keep thread alive
        while self._running and not self.engine.ctx.is_stopped():
            self.msleep(100)

        timer.stop()
        self.engine.stop()
        self.log_message.emit("INFO", "Bot stopped")
        self.finished.emit()

    def stop(self):
        self._running = False
        self.engine.stop()

    def _emit_status(self):
        if self.engine:
            self.status_update.emit(self.engine.get_status())

    def msleep(self, ms):
        QThread.msleep(ms)


# ─── Main Window ──────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self, config_path: str = None):
        super().__init__()
        self.config_path = config_path
        self.ctx = get_context(config_path)
        self.engine = None
        self.worker = None
        self.worker_thread = None
        self.resolver = None

        self.setWindowTitle("PKA Bot — PokeAlliance Assistant")
        self.setMinimumSize(1200, 800)
        self._setup_ui()
        self._setup_tray()
        self._load_config_to_ui()

        # Status timer
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._update_status_bar)
        self.status_timer.start(500)

    def _setup_ui(self):
        # Central widget with tabs
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # Create tabs
        self.tab_dashboard = self._create_dashboard_tab()
        self.tab_cavebot = self._create_cavebot_tab()
        self.tab_targeting = self._create_targeting_tab()
        self.tab_combat = self._create_combat_tab()
        self.tab_loot = self._create_loot_tab()
        self.tab_settings = self._create_settings_tab()
        self.tab_debug = self._create_debug_tab()

        self.tabs.addTab(self.tab_dashboard, "📊 Dashboard")
        self.tabs.addTab(self.tab_cavebot, "🗺️ Cavebot")
        self.tabs.addTab(self.tab_targeting, "🎯 Targeting")
        self.tabs.addTab(self.tab_combat, "⚔️ Combat")
        self.tabs.addTab(self.tab_loot, "💰 Loot")
        self.tabs.addTab(self.tab_settings, "⚙️ Settings")
        self.tabs.addTab(self.tab_debug, "🔧 Debug")

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.lbl_connection = QLabel("● Disconnected")
        self.lbl_connection.setStyleSheet(f"color: {DARK_PALETTE['red']};")
        self.lbl_uptime = QLabel("Uptime: 00:00:00")
        self.status_bar.addPermanentWidget(self.lbl_connection)
        self.status_bar.addPermanentWidget(self.lbl_uptime)

        # Control buttons at bottom
        control_bar = QHBoxLayout()
        self.btn_start = QPushButton("▶ START")
        self.btn_start.setObjectName("startBtn")
        self.btn_start.setFixedHeight(40)
        self.btn_start.clicked.connect(self._on_start)
        self.btn_stop = QPushButton("■ STOP")
        self.btn_stop.setObjectName("stopBtn")
        self.btn_stop.setFixedHeight(40)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_stop.setEnabled(False)
        self.btn_pause = QPushButton("⏸ PAUSE")
        self.btn_pause.setFixedHeight(40)
        self.btn_pause.clicked.connect(self._on_pause)
        control_bar.addStretch()
        control_bar.addWidget(self.btn_start)
        control_bar.addWidget(self.btn_pause)
        control_bar.addWidget(self.btn_stop)
        control_bar.addStretch()

        # Add control bar to status bar area via a widget
        control_widget = QWidget()
        control_widget.setLayout(control_bar)
        self.status_bar.addPermanentWidget(control_widget)

    def _create_dashboard_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # Status group
        status_group = QGroupBox("Bot Status")
        s_layout = QFormLayout(status_group)
        self.lbl_dash_status = QLabel("STOPPED")
        self.lbl_dash_status.setStyleSheet(f"color: {DARK_PALETTE['red']}; font-size: 18px; font-weight: bold;")
        s_layout.addRow("State:", self.lbl_dash_status)
        self.lbl_dash_uptime = QLabel("00:00:00")
        s_layout.addRow("Uptime:", self.lbl_dash_uptime)
        self.lbl_dash_modules = QLabel("0/6 active")
        s_layout.addRow("Modules:", self.lbl_dash_modules)
        layout.addWidget(status_group)

        # Stats group
        stats_group = QGroupBox("Session Statistics")
        st_layout = QFormLayout(stats_group)
        self.stat_labels = {}
        for key in ["heals", "mana_heals", "food_eaten", "creatures_killed", "items_looted", "waypoints_reached", "stuck_recoveries", "deaths", "disconnects"]:
            label = QLabel("0")
            label.setStyleSheet(f"color: {DARK_PALETTE['accent']}; font-weight: bold;")
            self.stat_labels[key] = label
            st_layout.addRow(key.replace("_", " ").title() + ":", label)
        layout.addWidget(stats_group)

        # Player info group
        player_group = QGroupBox("Player Info (from memory)")
        p_layout = QFormLayout(player_group)
        self.lbl_player_name = QLabel("—")
        self.lbl_player_hp = QLabel("—")
        self.lbl_player_mp = QLabel("—")
        self.lbl_player_pos = QLabel("—")
        self.lbl_player_dir = QLabel("—")
        p_layout.addRow("Name:", self.lbl_player_name)
        p_layout.addRow("HP:", self.lbl_player_hp)
        p_layout.addRow("MP:", self.lbl_player_mp)
        p_layout.addRow("Position:", self.lbl_player_pos)
        p_layout.addRow("Direction:", self.lbl_player_dir)
        layout.addWidget(player_group)

        # Recent events log
        log_group = QGroupBox("Recent Events")
        lg_layout = QVBoxLayout(log_group)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(150)
        self.log_view.setFont(QFont("Consolas", 9))
        lg_layout.addWidget(self.log_view)
        layout.addWidget(log_group)

        layout.addStretch()
        return w

    def _create_cavebot_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # Controls
        ctrl_group = QGroupBox("Waypoint Controls")
        c_layout = QHBoxLayout(ctrl_group)
        self.btn_add_wp = QPushButton("➕ Add Current Position")
        self.btn_add_wp.clicked.connect(self._add_waypoint)
        self.btn_remove_wp = QPushButton("➖ Remove Selected")
        self.btn_remove_wp.clicked.connect(self._remove_waypoint)
        self.btn_clear_wp = QPushButton("🗑️ Clear All")
        self.btn_clear_wp.clicked.connect(self._clear_waypoints)
        self.btn_load_wp = QPushButton("📂 Load")
        self.btn_load_wp.clicked.connect(self._load_waypoints)
        self.btn_save_wp = QPushButton("💾 Save")
        self.btn_save_wp.clicked.connect(self._save_waypoints)
        c_layout.addWidget(self.btn_add_wp)
        c_layout.addWidget(self.btn_remove_wp)
        c_layout.addWidget(self.btn_clear_wp)
        c_layout.addStretch()
        c_layout.addWidget(self.btn_load_wp)
        c_layout.addWidget(self.btn_save_wp)
        layout.addWidget(ctrl_group)

        # Waypoint list
        list_group = QGroupBox("Waypoints")
        lg_layout = QVBoxLayout(list_group)
        self.wp_table = QTableWidget()
        self.wp_table.setColumnCount(6)
        self.wp_table.setHorizontalHeaderLabels(["#", "Name", "X", "Y", "Z", "Action"])
        self.wp_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.wp_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.wp_table.setAlternatingRowColors(True)
        lg_layout.addWidget(self.wp_table)
        layout.addWidget(list_group)

        # Cavebot settings
        settings_group = QGroupBox("Cavebot Settings")
        sg_layout = QFormLayout(settings_group)
        self.spin_arrive_tol = QSpinBox()
        self.spin_arrive_tol.setRange(0, 10)
        self.spin_arrive_tol.setValue(self.ctx.get("cavebot", "arrive_tolerance_tiles", default=1))
        self.spin_arrive_tol.valueChanged.connect(lambda v: self.ctx.set(v, "cavebot", "arrive_tolerance_tiles"))
        sg_layout.addRow("Arrive Tolerance (tiles):", self.spin_arrive_tol)

        self.spin_key_hold = QSpinBox()
        self.spin_key_hold.setRange(20, 500)
        self.spin_key_hold.setValue(self.ctx.get("cavebot", "key_hold_ms", default=90))
        self.spin_key_hold.valueChanged.connect(lambda v: self.ctx.set(v, "cavebot", "key_hold_ms"))
        sg_layout.addRow("Key Hold (ms):", self.spin_key_hold)

        self.spin_max_leg = QSpinBox()
        self.spin_max_leg.setRange(1, 60)
        self.spin_max_leg.setValue(self.ctx.get("cavebot", "max_seconds_per_leg", default=6))
        self.spin_max_leg.valueChanged.connect(lambda v: self.ctx.set(v, "cavebot", "max_seconds_per_leg"))
        sg_layout.addRow("Max Seconds/Leg:", self.spin_max_leg)

        self.spin_stuck_retry = QSpinBox()
        self.spin_stuck_retry.setRange(0, 10)
        self.spin_stuck_retry.setValue(self.ctx.get("cavebot", "stuck_retry_count", default=3))
        self.spin_stuck_retry.valueChanged.connect(lambda v: self.ctx.set(v, "cavebot", "stuck_retry_count"))
        sg_layout.addRow("Stuck Retry Count:", self.spin_stuck_retry)

        self.spin_stuck_thresh = QSpinBox()
        self.spin_stuck_thresh.setRange(500, 10000)
        self.spin_stuck_thresh.setSingleStep(100)
        self.spin_stuck_thresh.setValue(self.ctx.get("cavebot", "stuck_threshold_ms", default=1500))
        self.spin_stuck_thresh.valueChanged.connect(lambda v: self.ctx.set(v, "cavebot", "stuck_threshold_ms"))
        sg_layout.addRow("Stuck Threshold (ms):", self.spin_stuck_thresh)

        self.spin_pause_creature = QSpinBox()
        self.spin_pause_creature.setRange(0, 10)
        self.spin_pause_creature.setValue(self.ctx.get("cavebot", "pause_on_creature_within_tiles", default=2))
        self.spin_pause_creature.valueChanged.connect(lambda v: self.ctx.set(v, "cavebot", "pause_on_creature_within_tiles"))
        sg_layout.addRow("Pause if Creature Within (tiles):", self.spin_pause_creature)

        layout.addWidget(settings_group)
        return w

    def _create_targeting_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # Targeting settings
        t_group = QGroupBox("Targeting Settings")
        t_layout = QFormLayout(t_group)

        self.spin_attack_range = QSpinBox()
        self.spin_attack_range.setRange(1, 20)
        self.spin_attack_range.setValue(self.ctx.get("auto_target", "attack_range_tiles", default=7))
        self.spin_attack_range.valueChanged.connect(lambda v: self.ctx.set(v, "auto_target", "attack_range_tiles"))
        t_layout.addRow("Attack Range (tiles):", self.spin_attack_range)

        self.spin_attack_cd = QSpinBox()
        self.spin_attack_cd.setRange(100, 5000)
        self.spin_attack_cd.setSingleStep(50)
        self.spin_attack_cd.setValue(self.ctx.get("auto_target", "attack_cooldown_ms", default=900))
        self.spin_attack_cd.valueChanged.connect(lambda v: self.ctx.set(v, "auto_target", "attack_cooldown_ms"))
        t_layout.addRow("Attack Cooldown (ms):", self.spin_attack_cd)

        self.combo_prioritize = QComboBox()
        self.combo_prioritize.addItems(["lowest_hp_percent", "nearest", "highest_level"])
        self.combo_prioritize.setCurrentText(self.ctx.get("auto_target", "prioritize", default="lowest_hp_percent"))
        self.combo_prioritize.currentTextChanged.connect(lambda v: self.ctx.set(v, "auto_target", "prioritize"))
        t_layout.addRow("Prioritize:", self.combo_prioritize)

        self.chk_ignore_players = QCheckBox()
        self.chk_ignore_players.setChecked(self.ctx.get("auto_target", "ignore_players", default=True))
        self.chk_ignore_players.toggled.connect(lambda v: self.ctx.set(v, "auto_target", "ignore_players"))
        t_layout.addRow("Ignore Players:", self.chk_ignore_players)

        self.chk_ignore_npcs = QCheckBox()
        self.chk_ignore_npcs.setChecked(self.ctx.get("auto_target", "ignore_npcs", default=True))
        self.chk_ignore_npcs.toggled.connect(lambda v: self.ctx.set(v, "auto_target", "ignore_npcs"))
        t_layout.addRow("Ignore NPCs:", self.chk_ignore_npcs)

        self.chk_ignore_dead = QCheckBox()
        self.chk_ignore_dead.setChecked(self.ctx.get("auto_target", "ignore_dead", default=True))
        self.chk_ignore_dead.toggled.connect(lambda v: self.ctx.set(v, "auto_target", "ignore_dead"))
        t_layout.addRow("Ignore Dead:", self.chk_ignore_dead)

        self.chk_chase = QCheckBox()
        self.chk_chase.setChecked(self.ctx.get("auto_target", "chase_enabled", default=False))
        self.chk_chase.toggled.connect(lambda v: self.ctx.set(v, "auto_target", "chase_enabled"))
        t_layout.addRow("Chase Enabled:", self.chk_chase)

        layout.addWidget(t_group)

        # Whitelist/Blacklist
        wl_group = QGroupBox("Name Filters")
        wl_layout = QHBoxLayout(wl_group)

        wl_left = QVBoxLayout()
        wl_left.addWidget(QLabel("Whitelist (empty = all)"))
        self.list_whitelist = QListWidget()
        for name in self.ctx.get("auto_target", "name_whitelist", default=[]):
            self.list_whitelist.addItem(name)
        wl_left.addWidget(self.list_whitelist)
        wl_btns = QHBoxLayout()
        self.btn_wl_add = QPushButton("Add")
        self.btn_wl_add.clicked.connect(lambda: self._add_to_list(self.list_whitelist, "auto_target", "name_whitelist"))
        self.btn_wl_rem = QPushButton("Remove")
        self.btn_wl_rem.clicked.connect(lambda: self._remove_from_list(self.list_whitelist, "auto_target", "name_whitelist"))
        wl_btns.addWidget(self.btn_wl_add)
        wl_btns.addWidget(self.btn_wl_rem)
        wl_left.addLayout(wl_btns)

        wl_right = QVBoxLayout()
        wl_right.addWidget(QLabel("Blacklist"))
        self.list_blacklist = QListWidget()
        for name in self.ctx.get("auto_target", "name_blacklist", default=[]):
            self.list_blacklist.addItem(name)
        wl_right.addWidget(self.list_blacklist)
        bl_btns = QHBoxLayout()
        self.btn_bl_add = QPushButton("Add")
        self.btn_bl_add.clicked.connect(lambda: self._add_to_list(self.list_blacklist, "auto_target", "name_blacklist"))
        self.btn_bl_rem = QPushButton("Remove")
        self.btn_bl_rem.clicked.connect(lambda: self._remove_from_list(self.list_blacklist, "auto_target", "name_blacklist"))
        bl_btns.addWidget(self.btn_bl_add)
        bl_btns.addWidget(self.btn_bl_rem)
        wl_right.addLayout(bl_btns)

        wl_layout.addLayout(wl_left)
        wl_layout.addLayout(wl_right)
        layout.addWidget(wl_group)
        return w

    def _create_combat_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        self.pokemon_healer_selector = PokemonHealerSelector(
            self.ctx, w, pid_provider=lambda: self.resolver.proc.pid if self.resolver else None)
        layout.addWidget(self.pokemon_healer_selector)

        # Healer settings
        h_group = QGroupBox("Healer")
        h_layout = QFormLayout(h_group)

        self.spin_hp_thresh = QSpinBox()
        self.spin_hp_thresh.setRange(1, 99)
        self.spin_hp_thresh.setValue(self.ctx.get("healer", "hp_percent_threshold", default=60))
        self.spin_hp_thresh.valueChanged.connect(lambda v: self.ctx.set(v, "healer", "hp_percent_threshold"))
        h_layout.addRow("HP Threshold (%):", self.spin_hp_thresh)

        self.spin_hp_above = QSpinBox()
        self.spin_hp_above.setRange(1, 100)
        self.spin_hp_above.setValue(self.ctx.get("healer", "hp_above_percent", default=85))
        self.spin_hp_above.valueChanged.connect(lambda v: self.ctx.set(v, "healer", "hp_above_percent"))
        h_layout.addRow("HP Stop Above (%):", self.spin_hp_above)

        self.spin_mp_thresh = QSpinBox()
        self.spin_mp_thresh.setRange(1, 99)
        self.spin_mp_thresh.setValue(self.ctx.get("healer", "mp_percent_threshold", default=40))
        self.spin_mp_thresh.valueChanged.connect(lambda v: self.ctx.set(v, "healer", "mp_percent_threshold"))
        h_layout.addRow("MP Threshold (%):", self.spin_mp_thresh)

        self.spin_mp_above = QSpinBox()
        self.spin_mp_above.setRange(1, 100)
        self.spin_mp_above.setValue(self.ctx.get("healer", "mp_above_percent", default=90))
        self.spin_mp_above.valueChanged.connect(lambda v: self.ctx.set(v, "healer", "mp_above_percent"))
        h_layout.addRow("MP Stop Above (%):", self.spin_mp_above)

        self.spin_panic_hp = QSpinBox()
        self.spin_panic_hp.setRange(1, 50)
        self.spin_panic_hp.setValue(self.ctx.get("healer", "panic_hp_percent", default=25))
        self.spin_panic_hp.valueChanged.connect(lambda v: self.ctx.set(v, "healer", "panic_hp_percent"))
        h_layout.addRow("Panic HP (%):", self.spin_panic_hp)

        self.spin_heal_delay = QSpinBox()
        self.spin_heal_delay.setRange(100, 5000)
        self.spin_heal_delay.setSingleStep(50)
        self.spin_heal_delay.setValue(self.ctx.get("healer", "delay_between_heals_ms", default=650))
        self.spin_heal_delay.valueChanged.connect(lambda v: self.ctx.set(v, "healer", "delay_between_heals_ms"))
        h_layout.addRow("Delay Between Heals (ms):", self.spin_heal_delay)

        layout.addWidget(h_group)

        # Auto-food
        f_group = QGroupBox("Auto-Food")
        f_layout = QFormLayout(f_group)

        self.spin_food_interval = QSpinBox()
        self.spin_food_interval.setRange(10, 600)
        self.spin_food_interval.setValue(self.ctx.get("auto_food", "interval_seconds", default=60))
        self.spin_food_interval.valueChanged.connect(lambda v: self.ctx.set(v, "auto_food", "interval_seconds"))
        f_layout.addRow("Interval (seconds):", self.spin_food_interval)

        self.spin_food_jitter = QSpinBox()
        self.spin_food_jitter.setRange(0, 60)
        self.spin_food_jitter.setValue(self.ctx.get("auto_food", "jitter_seconds", default=8))
        self.spin_food_jitter.valueChanged.connect(lambda v: self.ctx.set(v, "auto_food", "jitter_seconds"))
        f_layout.addRow("Jitter (seconds):", self.spin_food_jitter)

        self.spin_food_pause_hp = QSpinBox()
        self.spin_food_pause_hp.setRange(0, 99)
        self.spin_food_pause_hp.setValue(self.ctx.get("auto_food", "pause_when_hp_below_percent", default=30))
        self.spin_food_pause_hp.valueChanged.connect(lambda v: self.ctx.set(v, "auto_food", "pause_when_hp_below_percent"))
        f_layout.addRow("Pause if HP Below (%):", self.spin_food_pause_hp)

        layout.addWidget(f_group)

        # Auto-catch
        c_group = QGroupBox("Auto-Catch")
        c_layout = QFormLayout(c_group)

        self.spin_catch_throws = QSpinBox()
        self.spin_catch_throws.setRange(1, 10)
        self.spin_catch_throws.setValue(self.ctx.get("auto_catch", "throw_count", default=3))
        self.spin_catch_throws.valueChanged.connect(lambda v: self.ctx.set(v, "auto_catch", "throw_count"))
        c_layout.addRow("Throw Count:", self.spin_catch_throws)

        self.spin_catch_delay = QSpinBox()
        self.spin_catch_delay.setRange(100, 5000)
        self.spin_catch_delay.setSingleStep(50)
        self.spin_catch_delay.setValue(self.ctx.get("auto_catch", "throw_delay_ms", default=750))
        self.spin_catch_delay.valueChanged.connect(lambda v: self.ctx.set(v, "auto_catch", "throw_delay_ms"))
        c_layout.addRow("Throw Delay (ms):", self.spin_catch_delay)

        self.chk_only_after_kill = QCheckBox()
        self.chk_only_after_kill.setChecked(self.ctx.get("auto_catch", "only_after_kill", default=True))
        self.chk_only_after_kill.toggled.connect(lambda v: self.ctx.set(v, "auto_catch", "only_after_kill"))
        c_layout.addRow("Only After Kill:", self.chk_only_after_kill)

        self.spin_catch_stop_hp = QSpinBox()
        self.spin_catch_stop_hp.setRange(1, 100)
        self.spin_catch_stop_hp.setValue(self.ctx.get("auto_catch", "stop_when_hp_above_percent", default=60))
        self.spin_catch_stop_hp.valueChanged.connect(lambda v: self.ctx.set(v, "auto_catch", "stop_when_hp_above_percent"))
        c_layout.addRow("Stop If HP Above (%):", self.spin_catch_stop_hp)

        layout.addWidget(c_group)
        return w

    def _create_loot_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        group = QGroupBox("Loot Settings")
        g_layout = QFormLayout(group)

        self.list_loot = QListWidget()
        # Would load from config - placeholder
        self.list_loot.addItem("Gold Coin")
        self.list_loot.addItem("Platinum Coin")
        self.list_loot.addItem("Health Potion")
        g_layout.addRow("Desired Items:", self.list_loot)

        loot_btns = QHBoxLayout()
        self.btn_loot_add = QPushButton("Add")
        self.btn_loot_rem = QPushButton("Remove")
        loot_btns.addWidget(self.btn_loot_add)
        loot_btns.addWidget(self.btn_loot_rem)
        g_layout.addRow("", loot_btns)

        layout.addWidget(group)
        layout.addStretch()
        return w

    def _create_settings_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # General
        gen_group = QGroupBox("General")
        gen_layout = QFormLayout(gen_group)

        self.edit_process = QLineEdit(self.ctx.get("client", "process_name", default="PokeAlliance_dx.exe"))
        self.edit_process.textChanged.connect(lambda v: self.ctx.set(v, "client", "process_name"))
        gen_layout.addRow("Process Name:", self.edit_process)

        self.edit_window_title = QLineEdit(self.ctx.get("client", "window_title_pattern", default="PokeAlliance"))
        self.edit_window_title.textChanged.connect(lambda v: self.ctx.set(v, "client", "window_title_pattern"))
        gen_layout.addRow("Window Title Pattern:", self.edit_window_title)

        self.chk_focus = QCheckBox()
        self.chk_focus.setChecked(self.ctx.get("client", "focus_before_input", default=True))
        self.chk_focus.toggled.connect(lambda v: self.ctx.set(v, "client", "focus_before_input"))
        gen_layout.addRow("Focus Before Input:", self.chk_focus)

        self.spin_refocus = QSpinBox()
        self.spin_refocus.setRange(0, 1000)
        self.spin_refocus.setValue(self.ctx.get("client", "refocus_delay_ms", default=120))
        self.spin_refocus.valueChanged.connect(lambda v: self.ctx.set(v, "client", "refocus_delay_ms"))
        gen_layout.addRow("Refocus Delay (ms):", self.spin_refocus)

        self.spin_click_delay = QSpinBox()
        self.spin_click_delay.setRange(0, 500)
        self.spin_click_delay.setValue(self.ctx.get("client", "click_delay_ms", default=45))
        self.spin_click_delay.valueChanged.connect(lambda v: self.ctx.set(v, "client", "click_delay_ms"))
        gen_layout.addRow("Click Delay (ms):", self.spin_click_delay)

        self.spin_key_delay = QSpinBox()
        self.spin_key_delay.setRange(0, 500)
        self.spin_key_delay.setValue(self.ctx.get("client", "key_delay_ms", default=30))
        self.spin_key_delay.valueChanged.connect(lambda v: self.ctx.set(v, "client", "key_delay_ms"))
        gen_layout.addRow("Key Delay (ms):", self.spin_key_delay)

        layout.addWidget(gen_group)

        # Hotkeys
        hk_group = QGroupBox("Hotkeys")
        hk_layout = QFormLayout(hk_group)

        hk_map = {
            "panic_stop": "F12",
            "heal_hp": "F1",
            "heal_mp": "F2",
            "heal_panic": "F3",
            "food": "F4",
            "attack": "F5",
            "catch": "F6",
        }
        self.hk_edits = {}
        for key, default in hk_map.items():
            edit = QLineEdit(self.ctx.get("hotkeys", key, default=default))
            edit.textChanged.connect(lambda v, k=key: self.ctx.set(v, "hotkeys", k))
            hk_layout.addRow(key.replace("_", " ").title() + ":", edit)
            self.hk_edits[key] = edit

        self.chk_global_hotkeys = QCheckBox()
        self.chk_global_hotkeys.setChecked(self.ctx.get("hotkeys", "global_hotkeys", default=False))
        self.chk_global_hotkeys.toggled.connect(lambda v: self.ctx.set(v, "hotkeys", "global_hotkeys"))
        hk_layout.addRow("Global Hotkeys:", self.chk_global_hotkeys)

        layout.addWidget(hk_group)

        # Safety limits
        safe_group = QGroupBox("Safety Limits")
        safe_layout = QFormLayout(safe_group)

        self.spin_max_threads = QSpinBox()
        self.spin_max_threads.setRange(1, 16)
        self.spin_max_threads.setValue(self.ctx.get("safety_limits", "max_threads", default=8))
        self.spin_max_threads.valueChanged.connect(lambda v: self.ctx.set(v, "safety_limits", "max_threads"))
        safe_layout.addRow("Max Threads:", self.spin_max_threads)

        self.spin_queue_max = QSpinBox()
        self.spin_queue_max.setRange(8, 256)
        self.spin_queue_max.setValue(self.ctx.get("safety_limits", "input_bus_queue_max", default=32))
        self.spin_queue_max.valueChanged.connect(lambda v: self.ctx.set(v, "safety_limits", "input_bus_queue_max"))
        safe_layout.addRow("Input Queue Max:", self.spin_queue_max)

        self.spin_mem_interval = QSpinBox()
        self.spin_mem_interval.setRange(50, 1000)
        self.spin_mem_interval.setValue(self.ctx.get("safety_limits", "memory_read_interval_ms", default=150))
        self.spin_mem_interval.valueChanged.connect(lambda v: self.ctx.set(v, "safety_limits", "memory_read_interval_ms"))
        safe_layout.addRow("Memory Read Interval (ms):", self.spin_mem_interval)

        self.spin_min_input_interval = QSpinBox()
        self.spin_min_input_interval.setRange(5, 200)
        self.spin_min_input_interval.setValue(self.ctx.get("safety_limits", "min_interval_between_inputs_ms", default=25))
        self.spin_min_input_interval.valueChanged.connect(lambda v: self.ctx.set(v, "safety_limits", "min_interval_between_inputs_ms"))
        safe_layout.addRow("Min Input Interval (ms):", self.spin_min_input_interval)

        layout.addWidget(safe_group)

        # Runtime
        rt_group = QGroupBox("Runtime")
        rt_layout = QFormLayout(rt_group)

        self.combo_log_level = QComboBox()
        self.combo_log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.combo_log_level.setCurrentText(self.ctx.get("runtime", "log_level", default="INFO"))
        self.combo_log_level.currentTextChanged.connect(lambda v: self.ctx.set(v, "runtime", "log_level"))
        rt_layout.addRow("Log Level:", self.combo_log_level)

        self.chk_stop_death = QCheckBox()
        self.chk_stop_death.setChecked(self.ctx.get("runtime", "stop_on_death", default=True))
        self.chk_stop_death.toggled.connect(lambda v: self.ctx.set(v, "runtime", "stop_on_death"))
        rt_layout.addRow("Stop on Death:", self.chk_stop_death)

        self.chk_stop_disc = QCheckBox()
        self.chk_stop_disc.setChecked(self.ctx.get("runtime", "stop_on_disconnect", default=True))
        self.chk_stop_disc.toggled.connect(lambda v: self.ctx.set(v, "runtime", "stop_on_disconnect"))
        rt_layout.addRow("Stop on Disconnect:", self.chk_stop_disc)

        layout.addWidget(rt_group)

        # Save button
        btn_save = QPushButton("💾 Save All Settings")
        btn_save.clicked.connect(self._save_config)
        layout.addWidget(btn_save)
        layout.addStretch()
        return w

    def _create_debug_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # Scanner test
        scan_group = QGroupBox("Scanner Tests")
        scan_layout = QVBoxLayout(scan_group)

        btn_scan_sections = QPushButton("Run: scanner.py sections")
        btn_scan_sections.clicked.connect(lambda: self._run_scanner_test("sections"))
        scan_layout.addWidget(btn_scan_sections)

        # AOB origin: existing GUI debug literal; author/source not recorded.
        # ASSUMPTION — not validated in memory; scanner searches disk only.
        # Intended target: ASCII Player literal; not proof of a player pointer.
        btn_scan_aob = QPushButton('Run: scanner.py aob --section .rdata "50 6C 61 79 65 72"')
        btn_scan_aob.clicked.connect(lambda: self._run_scanner_test("aob"))
        scan_layout.addWidget(btn_scan_aob)

        btn_scan_aob_list = QPushButton("Run: scanner.py aob-list")
        btn_scan_aob_list.clicked.connect(lambda: self._run_scanner_test("aob-list"))
        scan_layout.addWidget(btn_scan_aob_list)

        btn_mem_check = QPushButton("Run: memory.py --check")
        btn_mem_check.clicked.connect(lambda: self._run_scanner_test("memory-check"))
        scan_layout.addWidget(btn_mem_check)

        layout.addWidget(scan_group)

        # Output
        out_group = QGroupBox("Output")
        out_layout = QVBoxLayout(out_group)
        self.debug_output = QTextEdit()
        self.debug_output.setReadOnly(True)
        self.debug_output.setFont(QFont("Consolas", 9))
        out_layout.addWidget(self.debug_output)
        layout.addWidget(out_group)

        return w

    def _setup_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setToolTip("PKA Bot")
        menu = QMenu()
        act_show = QAction("Show", self)
        act_show.triggered.connect(self.show)
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self.close)
        menu.addAction(act_show)
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.show()

    def _load_config_to_ui(self):
        """Sync config values to UI widgets."""
        pass  # Values loaded in widget creation

    def _save_config(self):
        self.ctx.save_config()
        self._log("INFO", "Configuration saved")

    def _add_to_list(self, list_widget: QListWidget, section: str, key: str):
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, "Add Entry", "Enter name:")
        if ok and text:
            list_widget.addItem(text)
            current = self.ctx.get(section, key, default=[])
            current.append(text)
            self.ctx.set(current, section, key)

    def _remove_from_list(self, list_widget: QListWidget, section: str, key: str):
        for item in list_widget.selectedItems():
            row = list_widget.row(item)
            list_widget.takeItem(row)
            current = self.ctx.get(section, key, default=[])
            if 0 <= row < len(current):
                current.pop(row)
                self.ctx.set(current, section, key)

    def _add_waypoint(self):
        if not self.engine or not self.engine.navigator:
            self._log("WARNING", "Engine not running")
            return
        # Would get current position from resolver
        self._log("INFO", "Add waypoint at current position (requires resolver)")

    def _remove_waypoint(self):
        row = self.wp_table.currentRow()
        if row >= 0 and self.engine and self.engine.navigator:
            self.engine.navigator.remove_waypoint(row)
            self._refresh_waypoint_table()

    def _clear_waypoints(self):
        if self.engine and self.engine.navigator:
            self.engine.navigator.clear_waypoints()
            self._refresh_waypoint_table()

    def _load_waypoints(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Waypoints", "", "JSON Files (*.json)")
        if path and self.engine and self.engine.navigator:
            self.engine.navigator.load_waypoints(path)
            self._refresh_waypoint_table()

    def _save_waypoints(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Waypoints", "waypoints.json", "JSON Files (*.json)")
        if path and self.engine and self.engine.navigator:
            self.engine.navigator.save_waypoints(path)

    def _refresh_waypoint_table(self):
        if not self.engine or not self.engine.navigator:
            return
        wps = self.engine.navigator.waypoints
        self.wp_table.setRowCount(len(wps))
        for i, wp in enumerate(wps):
            self.wp_table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.wp_table.setItem(i, 1, QTableWidgetItem(wp.name))
            self.wp_table.setItem(i, 2, QTableWidgetItem(str(wp.x)))
            self.wp_table.setItem(i, 3, QTableWidgetItem(str(wp.y)))
            self.wp_table.setItem(i, 4, QTableWidgetItem(str(wp.z)))
            self.wp_table.setItem(i, 5, QTableWidgetItem(wp.action))

    def _on_start(self):
        if self.engine:
            return
        self._log("INFO", "Starting bot...")

        # Create resolver with live process
        try:
            from memory import Process, Resolver
            proc_name = self.ctx.get("client", "process_name", default="PokeAlliance_dx.exe")
            proc = Process(proc_name, config=self.ctx.config.get("safety", {}))
            if not proc.attach():
                self._log("ERROR", "Failed to attach to process")
                QMessageBox.critical(self, "Error", "Failed to attach to PokeAlliance_dx.exe")
                return
            self.resolver = Resolver(proc, offsets_path="offsets.json", config_path=self.config_path)
        except Exception as exc:
            self._log("ERROR", f"Resolver init failed: {exc}")
            QMessageBox.critical(self, "Error", f"Failed to initialize resolver: {exc}")
            return

        self.engine = create_engine(config_path=self.config_path, resolver=self.resolver)

        self.worker_thread = QThread()
        self.worker = BotWorker(self.engine, self.resolver)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.status_update.connect(self._on_status_update)
        self.worker.log_message.connect(self._log)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker_thread.start()

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_pause.setEnabled(True)

    def _on_stop(self):
        if self.worker:
            self.worker.stop()
        self._log("INFO", "Stop requested")

    def _on_pause(self):
        if self.engine:
            if self.engine.ctx.is_paused():
                self.engine.resume()
                self.btn_pause.setText("⏸ PAUSE")
            else:
                self.engine.pause()
                self.btn_pause.setText("▶ RESUME")

    def _on_worker_finished(self):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("⏸ PAUSE")
        self.worker_thread.quit()
        self.worker_thread.wait()
        self.worker = None
        self.worker_thread = None
        self.engine = None
        if self.resolver:
            self.resolver.proc.detach()
            self.resolver = None

    def _on_status_update(self, status: dict):
        # Dashboard
        running = status.get("running", False)
        self.lbl_dash_status.setText("RUNNING" if running else "STOPPED")
        self.lbl_dash_status.setStyleSheet(
            f"color: {DARK_PALETTE['green'] if running else DARK_PALETTE['red']}; font-size: 18px; font-weight: bold;"
        )

        # Modules
        mods = status.get("modules", {})
        active = sum(1 for v in mods.values() if v)
        total = len(mods)
        self.lbl_dash_modules.setText(f"{active}/{total} active")

        # Stats
        stats = status.get("stats", {})
        for key, label in self.stat_labels.items():
            label.setText(str(stats.get(key, 0)))

        # Navigator
        nav = status.get("navigator", {})
        self._refresh_waypoint_table()

    def _update_status_bar(self):
        if self.engine and self.engine.ctx:
            uptime = self.engine.ctx.stats.get("uptime_start")
            # Would calculate uptime
            pass

    def _run_scanner_test(self, test: str):
        import subprocess
        self.debug_output.clear()
        self.debug_output.append(f"$ Running {test}...")
        try:
            if test == "sections":
                cmd = ["python", "scanner.py", "sections"]
            elif test == "aob":
                # AOB origin: existing GUI debug literal; author/source not recorded.
                # ASSUMPTION — not validated in memory; scanner searches disk only.
                # Intended target: ASCII Player literal; not proof of a player pointer.
                cmd = ["python", "scanner.py", "aob", "--section", ".rdata", "50 6C 61 79 65 72"]
            elif test == "aob-list":
                cmd = ["python", "scanner.py", "aob-list"]
            elif test == "memory-check":
                cmd = ["python", "memory.py", "--check"]
            else:
                return
            result = subprocess.run(cmd, cwd="C:\\pokebot", capture_output=True, text=True, timeout=30)
            self.debug_output.append(result.stdout)
            if result.stderr:
                self.debug_output.append(f"STDERR:\n{result.stderr}")
            self.debug_output.append(f"Exit code: {result.returncode}")
        except subprocess.TimeoutExpired:
            self.debug_output.append("TIMEOUT")
        except Exception as exc:
            self.debug_output.append(f"ERROR: {exc}")

    def _log(self, level: str, msg: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        color = {
            "DEBUG": DARK_PALETTE["fg_muted"],
            "INFO": DARK_PALETTE["fg"],
            "WARNING": DARK_PALETTE["yellow"],
            "ERROR": DARK_PALETTE["red"],
        }.get(level, DARK_PALETTE["fg"])
        self.log_view.append(f'<span style="color:{color}">[{timestamp}] [{level}] {msg}</span>')
        self.debug_output.append(f"[{timestamp}] [{level}] {msg}")

    def closeEvent(self, event):
        if self.worker:
            self.worker.stop()
            self.worker_thread.quit()
            self.worker_thread.wait()
        if self.resolver:
            self.resolver.proc.detach()
        self.ctx.save_config()
        event.accept()


def main(config_path: str = None):
    app = QApplication(sys.argv)
    apply_dark_theme(app)
    app.setFont(QFont("Segoe UI", 9))

    window = MainWindow(config_path)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
