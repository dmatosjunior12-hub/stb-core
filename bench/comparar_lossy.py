#!/usr/bin/env python3
"""Compara as versões do experimento com perda (lê os JSONs de bench/results/).

Uso: python bench/comparar_lossy.py
Imprime, por conjunto e por alvo de SSIM, a média geométrica de bpp de cada versão do STB
contra as referências, e a contagem de vitórias por imagem entre v2-rd e v1.
"""

import json
import math
import os

from exp_lossy import TARGETS, contagens, melhor_em

RES = os.path.join(os.path.dirname(__file__), "results")
ARQUIVOS = {
    ("naturais", "stb-lossy-v1"): "lossy_stb-lossy-v1_naturais.json",
    ("naturais", "stb-lossy-v2-rd"): "lossy_stb-lossy-v2-rd_naturais.json",
    ("estruturadas", "stb-lossy-v1"): "lossy_stb-lossy-v1_estruturadas.json",
    ("estruturadas", "stb-lossy-v2-rd"): "lossy_stb-lossy-v2-rd_estruturadas.json",
}


def carregar(conjunto, versao):
    caminho = os.path.join(RES, ARQUIVOS[(conjunto, versao)])
    if not os.path.exists(caminho):
        return None
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)["resultados"]


def fmt(c):
    if not c or not c["n"]:
        return "—"
    return f"{c['melhor']}/{c['empate']}/{c['pior']} (geo {c['geo']:.3f})"


def main():
    for conjunto in ("naturais", "estruturadas"):
        for versao in ("stb-lossy-v1", "stb-lossy-v2-rd"):
            r = carregar(conjunto, versao)
            if r is None:
                print(f"[faltando] {conjunto} {versao}")
                continue
            print(f"\n## {conjunto}: {versao}")
            print("| alvo | vs JPEG | vs WebP | vs Q+xz |")
            print("|---|---|---|---|")
            for alvo in TARGETS:
                print(
                    f"| {alvo} | {fmt(contagens(r, versao, 'JPEG', alvo))} | "
                    f"{fmt(contagens(r, versao, 'WebP', alvo))} | {fmt(contagens(r, versao, 'Q+xz', alvo))} |"
                )
        v1 = carregar(conjunto, "stb-lossy-v1")
        rd = carregar(conjunto, "stb-lossy-v2-rd")
        if v1 and rd:
            print(f"\n## {conjunto}: v2-rd contra v1 (melhor/empate/pior do v2-rd)")
            print("| alvo | contagem | geo |")
            print("|---|---|---|")
            for alvo in TARGETS:
                pares = _pares_por_imagem(rd, v1, alvo)
                print(f"| {alvo} | {pares['txt']} | {pares['geo']} |")


def _pares_por_imagem(rd, v1, alvo):
    vit = emp = der = 0
    razoes = []
    for nome in rd:
        a = melhor_em(rd[nome], "stb-lossy-v2-rd", alvo)
        b = melhor_em(v1[nome], "stb-lossy-v1", alvo)
        if not (a and b):
            continue
        r = a["bpp"] / b["bpp"]
        razoes.append(r)
        if r < 0.999:
            vit += 1
        elif r > 1.001:
            der += 1
        else:
            emp += 1
    geo = math.exp(sum(math.log(x) for x in razoes) / len(razoes)) if razoes else None
    return {
        "txt": f"{vit}/{emp}/{der} (n={len(razoes)})",
        "geo": f"{geo:.3f}" if geo else "—",
    }


if __name__ == "__main__":
    main()
