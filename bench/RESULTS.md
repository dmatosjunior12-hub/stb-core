# Resultados do benchmark STB vs. DEFLATE/zstd

Gerado em 2026-10-19 por `bench/run_benchmark.py`.

Razão de compressão ρ = bytes originais / bytes transmitidos (maior é melhor). Biblioteca/dicionário treinados **somente** nos dados de treino; medidos somente no teste.

- **isolado**: o dicionário/biblioteca é pago em cada arquivo (cada arquivo é transmitido sozinho).
- **amortizado**: dicionário/biblioteca pago uma vez por família (receptor já o possui).
- STB inclui um cabeçalho fixo de 40 bytes por arquivo. A coluna "sem custo de dicionário/Γ" mostra a força do codificador sem a biblioteca, para isolar o efeito da estratégia de literais.

## Resumo

- **Logs reais**: zstd-19 ρ = 12.55; zstd-19+dict ρ = 13.30; STB+Ω ρ = 4.37; STB ρ = 1.30 (ρ sem custo de dicionário/Γ).
- **Código-fonte Python**: zstd-19 ρ = 4.04; zstd-19+dict ρ = 4.62; STB+Ω ρ = 2.77; STB ρ = 1.01 (ρ sem custo de dicionário/Γ).
- **CSV reais**: zstd-19 ρ = 4.81; zstd-19+dict ρ = 4.74; STB+Ω ρ = 2.96; STB ρ = 1.03 (ρ sem custo de dicionário/Γ).
- **Bytecode .pyc**: zstd-19 ρ = 2.69; zstd-19+dict ρ = 3.12; STB+Ω ρ = 2.18; STB ρ = 1.02 (ρ sem custo de dicionário/Γ).

Em 4 de 4 famílias estruturadas, zstd-19 sem dicionário supera as duas variantes do STB mesmo quando o dicionário/Γ não é contado. No controle aleatório, todos os métodos ficam em ~1,0, como esperado.

Conclusão limitada a este formato, a este encoder e a este orçamento de Γ. Ver “Ambiente e limitações” e a análise de sensibilidade.

## Logs reais (Loghub, 16 sistemas, split temporal)

Arquivos de teste: 16 · tamanho original: 2218.4 KiB

| Método | ρ isolado | ρ amortizado | ρ sem custo de dicionário/Γ | Falhas de round-trip | Tempo (s) |
|---|---:|---:|---:|---:|---:|
| zlib-9 | 9.621 | 9.621 | 9.621 | 0 | 0.05 |
| zstd-19 | 12.552 | 12.552 | 12.552 | 0 | 1.21 |
| zstd-19+dict | 1.151 | 8.014 | 13.299 | 0 | 0.63 |
| STB | 0.641 | 1.225 | 1.305 | 0 | 0.36 |
| STB+Ω | 0.978 | 3.590 | 4.367 | 0 | 0.69 |

Γ: 3162 genes, 110.0 KiB. STB (formato atual): 38.0% dos bytes saem de REF, 62.0% são literais crus; média de 25 genes distintos por arquivo. STB+Ω: resíduo comprimido = 7.4% do original.

## Código-fonte Python (stdlib, split por arquivo)

Arquivos de teste: 20 · tamanho original: 470.1 KiB

| Método | ρ isolado | ρ amortizado | ρ sem custo de dicionário/Γ | Falhas de round-trip | Tempo (s) |
|---|---:|---:|---:|---:|---:|
| zlib-9 | 3.827 | 3.827 | 3.827 | 0 | 0.04 |
| zstd-19 | 4.044 | 4.044 | 4.044 | 0 | 0.15 |
| zstd-19+dict | 0.204 | 2.221 | 4.624 | 0 | 0.12 |
| STB | 0.176 | 0.818 | 1.011 | 0 | 1.52 |
| STB+Ω | 0.198 | 1.682 | 2.774 | 0 | 0.54 |

Γ: 4010 genes, 110.0 KiB. STB (formato atual): 2.6% dos bytes saem de REF, 97.4% são literais crus; média de 9 genes distintos por arquivo. STB+Ω: resíduo comprimido = 23.1% do original.

## CSV reais (seaborn-data, split temporal por linhas)

Arquivos de teste: 22 · tamanho original: 2526.0 KiB

| Método | ρ isolado | ρ amortizado | ρ sem custo de dicionário/Γ | Falhas de round-trip | Tempo (s) |
|---|---:|---:|---:|---:|---:|
| zlib-9 | 4.008 | 4.008 | 4.008 | 0 | 0.37 |
| zstd-19 | 4.806 | 4.806 | 4.806 | 0 | 0.89 |
| zstd-19+dict | 0.855 | 3.929 | 4.740 | 0 | 0.60 |
| STB | 0.517 | 0.982 | 1.025 | 0 | 0.91 |
| STB+Ω | 0.772 | 2.626 | 2.965 | 0 | 1.22 |

