"""Seletor de Pokémon de cura e skill com identidade estável por UUID."""
from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, QTimer, Qt
from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QLabel

from core import MemoryReader
from core.pokemon_roster import PokemonRosterReader, RosterError, selection_values


def live_clients():
    return [row["pid"] for row in MemoryReader.list_candidate_processes("PokeAlliance")
            if row["name"].casefold() == "pokealliance_dx.exe"]


class PokemonHealerSelector(QGroupBox):
    def __init__(self, ctx, parent=None, reader=None, process_provider=None, pid_provider=None):
        super().__init__("Pokémon de cura", parent)
        self.ctx = ctx
        self.reader = reader or PokemonRosterReader(ctx.get("healer", "telemetry_directory", default=None))
        self.process_provider = process_provider or live_clients
        self.pid_provider = pid_provider or (lambda: None)
        self.snapshot = None
        layout = QFormLayout(self)
        self.client_combo = QComboBox()
        self.pokemon_combo = QComboBox()
        self.skill_combo = QComboBox()
        self.status = QLabel()
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        note = QLabel("Fonte: telemetria local do PKA Tools. Este painel configura a escolha; não executa cura.")
        note.setWordWrap(True)
        layout.addRow("Cliente:", self.client_combo)
        layout.addRow("Pokémon:", self.pokemon_combo)
        layout.addRow("Skill de cura:", self.skill_combo)
        layout.addRow(self.status)
        layout.addRow(note)
        self.client_combo.currentIndexChanged.connect(self.refresh)
        self.pokemon_combo.currentIndexChanged.connect(self._choose_pokemon)
        self.skill_combo.currentIndexChanged.connect(self._choose_skill)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    @staticmethod
    def _populate(combo, prompt, entries, selected):
        blocker = QSignalBlocker(combo)
        combo.clear()
        combo.addItem(prompt, None)
        for text, identity in entries:
            combo.addItem(text, identity)
        index = combo.findData(selected) if selected is not None else 0
        combo.setCurrentIndex(max(index, 0))
        del blocker

    def refresh(self, *_):
        if any(combo.view().isVisible() for combo in
               (self.client_combo, self.pokemon_combo, self.skill_combo)):
            return
        try:
            pids = sorted(set(self.process_provider()))
            fixed_pid = self.pid_provider()
            selected_pid = fixed_pid or self.client_combo.currentData()
            if selected_pid not in pids:
                selected_pid = pids[0] if len(pids) == 1 and fixed_pid is None else None
            self._populate(self.client_combo, "Selecione o cliente", [(f"PID {pid}", pid) for pid in pids], selected_pid)
            self.client_combo.setEnabled(fixed_pid is None)
            if selected_pid is None:
                raise RosterError("selecione um cliente conectado")
            self.snapshot = self.reader.read(selected_pid)
            self._render()
        except (RosterError, OSError) as exc:
            self.snapshot = None
            self._populate(self.pokemon_combo, "Lista indisponível", [], None)
            self._populate(self.skill_combo, "Skills indisponíveis", [], None)
            self.pokemon_combo.setEnabled(False)
            self.skill_combo.setEnabled(False)
            self.status.setText(str(exc))

    def _render(self):
        uuid = self.ctx.get("healer", "heal_pokemon_uuid", default=None)
        entries = [(f"{item.name} — slot {item.slot} — HP {item.hp_percent}% [{item.uuid[:8]}]", item.uuid)
                   for item in self.snapshot.pokemon]
        self._populate(self.pokemon_combo, "Escolha o Pokémon de cura", entries, uuid)
        self.pokemon_combo.setEnabled(bool(entries))
        pokemon = self.snapshot.find(uuid)
        moves = pokemon.moves if pokemon else ()
        move = self.ctx.get("healer", "heal_move", default=None)
        self._populate(self.skill_combo, "Escolha a skill que cura o personagem",
                       [(item.spellword, item.spellword) for item in moves], move)
        self.skill_combo.setEnabled(bool(moves))
        if pokemon is None:
            self.status.setText("Pokémon salvo não está nesta pokébar." if uuid else "Escolha o Pokémon de cura.")
        elif move not in {item.spellword for item in moves}:
            self.status.setText("Escolha a skill de cura; habilidades passivas não são selecionáveis.")
        else:
            skill = next(item for item in moves if item.spellword == move)
            self.status.setText(f"{pokemon.name}: {move}; cooldown restante {skill.remaining_ms / 1000:.1f}s. "
                                "Use Salvar configurações para persistir a escolha.")

    def _choose_pokemon(self, *_):
        uuid = self.pokemon_combo.currentData()
        if uuid is None or self.snapshot is None:
            return
        try:
            fresh = self.reader.read(self.snapshot.pid)
            pokemon = fresh.find(uuid)
            if pokemon is None:
                raise RosterError("Pokémon não está mais nesta pokébar")
            previous = self.ctx.get("healer", "heal_pokemon_uuid", default=None)
            self.ctx.set(uuid, "healer", "heal_pokemon_uuid")
            self.ctx.set(pokemon.name, "healer", "heal_pokemon_name")
            if previous != uuid:
                self.ctx.set("", "healer", "heal_move")
            self.snapshot = fresh
            self._render()
        except RosterError as exc:
            self.refresh()
            self.status.setText(str(exc))

    def _choose_skill(self, *_):
        word = self.skill_combo.currentData()
        uuid = self.ctx.get("healer", "heal_pokemon_uuid", default=None)
        if word is None or self.snapshot is None:
            return
        try:
            fresh = self.reader.read(self.snapshot.pid)
            for key, value in selection_values(fresh, uuid, word).items():
                self.ctx.set(value, "healer", key)
            self.snapshot = fresh
            self._render()
        except RosterError as exc:
            self.refresh()
            self.status.setText(str(exc))
