# Resultados com Γ: versões v1, v2 e v3

Gerado por `bench/summarize_gamma.py` a partir de `bench/results/` (ignorado pelo Git).
Reprodução: `exp_gamma_dict.py --parser guloso|otimo` (v1-guloso, v2-otimo),
`exp_gamma_copy.py --parser guloso|otimo` (v3-guloso, v3-otimo), `zstd_baselines.py`.

## Versões

- **v1-guloso**: janela de Γ + COPY dentro do arquivo, parser guloso.
- **v2-otimo**: a mesma janela, parser ótimo (DP).
- **v3-guloso / v3-otimo**: COPY só com fonte inteiramente em Γ (sem COPY dentro do arquivo); genes sem COPY (G0) também medidos.

Variantes: A genes + COPY intra; B janela + COPY intra (sem REF); C janela + COPY intra + REF; D sem Γ;
E0 COPY só em Γ; E1 COPY só em Γ + REF; G0 genes sem COPY.

## Leitura

- Nenhuma configuração supera o zstd-19 puro em nenhuma família e divisão. A melhor com Γ e a melhor sem Γ ficam abaixo dele.
- Contra o zstd-19+dicionário (que também paga o dicionário), a melhor configuração com Γ vence em CSV e pyc, usando G0 (genes sem COPY, fluxos). Nos logs e no código, perde: 8% e 0,6%.
- A configuração "D sem Γ" não paga Γ nem dicionário. Por isso ela é comparada ao zstd-19 puro, e não ao zstd-19+dicionário.
- COPY só em Γ (E0/E1) perde para genes sem COPY nos fluxos, em todas as famílias e nas duas divisões. Com o codificador adaptativo também fica abaixo da melhor configuração em todas as famílias.

## Divisão normal

| Família | zstd-19 | zstd-19+dict | melhor com Γ (vs zstd-19+dict) | melhor sem Γ (vs zstd-19) |
|---|---|---|---|---|
| logs | 12.552 | 11.856 | v3-otimo · G0 genes sem COPY · fluxos · 10.860 (-8.4%) | v2-otimo · D sem Γ · fluxos · 11.606 (-7.5%) |
| codigo | 4.044 | 3.474 | v2-otimo · C dict+genes · rc · 3.452 (-0.6%) | v2-otimo · D sem Γ · rc · 3.876 (-4.1%) |
| csv | 4.806 | 4.485 | v3-guloso · G0 genes sem COPY · fluxos · 4.544 (+1.3%) | v2-otimo · D sem Γ · rc · 4.363 (-9.2%) |
| binario | 2.688 | 2.457 | v3-otimo · G0 genes sem COPY · fluxos · 2.572 (+4.7%) | v2-otimo · D sem Γ · fluxos · 2.644 (-1.6%) |

Melhor de cada grupo (ρ amortizado; % em relação ao zstd-19+dict):

| Família | Grupo | Versão · configuração · empacotador | ρ | falhas |
|---|---|---|---|---|
| logs | A genes + COPY intra | v2-otimo · A genes · rc · 10.537 (-11.1%) | 10.537 | 0 |
| logs | B janela Γ + COPY intra | v2-otimo · B dict · fluxos · 10.661 (-10.1%) | 10.661 | 0 |
| logs | C janela Γ + COPY intra + genes | v2-otimo · C dict+genes · rc · 10.642 (-10.2%) | 10.642 | 0 |
| logs | E0 COPY só em Γ | v3-otimo · E0 COPY só em Γ · fluxos · 6.004 (-49.4%) | 6.004 | 0 |
| logs | E1 COPY só em Γ + genes | v3-otimo · E1 COPY só em Γ + genes · fluxos · 6.828 (-42.4%) | 6.828 | 0 |
| logs | G0 genes sem COPY | v3-otimo · G0 genes sem COPY · fluxos · 10.860 (-8.4%) | 10.860 | 0 |
| codigo | A genes + COPY intra | v2-otimo · A genes · rc · 3.393 (-2.3%) | 3.393 | 0 |
| codigo | B janela Γ + COPY intra | v2-otimo · B dict · rc · 3.419 (-1.6%) | 3.419 | 0 |
| codigo | C janela Γ + COPY intra + genes | v2-otimo · C dict+genes · rc · 3.452 (-0.6%) | 3.452 | 0 |
| codigo | E0 COPY só em Γ | v3-otimo · E0 COPY só em Γ · fluxos · 2.495 (-28.2%) | 2.495 | 0 |
| codigo | E1 COPY só em Γ + genes | v3-otimo · E1 COPY só em Γ + genes · fluxos · 2.541 (-26.9%) | 2.541 | 0 |
| codigo | G0 genes sem COPY | v3-otimo · G0 genes sem COPY · fluxos · 3.241 (-6.7%) | 3.241 | 0 |
| csv | A genes + COPY intra | v2-otimo · A genes · rc · 4.269 (-4.8%) | 4.269 | 0 |
| csv | B janela Γ + COPY intra | v2-otimo · B dict · rc · 4.243 (-5.4%) | 4.243 | 0 |
| csv | C janela Γ + COPY intra + genes | v2-otimo · C dict+genes · rc · 4.269 (-4.8%) | 4.269 | 0 |
| csv | E0 COPY só em Γ | v3-otimo · E0 COPY só em Γ · fluxos · 3.682 (-17.9%) | 3.682 | 0 |
| csv | E1 COPY só em Γ + genes | v3-otimo · E1 COPY só em Γ + genes · fluxos · 3.921 (-12.6%) | 3.921 | 0 |
| csv | G0 genes sem COPY | v3-guloso · G0 genes sem COPY · fluxos · 4.544 (+1.3%) | 4.544 | 0 |
| binario | A genes + COPY intra | v2-otimo · A genes · fluxos · 2.455 (-0.1%) | 2.455 | 0 |
| binario | B janela Γ + COPY intra | v2-otimo · B dict · fluxos · 2.475 (+0.7%) | 2.475 | 0 |
| binario | C janela Γ + COPY intra + genes | v2-otimo · C dict+genes · fluxos · 2.474 (+0.7%) | 2.474 | 0 |
| binario | E0 COPY só em Γ | v3-otimo · E0 COPY só em Γ · fluxos · 2.255 (-8.2%) | 2.255 | 0 |
| binario | E1 COPY só em Γ + genes | v3-otimo · E1 COPY só em Γ + genes · fluxos · 2.296 (-6.6%) | 2.296 | 0 |
| binario | G0 genes sem COPY | v3-otimo · G0 genes sem COPY · fluxos · 2.572 (+4.7%) | 2.572 | 0 |