Γ: 4384 genes, 110.0 KiB. STB (formato atual): 4.8% dos bytes saem de REF, 95.2% são literais crus; média de 16 genes distintos por arquivo. STB+Ω: resíduo comprimido = 19.4% do original.

## Bytecode .pyc (stdlib, split por arquivo)

Arquivos de teste: 20 · tamanho original: 554.1 KiB

| Método | ρ isolado | ρ amortizado | ρ sem custo de dicionário/Γ | Falhas de round-trip | Tempo (s) |
|---|---:|---:|---:|---:|---:|
| zlib-9 | 2.551 | 2.551 | 2.551 | 0 | 0.06 |
| zstd-19 | 2.688 | 2.688 | 2.688 | 0 | 0.13 |
| zstd-19+dict | 0.233 | 1.927 | 3.120 | 0 | 0.09 |
| STB | 0.202 | 0.850 | 1.022 | 0 | 0.68 |
| STB+Ω | 0.226 | 1.523 | 2.182 | 0 | 0.48 |

Γ: 4177 genes, 110.0 KiB. STB (formato atual): 4.5% dos bytes saem de REF, 95.5% são literais crus; média de 16 genes distintos por arquivo. STB+Ω: resíduo comprimido = 35.3% do original.

## Controle: bytes aleatórios (sem estrutura)

Arquivos de teste: 10 · tamanho original: 640.0 KiB

| Método | ρ isolado | ρ amortizado | ρ sem custo de dicionário/Γ | Falhas de round-trip | Tempo (s) |
|---|---:|---:|---:|---:|---:|
| zlib-9 | 1.000 | 1.000 | 1.000 | 0 | 0.01 |
| zstd-19 | 1.000 | 1.000 | 1.000 | 0 | 0.04 |
| zstd-19+dict | 0.368 | 0.853 | 1.000 | 0 | 0.04 |
| STB | 0.999 | 0.999 | 0.999 | 0 | 0.13 |
| STB+Ω | 0.999 | 0.999 | 0.999 | 0 | 0.16 |

Γ: 0 genes, 0.0 KiB. STB (formato atual): 0.0% dos bytes saem de REF, 100.0% são literais crus; média de 0 genes distintos por arquivo. STB+Ω: resíduo comprimido = 100.0% do original.

## Ambiente e limitações

- Python 3.11.2, zstandard 0.25.0, numpy 2.4.6, linux-x86_64.
- A VM usada pelo STB é um **port Python** de `src/lib.rs` (`bench/stb_vm.py`); o ambiente não tem toolchain Rust. O round-trip é verificado com esse port, não com o binário Rust.
- O encoder é deliberadamente simples (guloso, genes de 16/32/64 bytes). Ele mede o formato atual, não o limite teórico do STB.
- O formato não tem REF para bytes já emitidos; repetições intra-arquivo fora de Γ viram literais.
- STB+Ω usa a operação RES, que só existe no port do benchmark (extensão proposta). Ela é a variante compatível com o paper (resíduo classicamente comprimido), não o formato implementado hoje.
- Dados: Loghub (logpai/loghub), seaborn-data e a stdlib do Python instalada no ambiente. Os hashes dos arquivos estão em `bench/data/manifest.json` (gerado, fora do Git).
## Sensibilidade ao orçamento de Γ/dicionário

ρ com orçamento de 32, 110 e 512 KiB (mesmo treino, mesmo teste). Entre parênteses: ρ sem custo de dicionário/Γ.

| Família | Orçamento | Γ real (KiB) | zstd-19+dict | STB | STB+Ω |
|---|---:|---:|---:|---:|---:|
| Logs reais | 32 KiB | 32.0 | 10.959 (13.017) | 1.221 (1.242) | 4.729 (5.075) |
| Logs reais | 110 KiB | 110.0 | 8.014 (13.299) | 1.225 (1.305) | 3.590 (4.367) |
| Logs reais | 512 KiB | 512.0 | 4.232 (13.494) | 1.019 (1.332) | 1.973 (3.624) |
| Código-fonte Python | 32 KiB | 32.0 | 3.391 (4.409) | 0.943 (1.007) | 2.414 (2.888) |
| Código-fonte Python | 110 KiB | 110.0 | 2.221 (4.624) | 0.818 (1.011) | 1.682 (2.774) |
| Código-fonte Python | 512 KiB | 347.1 | 1.289 (4.699) | 0.579 (1.011) | 0.897 (2.654) |
| CSV reais | 32 KiB | 32.0 | 4.400 (4.660) | 1.005 (1.018) | 2.997 (3.115) |
| CSV reais | 110 KiB | 110.0 | 3.929 (4.740) | 0.982 (1.025) | 2.626 (2.965) |
| CSV reais | 512 KiB | 512.0 | 2.447 (4.856) | 0.853 (1.031) | 1.745 (2.700) |

O treinador zstd recomenda ~100× o tamanho do dicionário em dados de treino; aqui o treino tem 0,3–2,5 MB por família, o que pode subestimar o zstd+dict.
