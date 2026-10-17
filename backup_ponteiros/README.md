# Backup de ponteiros e offsets — 17/10/2026

- offsets.snapshot.json: cópia integral do offsets.json na data do backup; não é carregada automaticamente.
- offsets.schema.json: contrato da cópia.
- pokebot-xyz.ct: tabela CE histórica, sem nova validação.
- evidencias/: resultados locais de scans e validações; excluídos do GitHub.
- Consulte ../CONTEXTO_RETOMADA.md para campos validados, candidatos rejeitados e pendências.

Restaurar somente após comparar versões e guardar a configuração atual. Endereços de heap e PIDs não sobrevivem necessariamente ao restart. O backup não certifica a versão atual do cliente.
