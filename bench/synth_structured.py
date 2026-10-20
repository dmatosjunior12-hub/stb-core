"""Imagens estruturadas, geradas de forma determinística, para o experimento com perda.

São desenhos com regiões planas, linhas, texto e formas repetidas: o tipo de conteúdo
em que genes (FLAT, REF, PLANE) deveriam ajudar mais do que em fotografias.
Todas são tons de cinza, 512x512 (múltiplo de 8), e dependem só de `seed`.
"""

import numpy as np
from PIL import Image, ImageDraw, ImageFont

SIZE = 512
_FONT_CACHE = {}


def _font(size):
    if size not in _FONT_CACHE:
        _FONT_CACHE[size] = ImageFont.load_default(size=size)
    return _FONT_CACHE[size]


def _gray(im):
    return np.asarray(im.convert("L"), dtype=np.uint8)


def grafico_linha(seed=0):
    rng = np.random.default_rng(seed)
    im = Image.new("L", (SIZE, SIZE), 255)
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = 60, 40, 480, 440
    for i in range(1, 6):  # grade horizontal
        y = y0 + i * (y1 - y0) // 6
        d.line([(x0, y), (x1, y)], fill=225)
    d.line([(x0, y0), (x0, y1), (x1, y1)], fill=0, width=2)
    for serie, nivel in zip(range(3), (60, 150, 230)):
        pontos = []
        v = nivel
        for i in range(40):
            v = np.clip(v + rng.normal(0, 8), 20, 480)
            pontos.append((x0 + i * (x1 - x0) / 39, y1 - v * (y1 - y0) / 480))
        d.line(pontos, fill=40 + 80 * serie, width=2)
    for i in range(0, 41, 10):  # marcas do eixo x
        x = x0 + i * (x1 - x0) / 40
        d.line([(x, y1), (x, y1 + 6)], fill=0)
        d.text((x - 6, y1 + 10), str(i), fill=0, font=_font(12))
    return _gray(im)


def grafico_barras(seed=1):
    rng = np.random.default_rng(seed)
    im = Image.new("L", (SIZE, SIZE), 255)
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = 60, 40, 480, 440
    d.line([(x0, y0), (x0, y1), (x1, y1)], fill=0, width=2)
    n = 12
    largura = (x1 - x0) / n
    for i in range(n):
        altura = int(rng.integers(40, 360))
        xa = x0 + i * largura + largura * 0.2
        xb = x0 + (i + 1) * largura - largura * 0.2
        d.rectangle([xa, y1 - altura, xb, y1], fill=90 if i % 2 else 170, outline=0)
        d.text((xa, y1 - altura - 16), str(altura), fill=0, font=_font(11))
    return _gray(im)


def documento(seed=2):
    rng = np.random.default_rng(seed)
    frases = [
        "O sistema registra cada transacao em ordem cronologica e mantem o historico.",
        "A verificacao de integridade ocorre antes da execucao de qualquer instrucao.",
        "Os parametros padrao foram definidos a partir de medicoes em conjuntos reais.",
        "Quando a tolerancia e excedida, o receptor solicita a retransmissao do bloco.",
        "A biblioteca de genes e atualizada somente apos a validacao dos dados.",
        "Cada secao do relatorio descreve um componente e suas limitacoes conhecidas.",
    ]
    im = Image.new("L", (SIZE, SIZE), 255)
    d = ImageDraw.Draw(im)
    d.text((48, 40), "Relatorio tecnico n. 12", fill=0, font=_font(24))
    d.line([(48, 80), (464, 80)], fill=0, width=1)
    y = 110
    for _ in range(18):
        frase = frases[int(rng.integers(len(frases)))]
        d.text((48, y), frase[: int(rng.integers(40, 80))] + "...", fill=20, font=_font(13))
        y += 22
        if rng.random() < 0.2:
            y += 14
    return _gray(im)


