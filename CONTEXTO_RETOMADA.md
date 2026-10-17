# Contexto de retomada — PokeBot

Atualizado em 17/10/2026. Este documento substitui as suposições desatualizadas dos contextos anteriores. Não representa uma nova validação ao vivo.

## Estado real
- Leitura externa Win32 por ReadProcessMemory; sem injeção. Leituras de cliente elevado exigem execução como Administrador. Não há garantia sobre ausência de anti-cheat ou compatibilidade futura.
- Healer legado corrigido: MP ausente não bloqueia HP; cooldown monotônico separado da duração física da tecla.
- O healer ainda NÃO executa a sequência de cura usando Pokémon. Selecionar Pokémon/skill na GUI não implementa essa execução.
- Último resultado registrado antes deste backup: 200 testes passando, 1 ignorado, 40 subtests. O teste ignorado depende de PySide6, ausente no Python padrão. Não houve teste visual da GUI nem envio de input ao jogo nesta etapa.

## Requisitos confirmados pelo usuário
1. Detectar os Pokémon disponíveis e permitir escolher o Pokémon de cura.
2. O usuário escolhe MANUALMENTE M1, M2, M3, M4 ou M5. Não ler habilidades nem cooldowns de habilidades da memória ou telemetria.
3. O Pokémon ativo pode subir ao topo da pokébar: identificar por UUID, não por posição fixa nem somente pelo nome.
4. Cura do personagem usa Pokémon + move; não presumir poção.

## O que já está implementado e o que falta
- core/pokemon_roster.py: adaptador somente leitura de telemetria local; valida PID, contrato, integridade e frescor.
- gui/pokemon_selector.py: seleção por UUID, escolha de cliente e atualização da lista.
- gui/main.py: painel integrado à aba Combat; configuração nas chaves healer.heal_pokemon_uuid, healer.heal_pokemon_name e healer.heal_move.
- PENDENTE: o código atual ainda deriva a lista de moves da telemetria. Substituir por opções fixas M1–M5 e remover a dependência de moves/cooldowns do adaptador, GUI, testes e documentação.
- PENDENTE: implementar máquina de estados de cura, com seleção confirmada, espera não bloqueante, uso do move e retorno ao Pokémon original por identidade.
- Não presumir que F1–F6 selecionam Pokémon, nem que M1 significa uma tecla Windows. Calibrar os controles reais antes de executar.
- Comando de reset, se necessário, e política de retorno ainda não foram definidos.

## Fonte atual da lista de Pokémon — dependência importante
A lista vem de %LOCALAPPDATA%/OTPbot/telemetry_<PID>.json, produzida pelo PKA Tools. Isso NÃO é detecção independente por ReadProcessMemory. Sem produtor ativo e telemetria recente, a lista fica indisponível.

Foram observados Charmander, Oddish, Togepi e Spearow; a ordem mudou ao ativar a opção de mover o Pokémon em uso para o topo. A lista é histórica, não uma leitura atual.

A tentativa de descompilar bytecode .jsc não é necessária para a próxima etapa. A inspeção local encontrou o contrato de telemetria; portanto não é correto dizer que toda investigação teve retorno zero. Não publicar código extraído, binários ou dumps de terceiros.

## Offsets e semântica do resolver
O schema real usa base_rva, não rva. A cópia integral está em backup_ponteiros/offsets.snapshot.json; offsets.json na raiz continua sendo o arquivo de execução.

| Campo | base_rva | steps | terminal | deref | tipo | evidência histórica |
| --- | --- | --- | --- | --- | --- | --- |
| player.hp | 0x3922260 | [0] | 0 | false | int32 | pointer scan e restart |
| player.hp_max | 0x3922260 | [0] | 4 | false | int32 | valor 200 confirmado pelo usuário |
| pokemon.hp_percent | 0x3921B48 | [] | 0x3C8 | true | int32 | percentual, não HP absoluto |

Para HP: endereço = read_ptr(base_do_módulo + 0x3922260); ler int32 no endereço para HP e no endereço + 4 para máximo. steps=[0] já representa a desreferência no contrato existente; não ativar deref adicional por engano.

