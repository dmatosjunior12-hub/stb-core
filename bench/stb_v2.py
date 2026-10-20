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
import math

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
#
# Parsers (todos produzem a mesma sequência de eventos, depois convertida em tokens):
#   greedy  pega o casamento mais longo em cada posição (comportamento original).
#   lazy    adia um literal se o casamento na posição seguinte for estritamente mais longo.
#   optimal programação dinâmica (caminho mínimo) sobre um modelo de custo em bits fixo.
#
# allow_copy=False restringe o parser a genes Γ (LIT/REF/RPT/STP): é o que se pode dizer que
# continua dentro da proposta de STB (10 verbos, sem referência à saída já emitida).

PARSERS = ("greedy", "lazy", "optimal")
LIT_BITS = 5.5          # custo de um literal (bits), após compressão do fluxo R
GENE_BITS = 12.0        # custo de um REF/RPT de gene (bits)
COPY_BASE_BITS = 12.0   # custo de um COPY: base + log2(distância) + ~log2(comprimento)
OPT_LEN_SPAN = 6        # no DP, comprimentos testados por candidato: MIN_COPY..MIN_COPY+OPT_LEN_SPAN, e o máximo


def _copy_bits(dist: int, length: int) -> float:
    return COPY_BASE_BITS + math.log2(dist) + math.log2(length)


def _match_len(d: bytes, j: int, i: int, maxlen: int) -> int:
    """Comprimento do casamento entre d[j:] e d[i:] (j < i; sobreposição permitida)."""
    L = 0
    while L + 8 <= maxlen and d[j + L:j + L + 8] == d[i + L:i + L + 8]:
        L += 8
    while L < maxlen and d[j + L] == d[i + L]:
        L += 1
    return L


class _Matcher:
    """Índice incremental: posições < `upto` estão indexadas. Consultas em p só usam posições < p."""

    def __init__(self, data: bytes, lib: stb_codec.Library):
        self.d = data
        self.n = len(data)
        self.lib = lib
        self.head = {}
        self.upto = 0

    def ensure(self, p: int) -> None:
        d, head = self.d, self.head
        while self.upto < p:
            q = self.upto
            if q + KEY <= self.n:
                head.setdefault(d[q:q + KEY], []).append(q)
            self.upto += 1

    def gene(self, p: int):
        """(gi, glen) do gene mais longo que casa em p, ou None."""
        d = self.d
        if self.n - p >= 8:
            for cand in self.lib.index.get(d[p:p + 8], ()):
                g = self.lib.genes[cand]
                if d.startswith(g, p):
                    return cand, len(g)  # lista ordenada do mais longo para o mais curto
        return None

    def copies(self, p: int):
        """Lista de (dist, L) para os últimos CHAIN candidatos, com L >= KEY. Mais recente primeiro."""
        d = self.d
        if self.n - p < KEY:
            return []
        cands = self.head.get(d[p:p + KEY])
        if not cands:
            return []
        maxlen = min(MAX_COPY, self.n - p)
        out = []
        for j in reversed(cands[-CHAIN:]):
            L = _match_len(d, j, p, maxlen)
            if L >= KEY:
                out.append((p - j, L))
        return out


def _greedy_events(data: bytes, lib: stb_codec.Library, allow_copy: bool):
    m = _Matcher(data, lib)
    ev = []
    i, n = 0, len(data)
    while i < n:
        m.ensure(i)
        g = m.gene(i)
        gi, glen = g if g else (-1, 0)
        clen, cdist = 0, 0
        if allow_copy:
            for dist, L in m.copies(i):
                if L > clen:
                    clen, cdist = L, dist
        if gi >= 0 and glen >= clen:
            ev.append(("G", gi, glen))
            i += glen
        elif clen >= MIN_COPY:
            ev.append(("C", cdist, clen))
            i += clen
        else:
            ev.append(("L", i, 1))
            i += 1
    return ev


def _best_at(m: _Matcher, p: int, allow_copy: bool):
    """Melhor casamento em p: ('G', gi, glen) | ('C', dist, L) | None (sem casamento útil)."""
    m.ensure(p)
    g = m.gene(p)
    best = ("G", g[0], g[1]) if g else None
    clen, cdist = 0, 0
    if allow_copy:
        for dist, L in m.copies(p):
            if L > clen:
                clen, cdist = L, dist
    if clen >= MIN_COPY and (best is None or clen > best[2]):
        best = ("C", cdist, clen)
    return best