def tabela(seed=3):
    rng = np.random.default_rng(seed)
    im = Image.new("L", (SIZE, SIZE), 255)
    d = ImageDraw.Draw(im)
    linhas, colunas = 16, 6
    x0, y0, x1, y1 = 24, 24, 488, 488
    cw = (x1 - x0) / colunas
    rh = (y1 - y0) / linhas
    for i in range(linhas + 1):
        y = y0 + i * rh
        d.line([(x0, y), (x1, y)], fill=0 if i in (0, 1, linhas) else 150)
    for j in range(colunas + 1):
        x = x0 + j * cw
        d.line([(x, y0), (x, y1)], fill=0 if j in (0, colunas) else 150)
    for i in range(linhas):
        for j in range(colunas):
            if i == 0:
                texto = f"Col {j + 1}"
            elif j == 0:
                texto = f"Item {i:02d}"
            else:
                texto = f"{int(rng.integers(0, 1000)):,}".replace(",", ".")
            d.text((x0 + j * cw + 8, y0 + i * rh + 10), texto, fill=0, font=_font(14))
    return _gray(im)


def interface(seed=4):
    rng = np.random.default_rng(seed)
    im = Image.new("L", (SIZE, SIZE), 242)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 120, SIZE], fill=55)  # barra lateral
    for i in range(7):
        y = 60 + i * 56
        d.rectangle([24, y, 96, y + 26], fill=85 if i else 120)
        d.text((30, y + 6), f"Menu {i + 1}", fill=255, font=_font(12))
    for r in range(3):
        for c in range(2):
            x = 150 + c * 170
            y = 40 + r * 150
            d.rounded_rectangle([x, y, x + 150, y + 120], radius=8, fill=255, outline=200)
            d.text((x + 12, y + 12), f"Cartao {r * 2 + c + 1}", fill=0, font=_font(13))
            for k in range(3):
                largura = int(rng.integers(90, 130))
                d.rectangle([x + 12, y + 44 + k * 18, x + 12 + largura, y + 50 + k * 18], fill=190)
            d.rounded_rectangle([x + 12, y + 92, x + 110, y + 110], radius=6, fill=60)
            d.text((x + 28, y + 95), "Abrir", fill=255, font=_font(12))
    d.rectangle([150, 490, 490, 512], fill=200)  # rodapé
    d.ellipse([440, 60, 470, 90], fill=110)  # ícone
    return _gray(im)


def diagrama(seed=5):
    rng = np.random.default_rng(seed)
    im = Image.new("L", (SIZE, SIZE), 255)
    d = ImageDraw.Draw(im)
    nomes = ["Entrada", "Purificacao", "Biblioteca", "Empacotamento", "Transmissao", "Execucao"]
    pos = [(30 + (i % 3) * 160, 60 + (i // 3) * 220) for i in range(6)]
    for (x, y), nome in zip(pos, nomes):
        d.rounded_rectangle([x, y, x + 130, y + 80], radius=10, fill=255, outline=0, width=2)
        d.text((x + 14, y + 30), nome, fill=0, font=_font(14))
    for i in range(5):
        (xa, ya), (xb, yb) = pos[i], pos[i + 1]
        if i == 2:
            continue
        ax, ay = (xa + 130, ya + 40)
        bx, by = (xb, yb + 40)
        d.line([(ax, ay), (bx, by)], fill=0, width=2)
        d.polygon([(bx, by), (bx - 9, by - 5), (bx - 9, by + 5)], fill=0)
    for (xa, ya), (xb, yb) in [(pos[0], pos[3]), (pos[2], pos[5])]:
        ax, ay = xa + 65, ya + 80
        bx, by = xb + 65, yb
        d.line([(ax, ay), (bx, by)], fill=120, width=1)
    d.text((40, 470), "Fluxo de dados, versao de teste", fill=0, font=_font(13))
    return _gray(im)


GERADORES = {
    "grafico_linha": grafico_linha,
    "grafico_barras": grafico_barras,
    "documento": documento,
    "tabela": tabela,
    "interface": interface,
    "diagrama": diagrama,
}


def carregar_estruturadas():
    return {nome: f() for nome, f in GERADORES.items()}


if __name__ == "__main__":
    import os
    import sys

    destino = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "results", "estruturadas")
    os.makedirs(destino, exist_ok=True)
    for nome, img in carregar_estruturadas().items():
        Image.fromarray(img).save(os.path.join(destino, nome + ".png"))
        print(nome, img.shape, img.dtype, "min", img.min(), "max", img.max())
