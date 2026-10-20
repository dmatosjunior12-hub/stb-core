#!/usr/bin/env python3
"""Opção B: simulação de canal para comparar símbolos de 6 bits e protocolos de transporte.

Duas camadas, medidas separadamente:

1) Símbolo (6 bits, canal binário simétrico com probabilidade q por bit):
   - bruto-6bits:   64 palavras, sem código. Não detecta nem corrige.
   - par-5bits:     32 palavras de paridade par. Detecta 1 erro (vira apagamento).
   - SEC-3bits:     8 palavras, distância mínima 3. Corrige 1 erro por símbolo.
   - G-REC-48:      48 palavras de dados, 16 de controle. Decodifica para a palavra de
                    dados mais próxima (a regra descrita na especificação).
   Métrica: taxa efetiva = taxa do código * (1 - erros - apagamentos), por símbolo.

2) Pacote (CRC detecta qualquer erro; a perda de pacote é o que o transporte vê):
   - Pacote de 8000 bits de canal. Se a taxa interna é r, cada pacote leva r*8000 bits de dados.
   - Perda de pacote P(q): sem código interno, 1 - (1-q)^8000. Com SEC, falha se algum
     símbolo tiver 2 ou mais erros.
   - Transporte: ARQ com repetição seletiva (simulado, janela = 2 BDP, sem controle de
     congestionamento) e fountain idealizado (sobrecarga de 2%, sem retransmissão).
   Métrica: vazão útil (Mbit/s) para entregar um arquivo de 10 MB.

Versões: exp_rede-v1 (este arquivo). Os resultados são idealizados e não substituem medições
em rede real. Nenhuma simulação de TCP ou QUIC está incluída.

Uso: python bench/exp_rede.py
"""

import json
import math
import os
import sys
from collections import deque

import numpy as np

VERSAO = "exp_rede-v1"
POP = np.array([bin(v).count("1") for v in range(64)])
RNG_SEED = 20261020

# Palavras de controle: 16 rótulos fora das 48 palavras de dados (48..63).
PALAVRAS_GREC = np.arange(48)


def _codigo_sec():
    """Código de 8 palavras de 6 bits com distância mínima 3 (busca determinística)."""

    def dfs(sel, inicio):
        if len(sel) == 8:
            return sel
        for c in range(inicio, 64):
            if all(POP[c ^ s] >= 3 for s in sel):
                r = dfs(sel + [c], c + 1)
                if r:
                    return r
        return None

    return dfs([0], 1)


CODIGO_SEC = np.array(_codigo_sec())
assert len(CODIGO_SEC) == 8
assert min(POP[a ^ b] for i, a in enumerate(CODIGO_SEC) for b in CODIGO_SEC[i + 1 :]) >= 3
PARES = np.array([v for v in range(64) if POP[v] % 2 == 0])
assert len(PARES) == 32
# Tabela de decodificação G-REC: palavra de dados mais próxima; empates vão para o menor rótulo.
TABELA_GREC = np.array([v if v < 48 else PALAVRAS_GREC[np.argmin(POP[v ^ PALAVRAS_GREC])] for v in range(64)])


# ------------------------------------------------------------------ teoria de símbolos


def limite_par_hipercubo():
    """Q6 tem emparelhamento perfeito por bit 0: 32 pares. Qualquer conjunto com 48 palavras
    contém pelo menos 48 - 32 = 16 pares inteiros, isto é, palavras a distância 1.
    Por isso um código de 48 palavras não detecta erro de 1 bit em todos os casos."""
    pares = [(v, v ^ 1) for v in range(0, 64, 2)]
    contidos_no_pior_caso = 48 - len(pares)
    return len(pares), contidos_no_pior_caso


# ------------------------------------------------------------------ nível de símbolo


def erros_de_bit(rotulos, q, rng):
    ruido = rng.random((len(rotulos), 6)) < q
    mascara = (ruido * (1 << np.arange(6))).sum(axis=1)
    return rotulos ^ mascara


def simular_simbolos(q, n, rng):
    res = {}
    # bruto-6bits
    s = rng.integers(0, 64, n)
    r = erros_de_bit(s, q, rng)
    res["bruto-6bits"] = dict(taxa=1.0, erro=float(np.mean(r != s)), apagamento=0.0)
    # par-5bits
    s = rng.choice(PARES, n)
    r = erros_de_bit(s, q, rng)
    apag = POP[r] % 2 == 1
    erro = (~apag) & (r != s)
    res["par-5bits"] = dict(taxa=5 / 6, erro=float(np.mean(erro)), apagamento=float(np.mean(apag)))
    # SEC-3bits
    s = rng.choice(CODIGO_SEC, n)
    r = erros_de_bit(s, q, rng)
    dist = POP[r[:, None] ^ CODIGO_SEC[None, :]]
    dec = CODIGO_SEC[np.argmin(dist, axis=1)]
    res["SEC-3bits"] = dict(taxa=3 / 6, erro=float(np.mean(dec != s)), apagamento=0.0)
    # G-REC-48
    s = rng.integers(0, 48, n)
    r = erros_de_bit(s, q, rng)
    dec = TABELA_GREC[r]
    res["G-REC-48"] = dict(taxa=math.log2(48) / 6, erro=float(np.mean(dec != s)), apagamento=0.0)
    for v in res.values():
        v["efetiva"] = v["taxa"] * (1 - v["erro"] - v["apagamento"])
    return res


