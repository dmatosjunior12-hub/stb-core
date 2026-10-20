"""Experimento v3: COPY restrito a Γ (sem COPY dentro do arquivo).

Uma cópia só pode ter a fonte inteiramente dentro de Γ (j + L <= len(Γ)). Não há COPY entre
posições do próprio arquivo. A saída do arquivo é a continuação de Γ, e as distâncias são
medidas a partir dessa posição, então o programa é executado pela VM com um prefixo de REFs
que reconstrói Γ (o prefixo não é cobrado, o receptor já tem Γ).

Variantes (todas com a mesma Γ e o mesmo orçamento):
  G0  genes sem COPY     : REF/RPT de genes, nenhum COPY (stb_v2 com allow_copy=False)
  E0  COPY só em Γ      : COPY com fonte em Γ, sem genes
  E1  COPY só em Γ + genes: COPY com fonte em Γ e REF/RPT de genes (o gene vence quando é ≥ a cópia)

Versões (sempre citar junto dos números):
  v3-guloso : parser guloso
  v3-otimo  : parser ótimo (DP), mesmos custos de stb_v2.optimal

Custo de Γ: min(cru, LZMA2) cobrado em todas as variantes (Γ é usada em todas).
Dois empacotadores: fluxos + zstd-19 (stb_v2.pack_streams) e codificador adaptativo (token_coder).

Uso: python3 bench/exp_gamma_copy.py --parser {guloso,otimo} --families logs [--swap]
Saída: bench/results/gamma_copy_<versão>_<família>[_swap].json (um arquivo por família)
"""

import argparse
import json
import math
import time
from pathlib import Path

import exp_gamma_dict as egd  # verify_vm, mesma convenção de prefixo
import run_benchmark as rb
import stb_codec
import stb_v2
import token_coder

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "data" / "corpus"
OUT = HERE / "results"

GAMMA_CHAIN = 128  # candidatos de Γ examinados por posição (Γ tem muitas repetições de 4 bytes)
VERSIONS = {"guloso": "v3-guloso", "otimo": "v3-otimo"}


class GammaIndex:
    """Índice de todas as posições de Γ com chave de KEY bytes (fontes possíveis de COPY)."""

    def __init__(self, G_bytes: bytes):
        self.G = len(G_bytes)
        self.idx = {}
        for j in range(self.G - stb_v2.KEY + 1):
            self.idx.setdefault(G_bytes[j:j + stb_v2.KEY], []).append(j)

    def copies(self, comb: bytes, p: int, n: int):
        """Lista de (dist, L) com fonte inteiramente em Γ, a partir da posição p dos dados."""
        q = self.G + p
        if n - p < stb_v2.KEY:
            return []
        cands = self.idx.get(comb[q:q + stb_v2.KEY])
        if not cands:
            return []
        out = []
        for j in reversed(cands[-GAMMA_CHAIN:]):
            L = stb_v2._match_len(comb, j, q, min(self.G - j, n - p))
            if L >= stb_v2.KEY:
                out.append((q - j, L))
        return out


def gamma_greedy(data, lib, gidx, comb, use_genes):
    n = len(data)
    ev, p = [], 0
    while p < n:
        gi, glen = -1, 0
        if use_genes and n - p >= 8:
            for cand in lib.index.get(data[p:p + 8], ()):
                g = lib.genes[cand]
                if data.startswith(g, p):
                    gi, glen = cand, len(g)
                    break
        clen, cdist = 0, 0
        for dist, L in gidx.copies(comb, p, n):
            if L > clen:
                clen, cdist = L, dist
        if gi >= 0 and glen >= clen:
            ev.append(("G", gi, glen))
            p += glen
        elif clen >= stb_v2.MIN_COPY:
            ev.append(("C", cdist, clen))
            p += clen
        else:
            ev.append(("L", p, 1))
            p += 1
    return ev