## Divisão swap

| Família | zstd-19 | zstd-19+dict | melhor com Γ (vs zstd-19+dict) | melhor sem Γ (vs zstd-19) |
|---|---|---|---|---|
| logs | 12.567 | 11.792 | v3-otimo · G0 genes sem COPY · fluxos · 10.748 (-8.8%) | v2-otimo · D sem Γ · rc · 11.705 (-6.9%) |
| codigo | 4.035 | 3.476 | v2-otimo · C dict+genes · rc · 3.449 (-0.8%) | v2-otimo · D sem Γ · rc · 3.885 (-3.7%) |
| csv | 4.573 | 4.288 | v3-guloso · G0 genes sem COPY · fluxos · 4.345 (+1.3%) | v2-otimo · D sem Γ · rc · 4.152 (-9.2%) |
| binario | 2.578 | 2.412 | v3-otimo · G0 genes sem COPY · fluxos · 2.503 (+3.8%) | v2-otimo · D sem Γ · fluxos · 2.537 (-1.6%) |

Melhor de cada grupo (ρ amortizado; % em relação ao zstd-19+dict):

| Família | Grupo | Versão · configuração · empacotador | ρ | falhas |
|---|---|---|---|---|
| logs | A genes + COPY intra | v2-otimo · A genes · rc · 10.611 (-10.0%) | 10.611 | 0 |
| logs | B janela Γ + COPY intra | v2-otimo · B dict · rc · 10.702 (-9.2%) | 10.702 | 0 |
| logs | C janela Γ + COPY intra + genes | v2-otimo · C dict+genes · rc · 10.744 (-8.9%) | 10.744 | 0 |
| logs | E0 COPY só em Γ | v3-otimo · E0 COPY só em Γ · fluxos · 5.889 (-50.1%) | 5.889 | 0 |
| logs | E1 COPY só em Γ + genes | v3-otimo · E1 COPY só em Γ + genes · fluxos · 6.651 (-43.6%) | 6.651 | 0 |
| logs | G0 genes sem COPY | v3-otimo · G0 genes sem COPY · fluxos · 10.748 (-8.8%) | 10.748 | 0 |
| codigo | A genes + COPY intra | v2-otimo · A genes · rc · 3.399 (-2.2%) | 3.399 | 0 |
| codigo | B janela Γ + COPY intra | v2-otimo · B dict · rc · 3.418 (-1.7%) | 3.418 | 0 |
| codigo | C janela Γ + COPY intra + genes | v2-otimo · C dict+genes · rc · 3.449 (-0.8%) | 3.449 | 0 |
| codigo | E0 COPY só em Γ | v3-otimo · E0 COPY só em Γ · fluxos · 2.568 (-26.1%) | 2.568 | 0 |
| codigo | E1 COPY só em Γ + genes | v3-otimo · E1 COPY só em Γ + genes · fluxos · 2.606 (-25.0%) | 2.606 | 0 |
| codigo | G0 genes sem COPY | v3-otimo · G0 genes sem COPY · fluxos · 3.293 (-5.3%) | 3.293 | 0 |
| csv | A genes + COPY intra | v2-otimo · A genes · rc · 4.066 (-5.2%) | 4.066 | 0 |
| csv | B janela Γ + COPY intra | v2-otimo · B dict · rc · 4.046 (-5.6%) | 4.046 | 0 |
| csv | C janela Γ + COPY intra + genes | v2-otimo · C dict+genes · rc · 4.066 (-5.2%) | 4.066 | 0 |
| csv | E0 COPY só em Γ | v3-otimo · E0 COPY só em Γ · fluxos · 3.558 (-17.0%) | 3.558 | 0 |
| csv | E1 COPY só em Γ + genes | v3-otimo · E1 COPY só em Γ + genes · fluxos · 3.801 (-11.4%) | 3.801 | 0 |
| csv | G0 genes sem COPY | v3-guloso · G0 genes sem COPY · fluxos · 4.345 (+1.3%) | 4.345 | 0 |
| binario | A genes + COPY intra | v2-otimo · A genes · fluxos · 2.377 (-1.4%) | 2.377 | 0 |
| binario | B janela Γ + COPY intra | v2-otimo · B dict · fluxos · 2.395 (-0.7%) | 2.395 | 0 |
| binario | C janela Γ + COPY intra + genes | v2-otimo · C dict+genes · rc · 2.398 (-0.6%) | 2.398 | 0 |
| binario | E0 COPY só em Γ | v3-otimo · E0 COPY só em Γ · fluxos · 2.201 (-8.7%) | 2.201 | 0 |
| binario | E1 COPY só em Γ + genes | v3-otimo · E1 COPY só em Γ + genes · fluxos · 2.234 (-7.4%) | 2.234 | 0 |
| binario | G0 genes sem COPY | v3-otimo · G0 genes sem COPY · fluxos · 2.503 (+3.8%) | 2.503 | 0 |

