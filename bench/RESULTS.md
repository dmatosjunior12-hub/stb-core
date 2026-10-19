# Resultados do benchmark STB vs. DEFLATE/zstd

Gerado em 2026-10-19 por `bench/run_benchmark.py`.

Razão de compressão ρ = bytes originais / bytes transmitidos (maior é melhor). Biblioteca/dicionário treinados **somente** nos dados de treino; medidos somente no teste.

- **isolado**: o dicionário/biblioteca é pago em cada arquivo (cada arquivo é transmitido sozinho).
- **amortizado**: dicionário/biblioteca pago uma vez por família (receptor já o possui).
- STB inclui um cabeçalho fixo de 40 bytes por arquivo. A coluna "sem custo de dicionário/Γ" mostra a força do codificador sem a biblioteca, para isolar o efeito da estratégia de literais.

## Resumo

- **Logs reais**: xz-9e ρ = 13.39; zstd-19 ρ = 12.55; zstd-19+dict ρ amortizado = 11.86 (sem custo = 13.30); STB-v2 com Γ ρ amortizado = 9.26 (sem custo = 10.28); STB-v2 sem Γ ρ = 10.17; melhor variante STB sem custo de Γ = 10.28 (STB-v2 com Γ).
- **Código-fonte Python**: xz-9e ρ = 4.02; zstd-19 ρ = 4.04; zstd-19+dict ρ amortizado = 3.47 (sem custo = 4.62); STB-v2 com Γ ρ amortizado = 3.12 (sem custo = 3.60); STB-v2 sem Γ ρ = 3.57; melhor variante STB sem custo de Γ = 3.60 (STB-v2 com Γ).
- **CSV reais**: xz-9e ρ = 5.02; zstd-19 ρ = 4.81; zstd-19+dict ρ amortizado = 4.49 (sem custo = 4.74); STB-v2 com Γ ρ amortizado = 3.73 (sem custo = 3.83); STB-v2 sem Γ ρ = 3.82; melhor variante STB sem custo de Γ = 3.83 (STB-v2 com Γ).
- **Bytecode .pyc**: xz-9e ρ = 2.89; zstd-19 ρ = 2.69; zstd-19+dict ρ amortizado = 2.46 (sem custo = 3.12); STB-v2 com Γ ρ amortizado = 2.42 (sem custo = 2.64); STB-v2 sem Γ ρ = 2.61; melhor variante STB sem custo de Γ = 2.64 (STB-v2 com Γ).

Em 4 de 4 famílias estruturadas, zstd-19 sem dicionário supera todas as variantes do STB mesmo quando o custo de Γ não é contado.
O STB-v2 com Γ supera, na contabilidade amortizada, zstd-19 sem dicionário, zstd-19+dict e a sua própria versão sem Γ em 0 de 4 famílias.
No controle aleatório, todos os métodos ficam em ~1,0, como esperado.

Conclusão limitada a este formato, a este encoder e a este orçamento de Γ. Ver “Ambiente e limitações” e a análise de sensibilidade.

## Logs reais (Loghub, 16 sistemas, split temporal)

Arquivos de teste: 16 · tamanho original: 2218.4 KiB

| Método | ρ isolado | ρ amortizado | ρ sem custo de dicionário/Γ | Falhas de round-trip | Tempo (s) |
|---|---:|---:|---:|---:|---:|
| zlib-9 | 9.621 | 9.621 | 9.621 | 0 | 0.05 |
| xz-9e | 13.392 | 13.392 | 13.392 | 0 | 1.15 |
| zstd-19 | 12.552 | 12.552 | 12.552 | 0 | 1.20 |
| zstd-19+dict | 4.514 | 11.856 | 13.299 | 0 | 0.58 |
| STB | 1.065 | 1.287 | 1.305 | 0 | 0.37 |
| STB+Ω | 2.493 | 4.171 | 4.367 | 0 | 0.78 |
| STB-v2 sem Γ | 10.166 | 10.166 | 10.166 | 0 | 3.30 |
| STB-v2 com Γ | 3.713 | 9.260 | 10.285 | 0 | 4.08 |

Γ: 3162 genes, 110.0 KiB crus, 23.9 KiB cobrados (min(cru, LZMA)). STB (formato atual): 38.0% dos bytes saem de REF, 62.0% são literais crus; média de 25 genes distintos por arquivo. STB+Ω: resíduo comprimido = 7.4% do original.

## Código-fonte Python (stdlib, split por arquivo)