# ------------------------------------------------------------------ nível de pacote

BITS_PACOTE = 8000
TAXA_CANAL = 10e6  # bit/s
T_SLOT = BITS_PACOTE / TAXA_CANAL  # segundos por pacote de canal
ARQUIVO_BITS = 80e6  # 10 MB
EPS_FOUNTAIN = 0.02


def perda_pacote(esquema, q):
    if esquema == "SEC-3bits":
        falha_simbolo = 1 - (1 - q) ** 6 - 6 * q * (1 - q) ** 5  # 2 ou mais erros no símbolo
        return 1 - (1 - falha_simbolo) ** (BITS_PACOTE / 6)
    return 1 - (1 - q) ** BITS_PACOTE  # sem código interno


def tempo_arq(K, P, rtt_slots, W, rng):
    """Repetição seletiva com janela fixa W, perda iid P. Devolve slots até o receptor ter K pacotes."""
    pend = deque()  # (instante em que o emissor sabe, id, entregue)
    retrans = deque()
    prox_novo = 0
    pendentes = 0
    recebidos = 0
    t = 0
    while True:
        while pend and pend[0][0] == t:
            _, pid, ok = pend.popleft()
            pendentes -= 1
            if not ok:
                retrans.append(pid)
        if pendentes < W:
            if retrans:
                pid = retrans.popleft()
            elif prox_novo < K:
                pid = prox_novo
                prox_novo += 1
            else:
                pid = None
            if pid is not None:
                ok = rng.random() >= P
                pend.append((t + rtt_slots, pid, ok))
                pendentes += 1
                if ok:
                    recebidos += 1
                    if recebidos == K:
                        return t + rtt_slots // 2  # metade do RTT para o último pacote chegar
        t += 1


def tempo_fountain(K, P, rtt_slots):
    slots = K * (1 + EPS_FOUNTAIN) / (1 - P)
    return slots + rtt_slots // 2


def simular_pacotes(rng):
    esquemas = {"base-64 sem código interno": 1.0, "G-REC-48 (sem correção garantida)": math.log2(48) / 6,
                "SEC-3bits (interno, taxa 1/2)": 0.5}
    nomes_interno = {"base-64 sem código interno": "uncoded", "G-REC-48 (sem correção garantida)": "uncoded",
                     "SEC-3bits (interno, taxa 1/2)": "SEC-3bits"}
    linhas = []
    for q in [1e-6, 1e-5, 1e-4, 1e-3]:
        for rtt in [0.05, 0.6]:
            rtt_slots = int(round(rtt / T_SLOT))
            W = max(64, int(2 * TAXA_CANAL * rtt / BITS_PACOTE))
            for nome, taxa in esquemas.items():
                P = perda_pacote(nomes_interno[nome], q)
                K = math.ceil(ARQUIVO_BITS / (taxa * BITS_PACOTE))
                for transporte in ["ARQ-SR", "fountain"]:
                    if transporte == "ARQ-SR":
                        t = tempo_arq(K, P, rtt_slots, W, rng) * T_SLOT
                    else:
                        t = tempo_fountain(K, P, rtt_slots) * T_SLOT
                    linhas.append(dict(q=q, rtt_s=rtt, esquema=nome, transporte=transporte, perda_pacote=P,
                                       K=K, vazao_mbps=ARQUIVO_BITS / t / 1e6, tempo_s=t))
    return linhas


# ------------------------------------------------------------------ execução


def main():
    rng = np.random.default_rng(RNG_SEED)
    print(f"[{VERSAO}] código de 6 bits, teoria:")
    pares, contidos = limite_par_hipercubo()
    print(f"  pares a distância 1 em Q6: {pares}; 48 palavras forçam >= {contidos} pares inteiros.")
    print(f"  palavras no código SEC: {CODIGO_SEC.tolist()}")

    print("\n== Nível de símbolo (N = 300 000 símbolos por ponto) ==")
    simbolos = {}
    for q in [1e-3, 1e-2, 5e-2]:
        r = simular_simbolos(q, 300_000, rng)
        simbolos[str(q)] = r
        print(f"q = {q}")
        print(f"  {'esquema':12s} {'taxa':>7s} {'erro':>9s} {'apagam.':>9s} {'efetiva':>9s}")
        for nome, v in r.items():
            print(f"  {nome:12s} {v['taxa']:7.3f} {v['erro']:9.5f} {v['apagamento']:9.5f} {v['efetiva']:9.4f}")

    print("\n== Nível de pacote (arquivo de 10 MB, canal de 10 Mbit/s, pacote de 8000 bits) ==")
    pacotes = simular_pacotes(rng)
    print(f"  {'q':>7s} {'RTT':>5s} {'esquema':34s} {'transp.':8s} {'P_perda':>8s} {'Mbit/s':>8s}")
    for l in pacotes:
        print(f"  {l['q']:7.0e} {l['rtt_s']:5.2f} {l['esquema']:34s} {l['transporte']:8s} "
              f"{l['perda_pacote']:8.4f} {l['vazao_mbps']:8.3f}")

    out = os.path.join(os.path.dirname(__file__), "results", f"rede_{VERSAO}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"versao": VERSAO, "seed": RNG_SEED, "simbolos": simbolos, "pacotes": pacotes}, f,
                  ensure_ascii=False, indent=1)
    print(f"\nJSON: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
