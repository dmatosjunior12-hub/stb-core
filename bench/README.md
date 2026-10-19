# Benchmark STB vs. DEFLATE/zstd

Implementa o benchmark previsto no roadmap (v0.4): mede o formato STB contra
zlib (DEFLATE) e zstd em dados reais, com a biblioteca/dicionário **contado** no custo
e treinado **somente** nos dados de treino.

Resultados e interpretação: [`RESULTS.md`](RESULTS.md).

## Como rodar

```bash
python3 -m venv .venv-bench
. .venv-bench/bin/activate
pip install -r bench/requirements.txt

python3 bench/build_corpus.py      # baixa Loghub e seaborn-data, monta o corpus (bench/data/)
python3 bench/run_benchmark.py     # gera bench/RESULTS.md e bench/data/results.json
python3 -m unittest discover -s bench -v   # testes do port da VM e do encoder
```

`build_corpus.py` baixa dois repositórios de `codeload.github.com` na primeira execução
e grava o SHA-256 de cada arquivo em `bench/data/manifest.json`. O corpus e os resultados
brutos ficam em `bench/data/`, que está no `.gitignore`.

## Arquivos

| Arquivo | Papel |
|---|---|
| `build_corpus.py` | Monta corpus e splits (treino/teste) das 5 famílias |
| `stb_codec.py` | Construção de Γ (biblioteca de genes) e encoder guloso |
| `stb_vm.py` | Port Python da VM do `src/lib.rs` + extensão `RES` (só no benchmark) |
| `run_benchmark.py` | Executa métodos, verifica round-trip, gera `RESULTS.md` |
| `test_bench.py` | Testes do port e do encoder |

## Métodos

| Método | O que é | Custo contado |
|---|---|---|
| zlib-9 | DEFLATE nível 9 | arquivo comprimido |
| zstd-19 | zstd nível 19, sem dicionário | arquivo comprimido |
| zstd-19+dict | zstd nível 19 com dicionário treinado (110 KiB) | arquivo + dicionário |
| STB | encoder do benchmark, formato atual do STB-Core (literais crus no programa) | programa + cabeçalho de 40 B + Γ |
| STB+Ω | mesmo encoder; literais vão para um resíduo Ω comprimido com zstd-19 e o programa usa `RES n` | programa + Ω + cabeçalho + Γ |

`STB+Ω` depende de uma operação (`RES`, opcode `0x09`) que **não existe em `src/lib.rs`**.
É uma extensão proposta para a variante descrita no paper (resíduo classicamente
comprimido). O campo `compressed_residual` de `TransmissionUnit` existe no código, mas
`transmit()` ainda não o usa.

## Limitações conhecidas

- **Port, não o binário Rust.** O ambiente de desenvolvimento não tinha toolchain Rust. A
  VM foi portada para Python com a mesma semântica e validação; o round-trip é verificado
  com esse port. Rode `cargo test` e compare quando houver toolchain.
- **Encoder simples.** É guloso e usa genes de 16/32/64 bytes. Mede o formato, não um limite
  teórico do STB. Um parser ótimo ou genes de tamanho variável podem mudar os números.
- **Sem REF para a saída já emitida.** Repetições dentro do próprio arquivo que não estão
  em Γ viram literais. Isso provavelmente é a maior lacuna frente ao zstd em logs.
- **Treino pequeno para o zstd.** Os splits têm 0,3–2,5 MB por família; o treinador zstd
  recomenda cerca de 100× o tamanho do dicionário. O zstd+dict pode estar subestimado.
- **Dados.** Logs do Loghub (16 sistemas, split temporal), CSVs do seaborn-data (split temporal
  por linhas), código e `.pyc` da stdlib do Python instalado (split por arquivo), e um controle
  aleatório.
