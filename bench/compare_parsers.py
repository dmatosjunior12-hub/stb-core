"""Compara parsers (greedy, lazy, optimal) com e sem COPY, com e sem Γ.

Uso:  python3 bench/compare_parsers.py [--swap] [--families logs,codigo,csv,binario]

--swap inverte treino e teste (teste de sensibilidade ao split). Saída: bench/results/parsers[_swap].json
e uma tabela em texto. Não altera RESULTS.md nem o README.

Contabilidade: custo = fluxos comprimidos + cabeçalho fixo (40 B) por arquivo [+ Γ comprimida
(min(cru, LZMA)), amortizada uma vez por família]. Round-trip verificado pela VM em todos os arquivos.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import stb_codec
import stb_v2
import stb_vm
import run_benchmark as rb

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "data" / "corpus"
OUT = HERE / "results"
PARSERS = ("greedy", "lazy", "optimal")


def load(family, split):
    return [p.read_bytes() for p in sorted((CORPUS / family / split).iterdir())]


def run_family(family, swap):
    train, test = load(family, "train"), load(family, "test")
    if swap:
        train, test = test, train
    orig = sum(map(len, test))
    n = len(test)
    lib = stb_codec.Library(stb_codec.build_library(train, rb.BUDGET))
    G_raw, G = rb.gamma_charge(lib)
    empty = stb_codec.Library([])
    rows = []
    for allow_copy in (True, False):
        for parser in PARSERS:
            t0 = time.perf_counter()
            sizes, fails, ntok = [], 0, 0
            sizes_g = []
            for d in test:
                toks, R = stb_v2.tokenize(d, lib, parser, allow_copy)
                blob = stb_v2.pack_streams(stb_v2.streams_from_tokens(toks, R))
                ntok += len(toks)
                try:
                    s2 = stb_v2.unpack_streams(blob)
                    prog = stb_v2.bytecode_from_tokens(stb_v2.tokens_from_streams(s2), lib)
                    if stb_vm.execute(prog, lib.payload, residue=s2["R"]) != d:
                        fails += 1
                except (stb_vm.VmError, ValueError, IndexError) as exc:
                    print(f"    [falha] {family} {parser}: {exc}")
                    fails += 1
                sizes.append(len(blob))
            el = time.perf_counter() - t0
            payload = sum(sizes) + stb_codec.CAPSID_BYTES * n
            # sem Γ: mesma codificação sem biblioteca (genes não usados viram literais)
            t1 = time.perf_counter()
            sizes0 = []
            for d in test:
                toks, R = stb_v2.tokenize(d, empty, parser, allow_copy)
                sizes0.append(len(stb_v2.pack_streams(stb_v2.streams_from_tokens(toks, R))))
            payload0 = sum(sizes0) + stb_codec.CAPSID_BYTES * n
            rows.append({
                "copy": allow_copy, "parser": parser, "files": n, "orig": orig,
                "rho_sem_gamma": orig / payload0,
                "rho_com_gamma_amort": orig / (payload + G),
                "rho_com_gamma_iso": orig / (payload + G * n),
                "payload_bytes": payload, "gamma_charged": G, "gamma_raw": G_raw,
                "tokens": ntok, "fails": fails, "time_s": round(el, 2),
                "time_sem_gamma_s": round(time.perf_counter() - t1, 2),
            })
            print(f"  {family:8s} copy={str(allow_copy):5s} {parser:8s} "
                  f"ρ_sem_Γ={orig/payload0:6.3f} ρ_com_Γ(amort)={orig/(payload+G):6.3f} "
                  f"falhas={fails} t={el:.1f}s", flush=True)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--swap", action="store_true")
    ap.add_argument("--families", default="logs,codigo,csv,binario")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    result = {}
    for fam in args.families.split(","):
        print(f"[{fam}{' (swap)' if args.swap else ''}]", flush=True)
        result[fam] = run_family(fam, args.swap)
    name = "parsers_swap.json" if args.swap else "parsers.json"
    (OUT / name).write_text(json.dumps(result, indent=1))
    print("gravado:", OUT / name)


if __name__ == "__main__":
    sys.setrecursionlimit(10000)
    main()
