# PokéBot

Automação e leitura de memória de alta performance para client de jogo (Tibia / PokeAlliance / PXG).

## Requisitos
- Windows 10/11 x64
- Python 3.11+
- Executar como Administrador (o cliente PokeAlliance roda elevado)
- offsets.json no formato schema v2

## Escolha do Pokémon de cura e skill
Contexto atualizado e pendências: [CONTEXTO_RETOMADA.md](CONTEXTO_RETOMADA.md).
Snapshot dos offsets: [backup_ponteiros](backup_ponteiros/README.md).
Requisito confirmado, ainda pendente: escolha manual fixa de M1–M5,
sem ler skills nem cooldowns da telemetria. O comportamento descrito abaixo
é o estado atual, anterior a esse ajuste; ainda não executa cura por Pokémon.

Na aba Combat, o painel Pokémon de cura lista os Pokémon da pokébar
do cliente escolhido e permite selecionar uma skill ativa (m1, m2 etc.).
A seleção usa UUID, não nome ou slot: continua identificando o mesmo
Pokémon quando a pokébar muda de ordem e distingue nomes repetidos.
As opções são atualizadas a cada segundo e configurações ficam nas chaves
`healer.heal_pokemon_uuid`, `healer.heal_pokemon_name` e `healer.heal_move`.
Use o botão de salvar configurações ou feche normalmente a GUI para persistir.
A fonte atual é somente leitura de `%LOCALAPPDATA%/OTPbot/telemetry_<PID>.json`,
publicada pelo PKA Tools; não é detecção independente por MemoryReader.
Telemetria ausente/desatualizada desabilita a seleção, sem apagar a escolha.
Os nomes das skills são seus comandos mX; o usuário deve escolher a que cura
o personagem. Habilidades passivas não aparecem como opções.
Este painel não aciona troca de Pokémon nem skills; o healer por hotkey
legado abaixo continua separado. A GUI requer PySide6.

## Healer por hotkey
O healer usa somente `player.hp` e `player.hp_max`; MP não bloqueia a cura.
Em `config.json`, preserva `hp_percent_threshold`, `hp_hotkey`,
`panic_hp_percent` e `panic_hotkey`, inclusive alterações pela GUI.
`hold_ms` controla apenas a duração da tecla (padrão 50 ms).
`cooldown_ms` controla o intervalo normal; quando ausente, usa
`delay_between_heals_ms` (650 ms na configuração atual; sem ambos, 800 ms).
`emergency_cooldown_ms` controla o intervalo de emergência (padrão 400 ms).
Esta versão cura abaixo do threshold, sem prolongar a cura até
`hp_above_percent`; as opções de MP e `panic_delay_ms` não são usadas.
Os contadores indicam ações aceitas na fila, não cura confirmada no jogo.

## Scan guiado de pokémons
Execute como Administrador: `python -m core.tools.scan_pokemon PokeAlliance_dx.exe`.
Ative os slots solicitados (padrão 2 → 3 → 1 → 2) e pressione ENTER
no terminal após cada troca. A ferramenta não envia teclas ao jogo.
Testa separadamente as hipóteses de índices 0-based e 1-based em int32;
use `--slot-type uint8` para testar bytes. Não presume F1–F6 para selecionar.
`--hp` solicita HP absoluto e máximo do Pokémon em cada etapa; não usa
o HP do personagem nem presume um intervalo de 1 a 999.
As leituras iniciais usam blocos de 4 MB; as demais releem só candidatos.
Com menos de 50 sobreviventes por campo, busca chains automaticamente
(pode demorar). Use `--skip-chains` para fazer somente o scan diferencial.
Salva `pokemon_candidates.json` com PID, histórico, cobertura e candidatos;
não altera `offsets.json` nem marca chains como verificadas. Valide cada
campo durante trocas, sem Pokémon ativo e após reiniciar o cliente.
Um campo pode não existir como índice simples, ou mudar de endereço ao trocar.
O limite de candidatos interrompe explicitamente o scan, sem truncar resultados.

## Módulos
- **Engine**: Loop principal e processamento assíncrono.
- **Memory**: Leitura de estruturas PE, offsets de memória, coordenadas (X, Y, Z) e status de vida (HP / HP Max).
- **Navigator**: Navegação por waypoints e desvio de obstáculos.
- **Modules**: Healer, Auto Target, Auto Catch, Cavebot, Alarms e Auto Food.
- **GUI**: Interface gráfica integrada.
