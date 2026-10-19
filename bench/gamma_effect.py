"""Efeito da biblioteca Γ no payload (sem contar o custo de Γ), com e sem COPY, parser guloso.

Também registra o controle "sem Γ, sem COPY": todo o arquivo vira fluxo de literais, então o
ρ deve coincidir com xz-9e por arquivo. Se não coincidir, o empacotador de fluxos está errado.
Saída: bench/results/gamma_effect.json.
"""
import json
from pathlib import Path

import stb_codec
import stb_v2
import run_benchmark as rb

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "data" / "corpus"
OUT = HERE / "results"


def main():
    res = {}
    for fam in ("logs", "codigo", "csv", "binario"):
        tr = [p.read_bytes() for p in sorted((CORPUS / fam / "train").iterdir())]
        te = [p.read_bytes() for p in sorted((CORPUS / fam / "test").iterdir())]
        orig, n = sum(map(len, te)), len(te)
        lib = stb_codec.Library(stb_codec.build_library(tr, rb.BUDGET))
        G_raw, G = rb.gamma_charge(lib)
        row = {"gamma_charged": G, "orig": orig}
        for label, L in (("sem_gamma", stb_codec.Library([])), ("com_gamma", lib)):
            for allow_copy in (False, True):
                size, genes = 0, 0
                for d in te:
                    toks, R = stb_v2.tokenize(d, L, "greedy", allow_copy)
                    size += len(stb_v2.pack_streams(stb_v2.streams_from_tokens(toks, R)))
                    genes += sum(1 for t in toks if t[0] in (stb_v2.T_REF, stb_v2.T_RPT))
                key = f"{label}_copy_{'on' if allow_copy else 'off'}"
                row[key] = {"rho_payload": orig / (size + stb_codec.CAPSID_BYTES * n), "gene_tokens": genes}
        res[fam] = row
        print(f"{fam:8s} Γ cobrada={G} " + " | ".join(
            f"{k}={v['rho_payload']:.3f}" for k, v in row.items() if isinstance(v, dict)), flush=True)
    OUT.mkdir(exist_ok=True)
    (OUT / "gamma_effect.json").write_text(json.dumps(res, indent=1))
    print("gravado:", OUT / "gamma_effect.json")


if __name__ == "__main__":
    main()
