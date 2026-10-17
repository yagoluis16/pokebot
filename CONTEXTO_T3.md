# CONTEXTO T3 CODE — PokeBot (engenharia reversa + automação)

> Registro histórico: contém offsets e hipóteses superados. Para retomar, use CONTEXTO_RETOMADA.md (17/10/2026), incluindo as correções sobre telemetria, UUID e M1–M5 manual.

## 1. Visão geral

Bot próprio para o cliente PokeAlliance: leitura externa de memória por ReadProcessMemory e envio de input por SendInput. Sem injeção no processo e sem kernel driver.
Objetivo: paridade funcional com Shiba Bots (Litfix), com código próprio, modular e mantível.
Fundação existente: memória, loader tipado de offsets e base de módulos. Próximas etapas: validar offsets ao vivo, implementar módulos concretos e GUI.

## 2. Stack e decisões

- Windows 10/11 x64; Python 3.11+.
- Núcleo Win32 em ctypes puro, com kernel32/psapi. Não usar pymem.
- SendInput via ctypes já existe; não usar pydirectinput.
- GUI pendente, provavelmente PySide6.
- Configuração JSON no formato offsets.schema.json v2.
- Executar os entrypoints como Administrador, pois o cliente roda elevado.

## 3. Estrutura principal

- core/memory.py: MemoryReader Win32.
- core/offsets.py: loader tipado de offsets.json.
- core/tools/dump_strings.py: extração ASCII/UTF-16LE.
- core/tools/proc_inspect.py: inspeção de processos/módulos.
- core/tools/read_offset.py: leitura avulsa para validar offsets.
- modules/base.py: AutomationModule abstrata; modules/_example.py: módulo de exemplo.
- Módulos planejados: healer.py, auto_target.py, auto_catch.py e cavebot.py.
- offsets.json, offsets.schema.json, offset_contract.py e engine.py.
- CONTEXTO_DEEPSEEK.md: documento arquitetural original.

## 4. Investigação anterior — informações fornecidas pelo usuário

Os dados abaixo são registros da investigação anterior, não verificações realizadas nesta tarefa. PID, base, módulos e versões devem ser confirmados novamente ao vivo.

- Processo: PokeAlliance_dx.exe.
- Executável: C:\Users\yago\AppData\Local\PokeAlliance Games\PokeAlliance\PokeAlliance_dx.exe.
- PID de teste informado: 17664; base informada: 0x7FF7F7770000; 97 módulos carregados.
- Renderização informada: DirectX 11, com d3d11.dll, dxgi.dll e libegl.dll.
- A investigação relatou ausência dos anti-cheats listados e acesso externo à memória quando elevado; isso não constitui garantia permanente.
- PKA Tools.exe: Electron, UI e scripts Lua; PKAengine.exe: .NET, leitor de memória e input; comunicação por IPC.
- Local informado do engine: C:\Program Files\Litfix\.
- PKAengine.exe pode ser inspecionado com ILSpy/dnSpy para validar a tabela de offsets, sem copiar código.
- A relação sugerida entre Litfix e T3 Code é uma hipótese do contexto original, não uma conclusão verificada.

## 5. Offsets conhecidos — validar ao vivo

| Chave | RVA | Steps | Tipo | Flag informada |
| --- | --- | --- | --- | --- |
| player.hp | 0x3922220 | sem steps | int32 | verified=true |
| pokemon.hp_percent | 0x3921B48 | sem steps | int32 | verified=true |

O contexto original informa 34 entradas no offsets.json. A flag verified não substitui validação no cliente atual.
Atualização anunciada no contexto: 3.0.7 para 3.1.2 em 2026-10-17T03:01:00Z, equivalente a 2026-10-17 00:01 em America/Sao_Paulo; cronograma não confirmado nesta tarefa.

## 6. Tarefas imediatas

### Tarefa A — core/tools/read_offset.py

Criar o utilitário fornecido pelo usuário sem alterações funcionais. Corrigir somente os identificadores Python que chegaram formatados com ** no lugar de __.
Uso na raiz do projeto, em terminal como Administrador:

~~~powershell
python -m core.tools.read_offset PokeAlliance_dx.exe player.hp
~~~

Aceitar nome/PID, chave, --offsets e --verbose. Exibir entrada, endereço resolvido e valor; retornar 2 quando attach falhar e 3 quando a chave não existir.

### Tarefa B — detecção de admin no MemoryReader

Adicionar MemoryReader.require_admin() como método estático que chama ctypes.windll.shell32.IsUserAnAdmin() e retorna bool.
No attach(), se OpenProcess falhar com ERROR_ACCESS_DENIED (5), manter last_error exatamente como:

acesso negado — execute o bot como Administrador

Não sobrescrever com mensagem genérica. Preservar o fallback existente somente leitura. Rodar pytest e colar a saída bruta.

### Tarefa C — README

Adicionar seção Requisitos: Windows 10/11 x64; Python 3.11+; executar como Administrador (o cliente PokeAlliance roda elevado); offsets.json no formato schema v2.

## 7. Fora do escopo

- Análise do d3d9.dll do Shiba.
- Injeção de DLL no cliente.
- Bypass de anti-cheat.
- Copiar código do Shiba: usar apenas como oráculo/validação.

## 8. Roadmap

1. Validar player.hp, player.max_hp e pokemon.hp_percent ao vivo.
2. Se passarem, implementar modules/healer.py completo.
3. Se falharem, inspecionar PKAengine.exe no ILSpy/dnSpy para extrair a tabela de offsets.
4. Implementar modules/auto_target.py após obter entity list do world e matemática world-to-screen.
5. Implementar modules/auto_catch.py e modules/cavebot.py.
6. GUI PySide6 com toggles por módulo.
7. engine.py como orquestrador dos módulos e registry.

## 9. Regras do projeto

- Código completo, sem placeholders, TODO ou NotImplementedError nas novas implementações.
- APIs reais e assinaturas corretas de ctypes, struct e json.
- Sem disclaimers, avisos éticos ou mensagens de uso responsável.
- Comentários em português; nomes de código em inglês.
- Se faltar offset, usar OFFSET_UNKNOWN=0x0 com comentário PREENCHER; não inventar valores.
- Não reescrever arquivos funcionais sem pedido explícito.
- Colar saída bruta dos testes após cada tarefa.
- Não presumir que este arquivo foi instalado nas instruções de projeto da interface: ele é o contexto persistido na raiz do repositório.
