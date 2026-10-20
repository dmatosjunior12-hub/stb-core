# Formato de fluxos fluxos-v1 (tokens G0)

Versão do formato: **fluxos-v1**, byte de versão `0x01`.
Implementação de referência: `bench/stb_stream_format.py`. Avaliação: `bench/eval_stream_format.py`.

Esta é uma extensão do benchmark. Não faz parte de `src/lib.rs`. O formato serializa somente os
tokens da configuração **G0**: genes de Γ, sem COPY, com parser ótimo (`stb_v2.tokenize(..., "optimal", allow_copy=False)`).

## 1. Escopo

- Tokens aceitos: `LIT n`, `REF g`, `RPT c g`, `STP`. Qualquer `COPY` é rejeitado na codificação.
- O decodificador precisa de `n_genes` (número de genes de Γ). A largura do bit-tree de GID vem daí. O receptor já tem Γ.
- A lista de tokens termina com exatamente um `STP`.
- Fora do escopo: COPY/DIST (exige nova versão do formato), Γ, o cabeçalho do capsídeo, e o resíduo Ω.

## 2. Layout

```
arquivo := versão (1 B = 0x01)  registro_T  registro_LEN  registro_CNT  registro_GID  registro_R
registro := método (1 B)  n (varint)  tamanho_do_corpo (varint)  corpo
varint  := LEB128 sem sinal (stb_v2.put_varint)
```

Não há contagem de registros, nem tamanho total: os cinco registros são sempre nessa ordem. O fim do arquivo
é o fim do registro R, e qualquer byte sobrando é erro.

## 3. Significado dos fluxos

| Fluxo | Itens (n) | Valor de cada item |
|---|---|---|
| T | um por token | tipo: 0 = LIT, 1 = REF, 2 = RPT, 4 = STP (3 é COPY, proibido) |
| LEN | um por LIT | comprimento da corrida de literais, ≥ 1 |
| CNT | um por RPT | contagem de repetições, ≥ `RPT_MIN` (3) |
| GID | um por REF e um por RPT | id do gene; na ordem dos tokens; `0 ≤ g < n_genes` |
| R | um por byte | bytes literais, na ordem dos LIT; soma dos LEN = `n` |

A reconstrução percorre T. Cada LIT consome um LEN, cada REF consome um GID, cada RPT consome um CNT e um GID.
Ao final, todos os fluxos precisam estar consumidos exatamente.

## 4. Métodos de corpo

| Método | Corpo | Aplica-se a |
|---|---|---|
| 0 cru | bytes (T, R) ou varints (LEN, CNT, GID) | todos |
| 1 LZMA2 | `lzma.compress(FORMAT_RAW, LZMA_FILTERS)`, preset 9e | todos |
| 2 zstd-19 | `zstandard.ZstdCompressor(level=19)` | todos |
| 3 rc | codificador binário adaptativo (`bench/rc.py`), com modelo próprio do fluxo | T, LEN, CNT, GID |

Modelos do método 3 (um por fluxo, sem cabeçalho de modelo):

- **T**: `TreeModel(3)` com contexto = tipo anterior (5 contextos).
- **LEN**: `IntModel` sobre `valor − 1` (Elias-gamma adaptativo).
- **CNT**: `IntModel` sobre `valor − RPT_MIN`.
- **GID**: `TreeModel(b)` com `b = max(1, ⌈log2 n_genes⌉)`.

Regra do codificador: para cada fluxo, escolhe o método de menor corpo. Empate: prevalece o método de
número menor (cru < LZMA2 < zstd-19 < rc). R não usa rc. Fluxos vazios usam o método 0 com corpo vazio.

## 5. Validação na decodificação

Qualquer um destes casos levanta `ValueError`:

- versão diferente de `0x01`;
- arquivo truncado, incluindo varint incompleto;
- bytes sobrando após R;
- `n` acima de `MAX_ITEMS` (2²⁶);
- falha de LZMA ou zstd (convertida em `ValueError`);
- tamanho descomprimido de T ou R diferente de `n`;
- tipo de token fora de {0, 1, 2, 4};
- id de gene fora de `[0, n_genes)`;
- contagens de LEN, CNT ou GID diferentes do que T pede;
- soma dos LEN diferente de `len(R)`;
- T sem um único `STP` no fim.

## 6. Integridade: digest do cabeçalho