Histórico de restart: PID 14808 → 29028; heap 0x2A205F20000 → 0x16A87FE0000; HP 177 e máximo 200. Outra sessão registrada: PID 14732, base 0x7FF7F7770000, HP/max 200/200. PIDs e heaps são históricos e não devem ser reutilizados como endereços atuais.

Não adicionar offsets inventados nem promover candidatos a verified=true. As demais entradas e seus flags estão preservados integralmente no snapshot, não foram revalidados para este backup.

## Scan de slot — já realizado, ainda não validado
- Sequência 2 → 3 → 1 → 2 produziu 3 candidatos 0-based e nenhum 1-based.
- Candidatos: 0x21CB91C7244, 0x21CB91DE39C e 0x21CC6539C88. Os dois primeiros falharam em leituras posteriores como índices simples.
- O terceiro gerou 20 chains; nenhuma foi validada como active_slot.
- Exemplo de candidato NÃO USAR: PokeAlliance_dx.exe+0x390F8F0, steps=[0x6A8,0x688,0xA08], terminal=0. Em teste posterior a folha mudou e os valores não corresponderam ao slot esperado.
- Relatórios: slot-candidates-20261017-010934.json e scan-slots-20261017-010934-console.txt, preservados localmente nas evidências do backup.
- A opção de mover o ativo ao topo confundiu a hipótese de índices visuais fixos. Não repetir o mesmo scan como se ainda não tivesse sido feito.
- Não usar --hp com porcentagem: essa opção pede HP absoluto/máximo; temos pokemon.hp_percent.

## Arquitetura e execução
- modules/healer.py herda de Module; construtor compatível com Healer(ctx, bus, resolver).
- Module.press(vk, hold_ms=50, priority=10) delega ao inputbus. Retorno true indica aceitação na fila, não execução nem cura confirmada.
- Config é lida via contexto/config.json; preservar atualizações da GUI.
- inputbus.py / wininput.py usam SendInput e tentam trazer a janela ao foreground. Não prometer input em background.
- Entry point correto: python __main__.py. Não existe main.py na raiz.
- python __main__.py --headless pode iniciar todos os módulos habilitados, inclusive AutoFood e Alarms. Não iniciar casualmente durante diagnóstico.
- Resolver.read_field retorna None para campos ausentes/não verificados.

## Próxima retomada — ordem recomendada
1. Verificar processo atual e comparar player.hp e player.hp_max com a tela, sem enviar teclas.
2. Confirmar que a telemetria pertence ao PID correto e está recente.
3. Aplicar a correção M1–M5 manual, sem leitura de skills/cooldowns; preservar escolha por UUID.
4. Rodar testes focados, suíte completa e compilação dos arquivos da GUI. Teste visual exige instalar PySide6 no ambiente apropriado.
5. Calibrar os controles reais de seleção, execução de M1–M5 e retorno. Só depois implementar/testar a sequência de cura com autorização do usuário.

## Comandos de diagnóstico (PowerShell elevado para memória)
~~~powershell
cd C:\Users\yago\Desktop\pokebot
python -m core.tools.proc_inspect PokeAlliance
python -m core.tools.read_offset PokeAlliance_dx.exe player.hp
python -m core.tools.read_offset PokeAlliance_dx.exe player.hp_max
python -m pytest tests/test_pokemon_roster.py tests/test_pokemon_selector.py -q
python -m pytest -q
python -m compileall -q core/pokemon_roster.py gui/pokemon_selector.py gui/main.py
~~~

## Atualização do cliente
O executável tinha LastWriteTime 16/10/2026 19:14:38 e versão de arquivo/produto vazia na inspeção anterior. Isso não prova versão 3.1.2 nem invalida automaticamente offsets. Não reutilizar afirmações relativas como “faltam 40 minutos”; a janela citada em conversas antigas já passou. Revalidar por leitura e comparação observável.

## Backup e publicação
- Documentos/BACKUPPOKEBOT: cópia local datada do projeto e contexto, sem .git, caches ou código extraído de terceiros.
- backup_ponteiros/: snapshot integral de offsets, schema, tabela CE e evidências locais separadas dos campos validados.
- Repositório existente: yagoluis16/pokebot (público na inspeção de 17/10/2026). Preservar essa visibilidade; não publicar telemetria pessoal, dumps, logs de execução ou código extraído de terceiros.