def _lazy_events(data: bytes, lib: stb_codec.Library, allow_copy: bool):
    m = _Matcher(data, lib)
    ev = []
    n = len(data)
    i = 0
    cur = _best_at(m, 0, allow_copy) if n else None
    while i < n:
        if cur is None:
            ev.append(("L", i, 1))
            i += 1
            cur = _best_at(m, i, allow_copy) if i < n else None
            continue
        # lookahead de um passo: literal em i se o casamento em i+1 for estritamente mais longo
        nxt = _best_at(m, i + 1, allow_copy) if i + 1 < n else None
        if nxt is not None and nxt[2] > cur[2]:
            ev.append(("L", i, 1))
            i += 1
            cur = nxt
            continue
        ev.append(cur)
        i += cur[2]
        cur = _best_at(m, i, allow_copy) if i < n else None
    return ev


def _optimal_events(data: bytes, lib: stb_codec.Library, allow_copy: bool):
    n = len(data)
    INF = float("inf")
    cost = [INF] * (n + 1)
    back = [None] * (n + 1)
    cost[0] = 0.0
    m = _Matcher(data, lib)
    for p in range(n):
        c = cost[p]
        if c == INF:
            continue
        m.ensure(p)
        # literal
        if c + LIT_BITS < cost[p + 1]:
            cost[p + 1] = c + LIT_BITS
            back[p + 1] = ("L", p, 1)
        # gene
        g = m.gene(p)
        if g is not None:
            gi, glen = g
            q = p + glen
            if c + GENE_BITS < cost[q]:
                cost[q] = c + GENE_BITS
                back[q] = ("G", gi, glen)
        # cópias
        if allow_copy:
            for dist, Lmax in m.copies(p):
                cb = _copy_bits(dist, Lmax)
                lengths = set(range(MIN_COPY, min(Lmax, MIN_COPY + OPT_LEN_SPAN) + 1))
                lengths.add(Lmax)
                for L in lengths:
                    if L < MIN_COPY:
                        continue
                    q = p + L
                    bits = c + COPY_BASE_BITS + math.log2(dist) + math.log2(L)
                    if bits < cost[q]:
                        cost[q] = bits
                        back[q] = ("C", dist, L)
    ev = []
    q = n
    while q > 0:
        e = back[q]
        ev.append(e)
        q -= e[2]  # L, G e C ocupam e[2] bytes; a origem é q - e[2]
    ev.reverse()
    return ev


def events_to_tokens(events, data: bytes):
    """Converte eventos (L/G/C) em tokens; mesma regra de RPT e de flush do encoder guloso."""
    tokens = []
    R = bytearray()
    lit = 0
    pend_gi = None
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
        nonlocal lit
        if lit:
            tokens.append((T_LIT, lit))
            lit = 0

    for e in events:
        kind = e[0]
        if kind == "L":
            flush_pend()
            lit += 1
            R.append(data[e[1]])
        elif kind == "G":
            flush_lit()
            if pend_gi == e[1]:
                pend_n += 1
            else:
                flush_pend()
                pend_gi, pend_n = e[1], 1
        else:  # "C"
            flush_pend()
            flush_lit()
            tokens.append((T_COPY, e[1], e[2]))
    flush_pend()
    flush_lit()
    tokens.append((T_STP,))
    return tokens, bytes(R)


def parse(data: bytes, lib: stb_codec.Library, parser: str = "greedy", allow_copy: bool = True):
    """Retorna a lista de eventos do parser escolhido."""
    if parser == "greedy":
        return _greedy_events(data, lib, allow_copy)
    if parser == "lazy":
        return _lazy_events(data, lib, allow_copy)
    if parser == "optimal":
        return _optimal_events(data, lib, allow_copy)
    raise ValueError(f"parser desconhecido: {parser}")


def tokenize(data: bytes, lib: stb_codec.Library, parser: str = "greedy", allow_copy: bool = True):
    """Retorna (tokens, R). tokens: (T_LIT, n) | (T_REF, gi) | (T_RPT, count, gi) | (T_COPY, dist, len) | (T_STP,)."""
    return events_to_tokens(parse(data, lib, parser, allow_copy), data)


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
