"""Encoder STB mínimo para o benchmark.

Recebe bytes brutos e produz um programa do formato do STB-Core, usando uma
biblioteca de genes Γ construída SOMENTE a partir dos dados de treino.

Estratégia (intencionalmente simples, para medir o formato, não um otimizador):

1. Γ: janelas de 64, 32 e 16 bytes com frequência >= 3 no treino, ordenadas por
   benefício estimado (frequência × (tamanho − custo do REF)), com supressão de
   sobreposição, até um orçamento em bytes (custo serializado como DEF).
2. Encoder guloso: em cada posição, usa o gene MAIS LONGO que casa exatamente
   (um REF emite o gene inteiro, então não há casamento parcial). Sem casamento,
   o byte vai para um literal.
3. Literais viram `DEF "~" <bytes>` + `REF "~"` (id local reservado). Runs de
   3+ REFs idênticos consecutivos viram `RPT`.
4. Termina com STP.

Limitação conhecida do formato (medida, não corrigida aqui): não existe REF a
bytes já emitidos na saída, então repetições dentro do próprio arquivo que não
estejam em Γ viram literais.
"""

import numpy as np

import stb_vm

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"  # sem '~'
LOCAL_ID = "~"
GENE_LENGTHS = (64, 32, 16)
MIN_COUNT = 3
RPT_MIN = 3
REF_COST = 5          # bytes típicos de um REF com id de 2 caracteres
LIT_OVERHEAD = 12     # DEF "~" (1+2+1+4) + REF "~" (1+2+1) por run de literais (formato atual)
# Em modo resíduo, cada run custa só o RES n (1+4) — ver stb_vm.RES_OVERHEAD.
CAPSID_BYTES = 40     # cabeçalho fixo: magic(4) + versão(1) + SHA256(32) + flags(3)
PREFIX = 8            # bytes usados para indexar candidatos no encoder
_BASE = np.uint64(0x100000001B3)


def gene_id(index: int) -> str:
    s = ""
    while True:
        s = ALPHABET[index % 62] + s
        index //= 62
        if index == 0:
            return s


def _window_hashes(arr: np.ndarray, length: int) -> np.ndarray:
    n = len(arr) - length + 1
    h = np.zeros(n, dtype=np.uint64)
    for j in range(length):
        h = h * _BASE + arr[j:j + n]
    return h


def build_library(files: list, budget: int) -> list:
    """Constrói Γ (lista de payloads) a partir de arquivos de treino (bytes)."""
    if not files:
        return []
    arrays = [np.frombuffer(f, dtype=np.uint8).astype(np.uint64) for f in files]
    candidates = []  # (score, length, file_idx, pos)
    for length in GENE_LENGTHS:
        hashes = []
        owners = []
        for fi, arr in enumerate(arrays):
            if len(arr) < length:
                continue
            h = _window_hashes(arr, length)
            hashes.append(h)
            owners.append((fi, len(h)))
        if not hashes:
            continue
        all_h = np.concatenate(hashes)
        starts = np.cumsum([0] + [n for _, n in owners])[:-1]
        uniq, first, counts = np.unique(all_h, return_index=True, return_counts=True)
        keep = counts >= MIN_COUNT
        first, counts = first[keep], counts[keep]
        for idx, cnt in zip(first.tolist(), counts.tolist()):
            seg = int(np.searchsorted(starts, idx, side="right") - 1)
            fi = owners[seg][0]
            pos = idx - int(starts[seg])
            candidates.append((cnt * (length - REF_COST), length, fi, pos))
    # maior benefício primeiro; desempate determinístico
    candidates.sort(key=lambda c: (-c[0], -c[1], c[2], c[3]))

    selected = []
    covered = set()
    size = 0
    for _score, length, fi, pos in candidates:
        gene = files[fi][pos:pos + length]
        grams = [gene[k:k + 16] for k in range(0, length - 15, 8)]
        if sum(g in covered for g in grams) * 2 >= len(grams):
            continue  # quase todo coberto por genes já escolhidos
        cost = 1 + 2 + len(gene_id(len(selected))) + 4 + length
        if size + cost > budget:
            continue
        selected.append(gene)
        size += cost
        covered.update(gene[k:k + 16] for k in range(length - 15))
    return selected


