"""Experimento: Γ como dicionário (janela de cópia pré-carregada), comparado ao uso de Γ só como genes.

Variantes (todas gulosas, mesma Γ, mesmo orçamento BUDGET):
  A  genes      : REF/RPT de genes de Γ + COPY dentro do arquivo (linha de base atual)
  B  dict       : Γ é só uma janela inicial de COPY; sem REF (Γ inteira vira histórico)
  C  dict+genes : janela de COPY com Γ + REF/RPT para genes (o gene vence quando é ≥ a cópia)
  D  sem Γ      : COPY dentro do arquivo, sem nenhuma biblioteca (referência, sem custo de Γ)

Custo de Γ: min(cru, LZMA2) como no restante do benchmark, cobrado em A, B e C.
Dois empacotadores para cada variante: fluxos + zstd-19 (stb_v2.pack_streams) e codificador adaptativo
(token_coder). Verificação: cada programa é executado pela VM; o prefixo de REFs que reconstrói Γ
não é cobrado (o receptor já tem Γ) e a saída do arquivo é a parte depois de Γ.

Uso: python3 bench/exp_gamma_dict.py [--swap] [--families logs,codigo,csv,binario]
Saída: bench/results/gamma_dict[_swap].json
"""

import argparse
import json
import time
from pathlib import Path

import rc  # noqa: F401  (token_coder depende de rc)
import run_benchmark as rb
import stb_codec
import stb_v2
import stb_vm
import token_coder

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "data" / "corpus"
OUT = HERE / "results"


def dict_events(data: bytes, lib, G_bytes: bytes, use_genes: bool):
    """Guloso com janela de cópia = Γ ‖ dados. Retorna eventos (L/G/C) com posições relativas aos dados."""
    G = len(G_bytes)
    comb = G_bytes + data
    m = stb_v2._Matcher(comb, stb_codec.Library([]))  # o matcher só usa o índice de COPY aqui
    ev = []
    n = len(data)
    p = 0  # posição em `data`
    while p < n:
        q = p + G  # posição em `comb`
        m.ensure(q)
        gi, glen = -1, 0
        if use_genes and n - p >= 8:
            for cand in lib.index.get(data[p:p + 8], ()):
                g = lib.genes[cand]
                if data.startswith(g, p):
                    gi, glen = cand, len(g)
                    break
        clen, cdist = 0, 0
        for dist, L in m.copies(q):
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


def variant_tokens(name, data, lib, G_bytes):
    if name == "A":
        return stb_v2.tokenize(data, lib, "greedy", True)
    if name == "D":
        return stb_v2.tokenize(data, stb_codec.Library([]), "greedy", True)
    ev = dict_events(data, lib, G_bytes, use_genes=(name == "C"))
    return stb_v2.events_to_tokens(ev, data)


def verify_vm(tokens, R, lib, G_bytes, data):
    """Executa pela VM: prefixo de REFs reconstrói Γ; a saída do arquivo deve ser `data`."""
    prefix = b"".join(stb_vm.enc_ref(gid) for gid in lib.ids)
    prog = prefix + stb_v2.bytecode_from_tokens(tokens, lib)
    out = stb_vm.execute(prog, lib.payload, residue=R)
    return out[len(G_bytes):] == data and out[:len(G_bytes)] == G_bytes


def run_family(family, swap):
    train = [p.read_bytes() for p in sorted((CORPUS / family / "train").iterdir())]
    test = [p.read_bytes() for p in sorted((CORPUS / family / "test").iterdir())]
    if swap:
        train, test = test, train
    lib = stb_codec.Library(stb_codec.build_library(train, rb.BUDGET))
    G_bytes = b"".join(lib.genes)
    G = rb.gamma_charge(lib)[1]
    orig, n = sum(map(len, test)), len(test)
    ov = stb_codec.CAPSID_BYTES * n
    rows = {}
    for name, label in (("A", "genes"), ("B", "dict"), ("C", "dict+genes"), ("D", "sem Γ")):
        s = r = fails = 0
        t0 = time.perf_counter()
        n_genes = len(lib.genes) if name in ("A", "C") else 0
        for d in test:
            toks, R = variant_tokens(name, d, lib, G_bytes)
            s += len(stb_v2.pack_streams(stb_v2.streams_from_tokens(toks, R)))
            blob = token_coder.encode_tokens(toks, R, n_genes)
            r += len(blob)
            try:
                if token_coder.decode_tokens(blob, n_genes) != (toks, R):
                    fails += 1
                elif not verify_vm(toks, R, lib if name != "D" else stb_codec.Library([]),
                                   G_bytes if name != "D" else b"", d):
                    fails += 1
            except (stb_vm.VmError, ValueError, IndexError) as exc:
                print(f"    [falha {name}] {exc}")
                fails += 1
        g = 0 if name == "D" else G
        rows[name] = {
            "label": label,
            "rho_streams_payload": orig / (s + ov),
            "rho_rc_payload": orig / (r + ov),
            "rho_streams_amort": orig / (s + ov + g),
            "rho_rc_amort": orig / (r + ov + g),
            "gamma_charge": g,
            "fails": fails,
            "time_s": round(time.perf_counter() - t0, 1),
        }
        x = rows[name]
        print(f"  {family:8s} {name} {label:11s} streams={x['rho_streams_amort']:6.3f} rc={x['rho_rc_amort']:6.3f} "
              f"(sem custo: {x['rho_streams_payload']:.3f}/{x['rho_rc_payload']:.3f}) "
              f"Γ={g} falhas={fails} t={x['time_s']}s", flush=True)
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
    name = "gamma_dict_swap.json" if args.swap else "gamma_dict.json"
    (OUT / name).write_text(json.dumps(result, indent=1))
    print("gravado:", OUT / name)


if __name__ == "__main__":
    main()
