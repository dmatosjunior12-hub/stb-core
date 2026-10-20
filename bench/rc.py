"""Codificador aritmético binário adaptativo (estilo LZMA), mínimo.

Blocos:
  Encoder / Decoder  codificam/decodificam um bit com um slot [p, n] (ver abaixo).
  TreeModel(nbits)   símbolo de `nbits` bits, um contexto por nó da árvore binária.
                     Aprende a frequência de cada símbolo (ex.: ids de genes).
  IntModel()         inteiro >= 0 por Elias-gamma adaptativo: prefixo unário do número
                     de bits e mantissa, cada posição com contexto próprio.

Cada contexto é um slot [p, n]: probabilidade de 11 bits e número de observações. A taxa
de atualização é 1/(n+2), limitada a 1/32 (LIMIT = 30). Assim um contexto novo aprende
rápido e depois estabiliza, sem ajuste por arquivo.

Garantia: decodificar o que foi codificado com os mesmos modelos devolve os mesmos valores.
Os testes em test_bench.py cobrem isso.
"""

PROB_BITS = 11
PROB_ONE = 1 << PROB_BITS
PROB_INIT = PROB_ONE >> 1
LIMIT = 30                       # taxa mínima 1/(LIMIT+2), ~ deslocamento 5 do LZMA
RATE = [65536 // (n + 2) for n in range(LIMIT + 1)]  # taxa 1/(n+2): rápida no início
TOP = 1 << 24
MASK32 = 0xFFFFFFFF
MAX_GAMMA = 40  # bits máximos de um inteiro codificado (até ~1 trilhão)


class Encoder:
    def __init__(self):
        self.low = 0
        self.range = MASK32
        self.cache = 0
        self.cache_size = 1
        self.out = bytearray()

    def _shift_low(self):
        if self.low < 0xFF000000 or self.low > MASK32:
            carry = self.low >> 32
            temp = self.cache
            while True:
                self.out.append((temp + carry) & 0xFF)
                temp = 0xFF
                self.cache_size -= 1
                if self.cache_size == 0:
                    break
            self.cache = (self.low >> 24) & 0xFF
        self.cache_size += 1
        self.low = (self.low & 0x00FFFFFF) << 8

    def bit(self, slot, b):
        """Codifica `b` com o modelo `slot` = [p, n] (p: P(bit=0) em 11 bits; n: observações)."""
        p, n = slot
        bound = (self.range >> PROB_BITS) * p
        if b:
            self.low += bound
            self.range -= bound
            slot[0] = p - ((p * RATE[n]) >> 16)
        else:
            self.range = bound
            slot[0] = p + (((PROB_ONE - p) * RATE[n]) >> 16)
        if n < LIMIT:
            slot[1] = n + 1
        while self.range < TOP:
            self.range <<= 8
            self._shift_low()

    def finish(self) -> bytes:
        for _ in range(5):
            self._shift_low()
        return bytes(self.out)


class Decoder:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.range = MASK32
        self.code = 0
        for _ in range(5):
            self.code = ((self.code << 8) | self._next()) & MASK32

    def _next(self) -> int:
        if self.pos >= len(self.data):
            # Um fluxo válido nunca é lido além do fim: o encoder grava todos os bytes no finish().
            raise ValueError("fluxo aritmético truncado ou corrompido")
        b = self.data[self.pos]
        self.pos += 1
        return b

    def bit(self, slot) -> int:
        p, n = slot
        bound = (self.range >> PROB_BITS) * p
        if self.code < bound:
            self.range = bound
            slot[0] = p + (((PROB_ONE - p) * RATE[n]) >> 16)
            b = 0
        else:
            self.code -= bound
            self.range -= bound
            slot[0] = p - ((p * RATE[n]) >> 16)
            b = 1
        if n < LIMIT:
            slot[1] = n + 1
        while self.range < TOP:
            self.range <<= 8
            self.code = ((self.code << 8) | self._next()) & MASK32
        return b


class TreeModel:
    """Símbolo em [0, 2**nbits) com árvore binária adaptativa."""

    def __init__(self, nbits: int):
        self.nbits = nbits
        self.probs = [[PROB_INIT, 0] for _ in range(1 << nbits)]

    def encode(self, enc: Encoder, v: int) -> None:
        m = 1
        for k in range(self.nbits - 1, -1, -1):
            b = (v >> k) & 1
            enc.bit(self.probs[m], b)
            m = (m << 1) | b

    def decode(self, dec: Decoder) -> int:
        m = 1
        for _ in range(self.nbits):
            m = (m << 1) | dec.bit(self.probs[m])
        return m - (1 << self.nbits)


class IntModel:
    """Inteiro >= 0 por Elias-gamma adaptativo (contexto por posição do prefixo e da mantissa)."""

    def __init__(self):
        self.unary = [[PROB_INIT, 0] for _ in range(MAX_GAMMA + 1)]
        self.mant = [[PROB_INIT, 0] for _ in range((MAX_GAMMA + 1) * (MAX_GAMMA + 1))]

    def encode(self, enc: Encoder, v: int) -> None:
        if v < 0:
            raise ValueError("IntModel aceita apenas inteiros >= 0")
        x = v + 1
        n = x.bit_length() - 1  # bits de mantissa
        if n > MAX_GAMMA:
            raise ValueError("inteiro grande demais para IntModel")
        for k in range(n):
            enc.bit(self.unary[k], 1)
        enc.bit(self.unary[n], 0)
        for k in range(n - 1, -1, -1):
            enc.bit(self.mant[n * (MAX_GAMMA + 1) + k], (x >> k) & 1)

    def decode(self, dec: Decoder) -> int:
        n = 0
        while dec.bit(self.unary[n]):
            n += 1
            if n > MAX_GAMMA:
                raise ValueError("prefixo corrompido")
        x = 1
        for k in range(n - 1, -1, -1):
            x = (x << 1) | dec.bit(self.mant[n * (MAX_GAMMA + 1) + k])
        return x - 1
