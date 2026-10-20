"""Baselines zstd-19 e zstd-19+dicionário para as duas divisões, com a mesma regra do benchmark.

ρ amortizado: zstd-19 = orig / payload; zstd-19+dict = orig / (payload + dicionário cobrado).
Normal: treino = train, teste = test. Swap: treino = test, teste = train (dicionário treinado no mesmo
conjunto que a Γ correspondente).

Saída: bench/results/zstd_baselines.json
"""
import json
import zstandard

import run_benchmark as rb
from pathlib import Path

OUT = Path(__file__).resolve().parent / "results"
FAMS = ("logs", "codigo", "csv", "binario")


def baselines(train, test):
    orig = sum(len(b) for _, b in test)
    z = zstandard.ZstdCompressor(level=19)
    payload = sum(len(z.compress(b)) for _, b in test)
    zd = rb.train_zstd_dict([b for _, b in train])
    cd = zstandard.ZstdCompressor(level=19, dict_data=zstandard.ZstdCompressionDict(zd))
    payload_d = sum(len(cd.compress(b)) for _, b in test)
    D = rb.charged(zd)
    return {"zstd19": orig / payload, "zstd19_dict": orig / (payload_d + D), "dict_charged": D}


def main():
    OUT.mkdir(exist_ok=True)
    res = {"normal": {}, "swap": {}}
    for fam in FAMS:
        tr, te = rb.load(fam, "train"), rb.load(fam, "test")
        res["normal"][fam] = baselines(tr, te)
        res["swap"][fam] = baselines(te, tr)
        for split in ("normal", "swap"):
            r = res[split][fam]
            print(f"{split:6s} {fam:8s} zstd-19={r['zstd19']:.3f} zstd-19+dict={r['zstd19_dict']:.3f} "
                  f"(dict cobrado {r['dict_charged']} B)", flush=True)
    (OUT / "zstd_baselines.json").write_text(json.dumps(res, indent=1))
    print("gravado:", OUT / "zstd_baselines.json")


if __name__ == "__main__":
    main()
