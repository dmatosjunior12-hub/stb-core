"""Avalia o codificador adaptativo (token_coder) contra o empacotador de fluxos (stb_v2.pack_streams).

Para cada família, parser e configuração (COPY ligado/desligado, com/sem Γ):
  - tamanho com o empacotador atual (fluxos + LZMA/zstd por fluxo);
  - tamanho com o codificador adaptativo;
  - decodificação e execução pela VM: o programa reconstruído tem de dar o arquivo original.
Contabilidade igual à de compare_parsers.py: cabeçalho de 40 B por arquivo; Γ comprimida amortizada.

Uso:  python3 bench/eval_token_coder.py [--swap] [--families logs,codigo,csv,binario]
Saída: bench/results/token_coder[_swap].json
"""

import argparse
import json
import sys
import time
from pathlib import Path

import stb_codec
import stb_v2
import stb_vm
import token_coder
import run_benchmark as rb

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "data" / "corpus"
OUT = HERE / "results"


def load(family, split):
    return [p.read_bytes() for p in sorted((CORPUS / family / split).iterdir())]


def evaluate(test, lib, parser, allow_copy):
    n_genes = len(lib.genes)
    streams_sz = rc_sz = 0
    fails = 0
    t0 = time.perf_counter()
    for d in test:
        toks, R = stb_v2.tokenize(d, lib, parser, allow_copy)
        streams_sz += len(stb_v2.pack_streams(stb_v2.streams_from_tokens(toks, R)))
        blob = token_coder.encode_tokens(toks, R, n_genes)
        rc_sz += len(blob)
        try:
            t2, R2 = token_coder.decode_tokens(blob, n_genes)
            if t2 != toks or R2 != R:
                fails += 1
                continue
            prog = stb_v2.bytecode_from_tokens(t2, lib)
            if stb_vm.execute(prog, lib.payload, residue=R2) != d:
                fails += 1
        except (stb_vm.VmError, ValueError, IndexError) as exc:
            print(f"    [falha] {exc}")
            fails += 1
    return streams_sz, rc_sz, fails, time.perf_counter() - t0


def run_family(family, swap):
    train, test = load(family, "train"), load(family, "test")
    if swap:
        train, test = test, train
    orig, n = sum(map(len, test)), len(test)
    lib = stb_codec.Library(stb_codec.build_library(train, rb.BUDGET))
    G = rb.gamma_charge(lib)[1]
    empty = stb_codec.Library([])
    rows = []
    for label, L in (("com Γ", lib), ("sem Γ", empty)):
        for allow_copy in (False, True):
            for parser in ("greedy", "optimal"):
                if parser == "optimal" and not allow_copy and label == "sem Γ":
                    continue  # sem Γ e sem COPY o parser ótimo não tem efeito
                s, r, fails, el = evaluate(test, L, parser, allow_copy)
                g = G if L is lib else 0
                ov = stb_codec.CAPSID_BYTES * n
                row = {
                    "config": label, "copy": allow_copy, "parser": parser,
                    "rho_streams_payload": orig / (s + ov),
                    "rho_rc_payload": orig / (r + ov),
                    "rho_streams_amort": orig / (s + ov + g),
                    "rho_rc_amort": orig / (r + ov + g),
                    "gain_pct": (s / r - 1) * 100,
                    "fails": fails, "time_s": round(el, 1),
                }
                rows.append(row)
                print(f"  {family:8s} {label:6s} copy={str(allow_copy):5s} {parser:7s} "
                      f"streams={row['rho_streams_amort']:6.3f} rc={row['rho_rc_amort']:6.3f} "
                      f"(amort; sem custo: {row['rho_streams_payload']:.3f} -> {row['rho_rc_payload']:.3f}) "
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
    name = "token_coder_swap.json" if args.swap else "token_coder.json"
    (OUT / name).write_text(json.dumps(result, indent=1))
    print("gravado:", OUT / name)


if __name__ == "__main__":
    sys.setrecursionlimit(10000)
    main()