O fluxos-v1 não tem checksum próprio. A integridade fica no capsídeo (40 B, já contados no benchmark):
`magic (4) + versão (1) + digest (32) + flags (3)`. O digest é

    digest = SHA-256( bytecode(tokens) ‖ R )

e deve ser conferido **antes** da execução, como no Rust (`Capsid::compute_checksum`). No Rust o checksum cobre só o bytecode, porque lá não há literais fora dele. Aqui o R entra no digest.
O digest precisa cobrir R. O bytecode carrega só o comprimento dos literais (`RES n`), não o conteúdo.
Sem R, uma inversão nos bytes literais passaria em silêncio. Isso foi medido: com digest só sobre o bytecode,
80 de 400 inversões de bit eram aceitas; com digest sobre bytecode ‖ R, nenhuma.

Os testes (`StreamFormatTests`) verificam que toda inversão de bit de um arquivo de exemplo é rejeitada
por `ValueError` ou pelo digest.

## 7. Resultados (G0, parser ótimo, 4 famílias, duas divisões)

ρ amortizado (40 B por arquivo e Γ cobrada). "Legado" é `stb_v2.pack_streams` (6 fluxos).
Os valores do legado batem com a linha G0-ótimo de `RESULTS_GAMMA.md`.

| Família | Divisão | Legado | fluxos-v1 | Ganho |
|---|---|---|---|---|
| logs | normal | 10,860 | 10,877 | +0,16% |
| código | normal | 3,241 | 3,285 | +1,34% |
| CSV | normal | 4,516 | 4,562 | +1,01% |
| pyc (binario) | normal | 2,572 | 2,592 | +0,79% |
| logs | swap | 10,748 | 10,765 | +0,16% |
| código | swap | 3,293 | 3,326 | +1,00% |
| CSV | swap | 4,306 | 4,365 | +1,37% |
| pyc (binario) | swap | 2,503 | 2,522 | +0,78% |

Verificação: 0 falhas de decodificação, 0 de digest e 0 de VM, em todos os arquivos de todas as 8 execuções.

Métodos escolhidos (divisão normal, por arquivo):

| Família | T | LEN | CNT | GID | R |
|---|---|---|---|---|---|
| logs | rc 7, zstd 8, LZMA 1 | LZMA 10, zstd 4, rc 2 | cru 16 | LZMA 11, rc 3, zstd 2 | LZMA 15, zstd 1 |
| código | rc 20 | rc 17, cru 3 | cru 20 | rc 20 | LZMA 8, zstd 12 |
| CSV | cru 17, rc 5 | cru 17, LZMA 2, rc 3 | cru 22 | cru 17, rc 5 | LZMA 14, zstd 8 |
| pyc | rc 20 | rc 20 | cru 20 | rc 19, LZMA 1 | LZMA 20 |

Leitura: o ganho vem quase todo de T, LEN e GID (método rc em código e pyc). R, que é 85–90% do tamanho,
é empacotado com LZMA2 ou zstd-19 em todos os casos.

## 8. Alternativas medidas e descartadas

- **IDs de gene ordenados por frequência no treino** (com varint): piora o fluxo GID em 0,1% a 0,3% (código e binário) e fica igual no CSV. Descartado.
- **rc de ordem 1 para R**: 37% a 177% maior que LZMA2 (no código, 170 KB contra 111 KB), porque R tem repetições longas. Descartado.
- **LZMA2 com lc=0, pb=0 como método extra**: −0,5% em R no código, +0,1% no pyc. Não compensa o método a mais.
- **GID com contexto do gene anterior (ordem 1)**: não supera o melhor método por fluxo em nenhuma família (nos logs, 12,4 KB contra 11,8 KB do LZMA2). Descartado.

## 9. Limitações

- O formato não é implementado em Rust. A porta exige definir o layout no lado Rust e testar com o VM real.
- Não há checksum dentro do fluxo. Sem o digest do capsídeo, uma corrupção pode decodificar para outro programa.
- Um fluxo rc com `n` grande e corpo pequeno pode demorar na decodificação (símbolos muito prováveis consomem
  poucos bits). `MAX_ITEMS` limita a contagem, não o tempo.
- O ganho sobre o legado é de 0,2% a 1,4%. A decisão do formato não muda o quadro frente ao zstd: G0 continua
  abaixo do zstd-19+dicionário em logs e código, e acima dele em CSV e pyc (ver `RESULTS_GAMMA.md`).
