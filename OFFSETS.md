# Contrato de offsets — versão 2

## Porcentagem do Pokémon ativo

`pokemon.hp_percent` resolve `read_ptr(module_base + 0x3921B48) + 0x3C8`
e lê `int32`. A configuração usa `steps: []` com `deref: true`, portanto
há exatamente uma desreferência antes de somar o terminal.
O alvo é relido a cada acesso, sem cache do objeto.

Validação relatada pelo usuário no CE: acompanha dano/cura, troca de Pokémon
com valores 87 → 100 → 87 e permanece funcional após reiniciar o cliente.
É uma porcentagem calculada da interface para o Pokémon ativo/selecionado,
não HP absoluto nem uma enumeração de todos os Pokémon.
Não confundir com `player.hp` e `player.hp_max`.

`py validate_position.py` inclui `POKEMON_HP=<valor>%`; alvo nulo, falha de
leitura ou valor fora de 0–100 gera `FAIL`, sem reaproveitar um valor anterior.
Nenhuma automação de cura foi ativada por essa calibração.

O arquivo `offsets.schema.json` define o JSON Schema Draft 2020-12.
`offset_contract.py` aplica as mesmas restrições no carregamento, sem dependências.
Entradas ficam em `entries`, identificadas por `bloco.campo`, por exemplo `player.x`.
Cada entrada contém estes campos obrigatórios, além dos opcionais `mask`, `shift` e `deref`:

| Campo | Contrato |
|---|---|
| `module` | Nome exato do módulo, com extensão; não alias nem caminho. A busca ignora maiúsculas/minúsculas conforme Windows. |
| `base_rva` | Inteiro não negativo de 32 bits, relativo à base atual do módulo; `null` se desconhecido. |
| `steps` | `null` se a cadeia é desconhecida; caso contrário, array de até 16 offsets inteiros ou `null` por etapa desconhecida. Cada etapa desreferencia e depois soma o offset. |
| `terminal` | Inteiro somado depois de todas as desreferências, sem desreferenciar novamente; `null` se desconhecido. |
| `type` | `int8`, `uint8`, `int16`, `uint16`, `int32`, `uint32`, `float32` ou `float64`; little-endian. |
| `verified` | Booleano. Só `true` depois da validação em sessão CE ao vivo; enquanto `false`, nenhuma leitura ocorre. |
| `note` | Origem e evidência da calibração, ou `unverified placeholder`. |
| `source` | `assumed`, `verified_ce` ou `reversed_disasm`; descreve a origem da entrada. |

Semântica exata:

```text
address = module_base + base_rva
para cada step em steps, na ordem do array:
    address = read_pointer(address) + step
se entry.get("deref", False):
    address = read_pointer(address)
address = address + terminal
value = read_type(address)
se mask estiver presente:
    value = (value & mask) >> shift  # shift ausente = 0
```

Uma desreferência na própria base exige `steps: [0]`. Array vazio significa
endereço direto, sem desreferências. Zero é válido em todos os deslocamentos.
Ponteiro lido com valor zero é nulo e interrompe a resolução. Não há fallback
para endereço absoluto. O tamanho de ponteiro vem do PE real, não do Python.
O endereço base deve cair dentro do módulo; alvos desreferenciados podem estar no heap.
As cadeias são recalculadas a cada leitura, sem cache de ponteiros do jogador.

O JSON exige inteiros decimais: strings `"0x..."`, floats e booleanos em campos
numéricos são rejeitados pelo validador Python. `null` identifica offsets desconhecidos;
zero é válido. Entradas verificadas não podem conter `null`.
Todos os offsets desconhecidos do arquivo ativo são `null`, inclusive `steps`.
Os tipos herdados são **ASSUMPTION**, sem calibração.

`offsets.legacy.json` preserva os valores anteriores para consulta, com anotações AOB adicionadas.
Strings, ponteiros como valores finais e campos de bits ficam somente nesse
arquivo: não possuem representação nos oito tipos escalares solicitados.
Flags anteriormente `bool` usam `uint8`, ainda como ASSUMPTION.
Assinaturas anteriores estão em `signatures.json`, todas não verificadas.
O scanner é uma ferramenta de investigação: encontrar uma assinatura não altera
`verified` nem confirma sua associação ao campo.

Não copie a ordem visual dos offsets do CE sem conferir as desreferências:
o array acima é sempre a ordem de execução, da raiz até o valor.

## Origem e aviso de leitura

`source` e obrigatorio: `assumed`, `verified_ce` ou `reversed_disasm`.
X/Y/Z usam `int32`; Z aplica `mask: 255`, `shift: 0`.
Esses três campos foram marcados como verificados conforme o relato do usuário.
X/Y/Z usam `steps: [0]`: `read_ptr(module_base + base_rva) + terminal`,
correspondendo à cadeia mostrada no CE. `OK` no validador significa que as leituras
terminaram, não que os números representam a posição correta.
`mask` aceita inteiro não negativo de 32 bits, somente para tipos inteiros.
`shift` aceita 0 a 31 e exige `mask`; quando omitido, assume zero.
Não há desreferência implícita na base. Para uma desreferência explícita, use `[0]`.
Se `verified` for falso e `source` for `assumed`, a primeira tentativa
de leitura por campo/resolvedor emite `[warn] reading ASSUMED field X — value may be wrong`.
O aviso nao libera leituras: entradas nao verificadas ou com offsets `null` continuam bloqueadas.

## Auditoria AOB

JSON nao aceita comentarios; `_comment` imediatamente antes de `pattern`
registra origem, status, alvo pretendido e evidencia. Nenhum byte foi alterado.
O arquivo legado e o exportador historico receberam somente essas anotacoes;
seus offsets antigos nao sao configuracao ativa e nao devem ser usados para calibracao.

## Desreferência final opcional

`deref` é um booleano opcional, falso por padrão. Quando verdadeiro, lê um ponteiro antes de somar `terminal`. Ponteiros nulos ou leituras inválidas interrompem a resolução. O alvo é relido a cada chamada, sem cache.

HP usa RVA 59908640 (0x3922220), `steps: []`, `terminal: 0`, `deref: true` e `int32`. X/Y/Z mantêm suas cadeias verificadas `steps: [0]`; não usam a desreferência final. Arrays vazios continuam sem desreferências de cadeia. Um step zero continua válido: lê o ponteiro e soma zero.

A desreferência opcional ocorre antes de `terminal`. HP usa `steps: []`, `deref: true`, `terminal: 0`; HP max compartilha o RVA e usa `terminal: 4`. Ambos leem o mesmo ponteiro global e somam o deslocamento do campo ao alvo. `deref: false` mantém a semântica anterior de cadeias e endereços diretos.