Arquivos de teste: 20 · tamanho original: 470.1 KiB

| Método | ρ isolado | ρ amortizado | ρ sem custo de dicionário/Γ | Falhas de round-trip | Tempo (s) |
|---|---:|---:|---:|---:|---:|
| zlib-9 | 3.827 | 3.827 | 3.827 | 0 | 0.04 |
| xz-9e | 4.020 | 4.020 | 4.020 | 0 | 0.64 |
| zstd-19 | 4.044 | 4.044 | 4.044 | 0 | 0.15 |
| zstd-19+dict | 0.607 | 3.474 | 4.624 | 0 | 0.16 |
| STB | 0.543 | 0.969 | 1.011 | 0 | 1.31 |
| STB+Ω | 0.825 | 2.481 | 2.774 | 0 | 0.43 |
| STB-v2 sem Γ | 3.569 | 3.569 | 3.569 | 0 | 2.39 |
| STB-v2 com Γ | 0.885 | 3.119 | 3.597 | 0 | 2.68 |

Γ: 4010 genes, 110.0 KiB crus, 20.0 KiB cobrados (min(cru, LZMA)). STB (formato atual): 2.6% dos bytes saem de REF, 97.4% são literais crus; média de 9 genes distintos por arquivo. STB+Ω: resíduo comprimido = 23.1% do original.

## CSV reais (seaborn-data, split temporal por linhas)

Arquivos de teste: 22 · tamanho original: 2526.0 KiB

| Método | ρ isolado | ρ amortizado | ρ sem custo de dicionário/Γ | Falhas de round-trip | Tempo (s) |
|---|---:|---:|---:|---:|---:|
| zlib-9 | 4.008 | 4.008 | 4.008 | 0 | 0.30 |
| xz-9e | 5.020 | 5.020 | 5.020 | 0 | 1.46 |
| zstd-19 | 4.806 | 4.806 | 4.806 | 0 | 0.75 |
| zstd-19+dict | 2.107 | 4.485 | 4.740 | 0 | 0.59 |
| STB | 0.892 | 1.019 | 1.025 | 0 | 0.87 |
| STB+Ω | 2.069 | 2.908 | 2.965 | 0 | 1.07 |
| STB-v2 sem Γ | 3.817 | 3.817 | 3.817 | 0 | 7.81 |
| STB-v2 com Γ | 2.454 | 3.730 | 3.825 | 0 | 8.90 |

Γ: 4384 genes, 110.0 KiB crus, 16.8 KiB cobrados (min(cru, LZMA)). STB (formato atual): 4.8% dos bytes saem de REF, 95.2% são literais crus; média de 16 genes distintos por arquivo. STB+Ω: resíduo comprimido = 19.4% do original.

## Bytecode .pyc (stdlib, split por arquivo)

Arquivos de teste: 20 · tamanho original: 554.1 KiB

| Método | ρ isolado | ρ amortizado | ρ sem custo de dicionário/Γ | Falhas de round-trip | Tempo (s) |
|---|---:|---:|---:|---:|---:|
| zlib-9 | 2.551 | 2.551 | 2.551 | 0 | 0.06 |
| xz-9e | 2.890 | 2.890 | 2.890 | 0 | 0.68 |
| zstd-19 | 2.688 | 2.688 | 2.688 | 0 | 0.14 |
| zstd-19+dict | 0.488 | 2.457 | 3.120 | 0 | 0.18 |
| STB | 0.609 | 0.989 | 1.022 | 0 | 0.68 |
| STB+Ω | 0.892 | 2.035 | 2.182 | 0 | 0.49 |
| STB-v2 sem Γ | 2.608 | 2.608 | 2.608 | 0 | 2.77 |
| STB-v2 com Γ | 0.960 | 2.424 | 2.636 | 0 | 3.52 |

Γ: 4177 genes, 110.0 KiB crus, 18.4 KiB cobrados (min(cru, LZMA)). STB (formato atual): 4.5% dos bytes saem de REF, 95.5% são literais crus; média de 16 genes distintos por arquivo. STB+Ω: resíduo comprimido = 35.3% do original.

## Controle: bytes aleatórios (sem estrutura)

Arquivos de teste: 10 · tamanho original: 640.0 KiB

