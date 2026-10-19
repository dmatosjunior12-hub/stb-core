"""STB v2 (extensão do benchmark): cópia intra-arquivo + genes Γ + transmissão entropicamente codificada.

Modelo lógico (o que o receptor executa): uma sequência de tokens equivalente a bytecode
com as instruções RES, REF, RPT, COPY e STP, executada pela VM Python (stb_vm.py) com um
resíduo Ω (bytes dos literais). Este módulo NÃO é o formato Rust atual.

Modelo de transmissão (o que é medido): os campos dos tokens são separados em fluxos
    T    tipo de cada token (1 byte)
    LEN  comprimentos de literais e de cópias (varint)
    CNT  contagens de RPT (varint)
    GID  índices de genes (varint)
    DIST distâncias de COPY (varint)
    R    bytes dos literais (Ω)
e cada fluxo é comprimido pelo MELHOR entre {cru, LZMA2 raw (preset 9e), zstd-19}, com um
byte de método e um varint de tamanho. Isso é o que codificadores de propósito geral
fazem internamente; aqui é explícito e medido.
"""

import lzma
import zstandard

import stb_codec
import stb_vm

T_LIT, T_REF, T_RPT, T_COPY, T_STP = 0, 1, 2, 3, 4
MIN_COPY = 6           # menor cópia útil
RPT_MIN = 3            # repetições de um mesmo gene a partir daqui viram RPT
MAX_COPY = 1 << 16
CHAIN = 32             # candidatos de cópia examinados por posição
KEY = 4                # tamanho da chave de casamento para cópias
STREAMS = ("T", "LEN", "CNT", "GID", "DIST", "R")
LZMA_FILTERS = [{"id": lzma.FILTER_LZMA2, "preset": 9 | lzma.PRESET_EXTREME}]
M_RAW, M_LZMA, M_ZSTD = 0, 1, 2


# ----------------------------------------------------------------- varint

def put_varint(buf: bytearray, n: int) -> None:
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            buf.append(b | 0x80)
        else:
            buf.append(b)
            return


class VarintReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def read(self) -> int:
        shift = 0
        val = 0
        while True:
            b = self.data[self.pos]
            self.pos += 1
            val |= (b & 0x7F) << shift
            if not b & 0x80:
                return val
            shift += 7


# ----------------------------------------------------------------- tokenização

def _match_len(d: bytes, j: int, i: int, maxlen: int) -> int:
    """Comprimento do casamento entre d[j:] e d[i:] (j < i; sobreposição permitida)."""
    L = 0
    while L + 8 <= maxlen and d[j + L:j + L + 8] == d[i + L:i + L + 8]:
        L += 8
    while L < maxlen and d[j + L] == d[i + L]:
        L += 1
    return L


def tokenize(data: bytes, lib: stb_codec.Library):
    """Greedy com preferência ao casamento mais longo entre gene Γ e cópia intra-arquivo.

    Retorna (tokens, R). tokens: tuplas (T_LIT, n) | (T_REF, gi) | (T_RPT, count, gi)
    | (T_COPY, dist, len) | (T_STP,). R: bytes dos literais na ordem do programa.
    """
    n = len(data)
    tokens = []
    R = bytearray()
    head = {}                       # chave de KEY bytes -> posições já vistas (crescente)
    lit_start = 0                   # início do run de literais pendente
    lit = 0                         # tamanho do run de literais pendente
    pend_gi = None                  # gene pendente (para RPT)
    pend_n = 0

    def flush_pend():
        nonlocal pend_gi, pend_n
        if pend_gi is None:
            return
        if pend_n >= RPT_MIN:
            tokens.append((T_RPT, pend_n, pend_gi))
        else:
            tokens.extend((T_REF, pend_gi) for _ in range(pend_n))
        pend_gi = None
        pend_n = 0

    def flush_lit():
        nonlocal lit, lit_start
        if lit:
            tokens.append((T_LIT, lit))
            R.extend(data[lit_start:lit_start + lit])
            lit = 0

    def index(p):
        if p + KEY <= n:
            head.setdefault(data[p:p + KEY], []).append(p)

    i = 0
    while i < n:
        # --- gene Γ mais longo que casa exatamente em i
        gi, glen = -1, 0
        if n - i >= 8:
            for cand in lib.index.get(data[i:i + 8], ()):
                g = lib.genes[cand]
                if data.startswith(g, i):
                    gi, glen = cand, len(g)
                    break               # lista ordenada do mais longo para o mais curto
        # --- cópia intra-arquivo mais longa
        clen, cdist = 0, 0
        if n - i >= KEY:
            cands = head.get(data[i:i + KEY])
            if cands:
                maxlen = min(MAX_COPY, n - i)
                for j in reversed(cands[-CHAIN:]):
                    L = _match_len(data, j, i, maxlen)
                    if L > clen:
                        clen, cdist = L, i - j
        if gi >= 0 and glen >= clen:
            flush_lit()
            if pend_gi == gi:
                pend_n += 1
            else:
                flush_pend()
                pend_gi, pend_n = gi, 1
            step = glen
        elif clen >= MIN_COPY:
            flush_pend()
            flush_lit()
            tokens.append((T_COPY, cdist, clen))
            step = clen
        else:
            flush_pend()
            if lit == 0:
                lit_start = i
            lit += 1
            index(i)
            i += 1
            continue
        for p in range(i, i + step):
            index(p)
        i += step
    flush_pend()
    flush_lit()
    tokens.append((T_STP,))
    return tokens, bytes(R)