def gamma_optimal(data, lib, gidx, comb, use_genes):
    """DP com os mesmos custos de stb_v2._optimal_events; arestas de COPY só com fonte em Γ."""
    n = len(data)
    INF = float("inf")
    cost = [INF] * (n + 1)
    back = [None] * (n + 1)
    cost[0] = 0.0
    for p in range(n):
        c = cost[p]
        if c == INF:
            continue
        if c + stb_v2.LIT_BITS < cost[p + 1]:
            cost[p + 1] = c + stb_v2.LIT_BITS
            back[p + 1] = ("L", p, 1)
        if use_genes and n - p >= 8:
            for cand in lib.index.get(data[p:p + 8], ()):
                g = lib.genes[cand]
                if data.startswith(g, p):
                    e = p + len(g)
                    if c + stb_v2.GENE_BITS < cost[e]:
                        cost[e] = c + stb_v2.GENE_BITS
                        back[e] = ("G", cand, len(g))
                    break  # lista ordenada do mais longo para o mais curto
        for dist, Lmax in gidx.copies(comb, p, n):
            cb = stb_v2.COPY_BASE_BITS + math.log2(dist)
            lengths = set(range(stb_v2.MIN_COPY, min(Lmax, stb_v2.MIN_COPY + stb_v2.OPT_LEN_SPAN) + 1))
            lengths.add(Lmax)
            for L in lengths:
                if L < stb_v2.MIN_COPY or p + L > n:
                    continue
                bits = c + cb + math.log2(L)
                if bits < cost[p + L]:
                    cost[p + L] = bits
                    back[p + L] = ("C", dist, L)
    ev, p = [], n
    while p > 0:
        e = back[p]
        ev.append(e)
        p -= e[2]
    ev.reverse()
    return ev


def tokens_for(variant, parser, data, lib, gidx, G_bytes):
    if variant == "G0":
        return stb_v2.tokenize(data, lib, "greedy" if parser == "guloso" else "optimal", False)
    comb = G_bytes + data
    use_genes = variant == "E1"
    fn = gamma_greedy if parser == "guloso" else gamma_optimal
    ev = fn(data, lib, gidx, comb, use_genes)
    return stb_v2.events_to_tokens(ev, data)


def run(family, swap, parser):
    train = [p.read_bytes() for p in sorted((CORPUS / family / "train").iterdir())]
    test = [p.read_bytes() for p in sorted((CORPUS / family / "test").iterdir())]
    if swap:
        train, test = test, train
    lib = stb_codec.Library(stb_codec.build_library(train, rb.BUDGET))
    G_bytes = b"".join(lib.genes)
    gidx = GammaIndex(G_bytes)
    G = rb.gamma_charge(lib)[1]
    orig, n = sum(map(len, test)), len(test)
    ov = stb_codec.CAPSID_BYTES * n
    rows = {}
    for variant, label in (("G0", "genes sem COPY"), ("E0", "COPY só em Γ"), ("E1", "COPY só em Γ + genes")):
        s = r = fails = 0
        t0 = time.perf_counter()
        n_genes = len(lib.genes) if variant in ("G0", "E1") else 0
        for d in test:
            toks, R = tokens_for(variant, parser, d, lib, gidx, G_bytes)
            s += len(stb_v2.pack_streams(stb_v2.streams_from_tokens(toks, R)))
            blob = token_coder.encode_tokens(toks, R, n_genes)
            r += len(blob)
            try:
                if token_coder.decode_tokens(blob, n_genes) != (toks, R):
                    fails += 1
                elif not egd.verify_vm(toks, R, lib, G_bytes, d):
                    fails += 1
            except (ValueError, IndexError) as exc:
                print(f"    [falha {variant}] {exc}", flush=True)
                fails += 1
        rows[variant] = {
            "versao": VERSIONS[parser],
            "label": label,
            "rho_streams_payload": orig / (s + ov),
            "rho_rc_payload": orig / (r + ov),
            "rho_streams_amort": orig / (s + ov + G),
            "rho_rc_amort": orig / (r + ov + G),
            "gamma_charge": G,
            "fails": fails,
            "time_s": round(time.perf_counter() - t0, 1),
        }
        x = rows[variant]
        print(f"  {VERSIONS[parser]} {family:8s} {variant} {label:20s} streams={x['rho_streams_amort']:6.3f} "
              f"rc={x['rho_rc_amort']:6.3f} (sem custo: {x['rho_streams_payload']:.3f}/{x['rho_rc_payload']:.3f}) "
              f"falhas={fails} t={x['time_s']}s", flush=True)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parser", choices=("guloso", "otimo"), required=True)
    ap.add_argument("--families", default="logs,codigo,csv,binario")
    ap.add_argument("--swap", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    for fam in args.families.split(","):
        print(f"[{VERSIONS[args.parser]} {fam}{' (swap)' if args.swap else ''}]", flush=True)
        rows = run(fam, args.swap, args.parser)
        name = f"gamma_copy_{VERSIONS[args.parser]}_{fam}{'_swap' if args.swap else ''}.json"
        (OUT / name).write_text(json.dumps(rows, indent=1))
        print("gravado:", OUT / name, flush=True)


if __name__ == "__main__":
    main()
