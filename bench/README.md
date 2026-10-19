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
| `stb_vm.py` | Port Python da VM do `src/lib.rs` + extensões `RES` e `COPY` (só no benchmark) |
| `stb_v2.py` | STB-v2: tokenização (LIT/REF/RPT/COPY/STP), fluxos separados e empacotamento |
| `run_benchmark.py` | Executa métodos, verifica round-trip, gera `RESULTS.md` |
| `test_bench.py` | Testes do port e do encoder |

## Métodos

| Método | O que é | Custo contado |
|---|---|---|
| zlib-9 | DEFLATE nível 9 | arquivo comprimido |
| xz-9e | xz/LZMA2 preset 9 extremo | arquivo comprimido |
| zstd-19 | zstd nível 19, sem dicionário | arquivo comprimido |
| zstd-19+dict | zstd nível 19 com dicionário treinado (110 KiB) | arquivo + dicionário comprimido |
| STB | encoder do benchmark, formato atual do STB-Core (literais crus no programa) | programa + cabeçalho de 40 B + Γ comprimida |
| STB+Ω | mesmo encoder; literais vão para um resíduo Ω comprimido com zstd-19 e o programa usa `RES n` | programa + Ω + cabeçalho + Γ comprimida |
| STB-v2 sem Γ | tokens LIT/REF/RPT/COPY/STP; COPY copia de bytes já emitidos; cada fluxo (T, LEN, CNT, GID, DIST, R) vai com o melhor entre cru, LZMA2 raw 9e e zstd-19 | fluxos + cabeçalho |
| STB-v2 com Γ | mesmo, com a biblioteca Γ do treino | fluxos + cabeçalho + Γ comprimida |

Custo de Γ e de dicionário = `min(bytes crus, LZMA2 raw 9e)`, aplicado igualmente ao dicionário
zstd e a Γ. Antes desta rodada o dicionário zstd era cobrado cru, o que tornava o zstd+dict
menos favorável na contabilidade amortizada (ρ logs 8,01 antes; 11,86 agora).

`STB-v2` usa `COPY` e a separação em fluxos. Nenhum dos dois existe em `src/lib.rs`: são extensões
do benchmark, e o formato Rust não os implementa.

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
- **STB v1 sem REF para a saída já emitida.** Repetições dentro do próprio arquivo que não
  estão em Γ viram literais. STB-v2 corrige isso com COPY, mas o parser é guloso e os fluxos são
  comprimidos por arquivo, sem contexto compartilhado. Mesmo assim, zstd-19 ainda vence.
- **MIN_COPY = 6 fixado a priori.** Uma varredura pós-fato nos arquivos de teste (MIN_COPY 4/6/8/12)
  mostrou que valores maiores comprimem um pouco melhor, mas não chegam ao zstd-19. Essa varredura
  não alterou os números da tabela.
- **Treino pequeno para o zstd.** Os splits têm 0,3–2,5 MB por família; o treinador zstd
  recomenda cerca de 100× o tamanho do dicionário. O zstd+dict pode estar subestimado.
- **Dados.** Logs do Loghub (16 sistemas, split temporal), CSVs do seaborn-data (split temporal
  por linhas), código e `.pyc` da stdlib do Python instalado (split por arquivo), e um controle
  aleatório.