| Método | ρ isolado | ρ amortizado | ρ sem custo de dicionário/Γ | Falhas de round-trip | Tempo (s) |
|---|---:|---:|---:|---:|---:|
| zlib-9 | 1.000 | 1.000 | 1.000 | 0 | 0.01 |
| xz-9e | 0.999 | 0.999 | 0.999 | 0 | 0.41 |
| zstd-19 | 1.000 | 1.000 | 1.000 | 0 | 0.03 |
| zstd-19+dict | 0.368 | 0.853 | 1.000 | 0 | 0.10 |
| STB | 0.999 | 0.999 | 0.999 | 0 | 0.10 |
| STB+Ω | 0.999 | 0.999 | 0.999 | 0 | 0.13 |
| STB-v2 sem Γ | 0.999 | 0.999 | 0.999 | 0 | 1.45 |
| STB-v2 com Γ | 0.999 | 0.999 | 0.999 | 0 | 1.59 |

Γ: 0 genes, 0.0 KiB crus, 0.0 KiB cobrados (min(cru, LZMA)). STB (formato atual): 0.0% dos bytes saem de REF, 100.0% são literais crus; média de 0 genes distintos por arquivo. STB+Ω: resíduo comprimido = 100.0% do original.

## Ambiente e limitações

- Python 3.11.2, zstandard 0.25.0, numpy 2.4.6, linux-x86_64.
- A VM usada pelo STB é um **port Python** de `src/lib.rs` (`bench/stb_vm.py`); o ambiente não tem toolchain Rust. O round-trip é verificado com esse port, não com o binário Rust.
- O encoder é deliberadamente simples (guloso, genes de 16/32/64 bytes). Ele mede o formato atual, não o limite teórico do STB.
- STB (v1) não tem REF para bytes já emitidos; repetições intra-arquivo fora de Γ viram literais. STB-v2 tem COPY (cópia intra-arquivo), que também é extensão do benchmark, não do formato Rust.
- STB-v2: MIN_COPY = 6 e CHAIN = 32 foram fixados antes desta rodada e não foram ajustados pelos resultados de teste. Os fluxos são comprimidos por arquivo, sem contexto compartilhado.
- STB+Ω usa a operação RES, que só existe no port do benchmark (extensão proposta). Ela é a variante compatível com o paper (resíduo classicamente comprimido), não o formato implementado hoje.
- Dados: Loghub (logpai/loghub), seaborn-data e a stdlib do Python instalada no ambiente. Os hashes dos arquivos estão em `bench/data/manifest.json` (gerado, fora do Git).
## Sensibilidade ao orçamento de Γ/dicionário

ρ amortizado com orçamento de 32, 110 e 512 KiB (mesmo treino, mesmo teste). Entre parênteses: ρ sem custo de dicionário/Γ. Γ e dicionário são cobrados comprimidos (min(cru, LZMA)).

| Família | Orçamento | Γ cobrada (KiB) | zstd-19+dict | STB | STB+Ω | STB-v2 |
|---|---:|---:|---:|---:|---:|---:|
| Logs reais | 32 KiB | 8.3 | 12.413 (13.017) | 1.237 (1.242) | 4.980 (5.075) | 9.869 (10.249) |
| Logs reais | 110 KiB | 23.9 | 11.856 (13.299) | 1.287 (1.305) | 4.171 (4.367) | 9.260 (10.285) |
| Logs reais | 512 KiB | 77.5 | 8.775 (13.494) | 1.273 (1.332) | 3.216 (3.624) | 7.583 (10.317) |
| Código-fonte Python | 32 KiB | 7.2 | 4.007 (4.409) | 0.992 (1.007) | 2.766 (2.888) | 3.398 (3.584) |
| Código-fonte Python | 110 KiB | 20.0 | 3.474 (4.624) | 0.969 (1.011) | 2.481 (2.774) | 3.119 (3.597) |
| Código-fonte Python | 512 KiB | 47.7 | 2.570 (4.699) | 0.917 (1.011) | 2.091 (2.654) | 2.645 (3.615) |
| CSV reais | 32 KiB | 5.9 | 4.581 (4.660) | 1.015 (1.018) | 3.092 (3.115) | 3.788 (3.822) |
| CSV reais | 110 KiB | 16.8 | 4.485 (4.740) | 1.019 (1.025) | 2.908 (2.965) | 3.730 (3.825) |
| CSV reais | 512 KiB | 69.2 | 3.855 (4.856) | 1.003 (1.031) | 2.514 (2.700) | 3.474 (3.840) |

O treinador zstd recomenda ~100× o tamanho do dicionário em dados de treino; aqui o treino tem 0,3–2,5 MB por família, o que pode subestimar o zstd+dict.