# ----------------------------------------------------------------- fluxos

def streams_from_tokens(tokens, R: bytes) -> dict:
    s = {k: bytearray() for k in STREAMS if k != "R"}
    for t in tokens:
        kind = t[0]
        s["T"].append(kind)
        if kind == T_LIT:
            put_varint(s["LEN"], t[1])
        elif kind == T_REF:
            put_varint(s["GID"], t[1])
        elif kind == T_RPT:
            put_varint(s["CNT"], t[1])
            put_varint(s["GID"], t[2])
        elif kind == T_COPY:
            put_varint(s["DIST"], t[1])
            put_varint(s["LEN"], t[2])
    s = {k: bytes(v) for k, v in s.items()}
    s["R"] = R
    return s


def tokens_from_streams(s: dict):
    tokens = []
    rd = {k: VarintReader(s[k]) for k in ("LEN", "CNT", "GID", "DIST")}
    for kind in s["T"]:
        if kind == T_LIT:
            tokens.append((T_LIT, rd["LEN"].read()))
        elif kind == T_REF:
            tokens.append((T_REF, rd["GID"].read()))
        elif kind == T_RPT:
            cnt = rd["CNT"].read()
            tokens.append((T_RPT, cnt, rd["GID"].read()))
        elif kind == T_COPY:
            dist = rd["DIST"].read()
            tokens.append((T_COPY, dist, rd["LEN"].read()))
        elif kind == T_STP:
            tokens.append((T_STP,))
        else:
            raise ValueError(f"tipo de token inválido: {kind}")
    return tokens


def bytecode_from_tokens(tokens, lib: stb_codec.Library) -> bytes:
    out = bytearray()
    for t in tokens:
        kind = t[0]
        if kind == T_LIT:
            out += stb_vm.enc_res(t[1])
        elif kind == T_REF:
            out += stb_vm.enc_ref(lib.ids[t[1]])
        elif kind == T_RPT:
            out += stb_vm.enc_rpt(t[1], stb_vm.enc_ref(lib.ids[t[2]]))
        elif kind == T_COPY:
            out += stb_vm.enc_copy(t[1], t[2])
        elif kind == T_STP:
            out += stb_vm.STP_BYTES
    return bytes(out)


# ----------------------------------------------------------------- empacotamento

_ZC = zstandard.ZstdCompressor(level=19)
_ZD = zstandard.ZstdDecompressor()


def pack_stream(raw: bytes) -> bytes:
    """Melhor de {cru, LZMA2 raw 9e, zstd-19}; formato: método (1 B) + tamanho (varint) + dados."""
    best_m, best = M_RAW, raw
    if raw:
        lz = lzma.compress(raw, format=lzma.FORMAT_RAW, filters=LZMA_FILTERS)
        if len(lz) < len(best):
            best_m, best = M_LZMA, lz
        zs = _ZC.compress(raw)
        if len(zs) < len(best):
            best_m, best = M_ZSTD, zs
    out = bytearray([best_m])
    put_varint(out, len(best))
    out += best
    return bytes(out)


def unpack_stream(buf: bytes, pos: int):
    m = buf[pos]
    rd = VarintReader(buf)
    rd.pos = pos + 1
    size = rd.read()
    body = buf[rd.pos:rd.pos + size]
    if m == M_RAW:
        raw = body
    elif m == M_LZMA:
        raw = lzma.decompress(body, format=lzma.FORMAT_RAW, filters=LZMA_FILTERS)
    elif m == M_ZSTD:
        raw = _ZD.decompress(body)
    else:
        raise ValueError(f"método de fluxo desconhecido: {m}")
    return raw, rd.pos + size


def pack_streams(streams: dict) -> bytes:
    return b"".join(pack_stream(streams[k]) for k in STREAMS)


def unpack_streams(buf: bytes) -> dict:
    out = {}
    pos = 0
    for k in STREAMS:
        out[k], pos = unpack_stream(buf, pos)
    if pos != len(buf):
        raise ValueError("bytes sobrando após os fluxos")
    return out
