"""Monta o corpus do benchmark em bench/data/corpus/ (fora do Git).

Famílias (todas reais, exceto o controle aleatório):

  logs        16 sistemas do Loghub (logs reais de 2k linhas). Split TEMPORAL:
              primeira metade das linhas = treino, segunda metade = teste.
  codigo      código-fonte Python da stdlib (arquivos inteiros). Split por arquivo.
  csv         22 datasets CSV do seaborn-data. Split temporal por linhas (cabeçalho em ambos).
  binario     arquivos .pyc da stdlib (arquivos inteiros). Split por arquivo.
  aleatorio   bytes aleatórios (controle negativo; dicionário treinado em outros
              bytes aleatórios). Não há estrutura a explorar.

Os dados são baixados de codeload.github.com se não estiverem presentes.
Um manifesto com SHA-256 de cada arquivo é gravado em bench/data/manifest.json.
"""

import hashlib
import json
import random
import sysconfig
import tarfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
RAW = DATA / "raw"
CORPUS = DATA / "corpus"

SOURCES = {
    "loghub": "https://codeload.github.com/logpai/loghub/tar.gz/refs/heads/master",
    "seaborn": "https://codeload.github.com/mwaskom/seaborn-data/tar.gz/refs/heads/master",
}


def _fetch_sources():
    RAW.mkdir(parents=True, exist_ok=True)
    for name, url in SOURCES.items():
        tgz = RAW / f"{name}.tgz"
        if not tgz.exists():
            print(f"baixando {name} ...")
            urllib.request.urlretrieve(url, tgz)
        marker = RAW / f"{name}.extracted"
        if not marker.exists():
            with tarfile.open(tgz) as tf:
                root = RAW.resolve()
                for member in tf.getmembers():  # evita caminhos fora de RAW
                    target = (RAW / member.name).resolve()
                    if root not in target.parents and target != root:
                        raise RuntimeError(f"caminho inseguro no tarball: {member.name}")
                    if member.issym() or member.islnk():
                        raise RuntimeError(f"link no tarball não permitido: {member.name}")
                tf.extractall(RAW)
            marker.touch()


def _write(family: str, split: str, name: str, data: bytes, manifest: dict):
    path = CORPUS / family / split / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    manifest.setdefault(family, {}).setdefault(split, {})[name] = hashlib.sha256(data).hexdigest()


def _parity_split(files):
    """Índices pares -> treino, ímpares -> teste (ordem determinística)."""
    files = sorted(files)
    return [f for i, f in enumerate(files) if i % 2 == 0], [f for i, f in enumerate(files) if i % 2 == 1]


def build():
    _fetch_sources()
    if CORPUS.exists():
        for p in sorted(CORPUS.rglob("*"), reverse=True):
            if p.is_file():
                p.unlink()
    manifest = {}

    # --- logs: split temporal por sistema
    for log in sorted((RAW / "loghub-master").glob("*/*_2k.log")):
        lines = log.read_bytes().splitlines(keepends=True)
        half = len(lines) // 2
        _write("logs", "train", log.name, b"".join(lines[:half]), manifest)
        _write("logs", "test", log.name, b"".join(lines[half:]), manifest)

    stdlib = Path(sysconfig.get_paths()["stdlib"])

    # --- código-fonte: amostra determinística de módulos 4–120 KB
    py = [p for p in stdlib.glob("*.py") if 4096 <= p.stat().st_size <= 120 * 1024]
    rng = random.Random(42)
    py = rng.sample(sorted(py), 40)
    tr, te = _parity_split(py)
    for p in tr:
        _write("codigo", "train", p.name, p.read_bytes(), manifest)
    for p in te:
        _write("codigo", "test", p.name, p.read_bytes(), manifest)

    # --- CSV reais
    # --- CSV reais: split temporal por linhas (cabeçalho em ambas as metades)
    for csv in sorted((RAW / "seaborn-data-master").glob("*.csv")):
        lines = csv.read_bytes().splitlines(keepends=True)
        if len(lines) < 4:
            continue
        header, body = lines[0], lines[1:]
        half = len(body) // 2
        _write("csv", "train", csv.name, header + b"".join(body[:half]), manifest)
        _write("csv", "test", csv.name, header + b"".join(body[half:]), manifest)

    # --- binários: .pyc da stdlib
    pyc = [p for p in (stdlib / "__pycache__").glob("*.pyc") if 4096 <= p.stat().st_size <= 100 * 1024]
    rng = random.Random(43)
    pyc = rng.sample(sorted(pyc), 40)
    tr, te = _parity_split(pyc)
    for p in tr:
        _write("binario", "train", p.name, p.read_bytes(), manifest)
    for p in te:
        _write("binario", "test", p.name, p.read_bytes(), manifest)

    # --- controle aleatório
    r1, r2 = random.Random(1), random.Random(2)
    for k in range(10):
        _write("aleatorio", "train", f"rnd_train_{k:02d}.bin", r1.randbytes(64 * 1024), manifest)
        _write("aleatorio", "test", f"rnd_test_{k:02d}.bin", r2.randbytes(64 * 1024), manifest)

    (DATA / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True))
    for fam in sorted(manifest):
        for split in ("train", "test"):
            files = manifest[fam].get(split, {})
            total = sum((CORPUS / fam / split / n).stat().st_size for n in files)
            print(f"{fam:10s} {split:5s} {len(files):3d} arquivos  {total/1024:9.1f} KiB")


if __name__ == "__main__":
    build()