class Library:
    """Γ pronta para uso: ids, payloads e índice de casamento por prefixo."""

    def __init__(self, genes: list):
        self.genes = genes
        self.ids = [gene_id(i) for i in range(len(genes))]
        self.payload = {gid: g for gid, g in zip(self.ids, genes)}
        self.index = {}
        for i, g in enumerate(genes):
            self.index.setdefault(g[:PREFIX], []).append(i)
        for lst in self.index.values():
            lst.sort(key=lambda i: -len(genes[i]))  # mais longo primeiro

    def serialized_size(self) -> int:
        """Custo de transmitir Γ como uma sequência de DEFs."""
        return sum(1 + 2 + len(gid.encode()) + 4 + len(g)
                   for gid, g in zip(self.ids, self.genes))

    def as_program(self) -> bytes:
        return b"".join(stb_vm.enc_def(gid, g) for gid, g in zip(self.ids, self.genes))


def encode(data: bytes, lib: Library, residue_mode: bool = False):
    """Retorna (programa, estatísticas, Ω).

    residue_mode=False: formato atual do STB-Core; literais viram DEF "~" + REF "~" e
                        ficam crus no programa. Ω = None.
    residue_mode=True:  extensão do benchmark; literais vão para Ω (bytes concatenados,
                        a ser comprimido à parte) e o programa usa RES n por run.
    O programa inclui STP final.
    """
    out = bytearray()
    lit = bytearray()
    residue = bytearray() if residue_mode else None
    lit_overhead = stb_vm.RES_OVERHEAD if residue_mode else LIT_OVERHEAD
    pend_id = None
    pend_n = 0
    ref_bytes = 0
    used = set()

    def flush_pending():
        nonlocal pend_id, pend_n
        if pend_id is None:
            return
        ref = stb_vm.enc_ref(pend_id)
        if pend_n >= RPT_MIN:
            out.extend(stb_vm.enc_rpt(pend_n, ref))
        else:
            out.extend(ref * pend_n)
        pend_id = None
        pend_n = 0

    def flush_literal():
        if lit:
            if residue_mode:
                out.extend(stb_vm.enc_res(len(lit)))
                residue.extend(lit)
            else:
                out.extend(stb_vm.enc_def(LOCAL_ID, bytes(lit)))
                out.extend(stb_vm.enc_ref(LOCAL_ID))
            lit.clear()

    n = len(data)
    i = 0
    while i < n:
        best = -1
        if n - i >= PREFIX:
            for gi in lib.index.get(data[i:i + PREFIX], ()):
                if data.startswith(lib.genes[gi], i):
                    best = gi
                    break
        if best >= 0 and len(lib.genes[best]) <= REF_COST + (lit_overhead if lit else 0):
            # Custo-benefício: um REF custa REF_COST; com literais pendentes, usar um gene
            # interrompe o run, e o run seguinte paga LIT_OVERHEAD de novo.
            best = -1
        if best >= 0:
            flush_literal()
            gid = lib.ids[best]
            if pend_id == gid:
                pend_n += 1
            else:
                flush_pending()
                pend_id = gid
                pend_n = 1
            used.add(best)
            ref_bytes += len(lib.genes[best])
            i += len(lib.genes[best])
        else:
            flush_pending()
            lit.append(data[i])
            i += 1
    flush_pending()
    flush_literal()
    out.extend(stb_vm.STP_BYTES)
    stats = {
        "ref_bytes": ref_bytes,
        "literal_bytes": n - ref_bytes,
        "genes_used": len(used),
    }
    return bytes(out), stats, (bytes(residue) if residue_mode else None)
