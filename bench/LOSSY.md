# Experimento com perda: stb-lossy-v1

Premissa testada: o STB como codificação semântica/perceptual, em que a reconstrução
X̂ satisfaz uma tolerância τ e não precisa ser igual a X (paper, §3.2 L1, §4 N4).

Este documento descreve a versão **stb-lossy-v1**, implementada em `bench/exp_lossy.py`.
Resultados brutos: `bench/results/lossy_stb-lossy-v1.json` (ignorado pelo Git).
Reprodução: `python bench/exp_lossy.py` (cerca de 12 min; 8 imagens, 72 configurações do STB por imagem).

## Escopo e limites do que foi medido

- **Domínio**: 8 imagens em tons de cinza, do pacote `scikit-image` (camera, astronaut,
  moon, brick, grass, gravel, page, coffee), cortadas para múltiplos de 8.
- **Métrica de tolerância**: SSIM global (`skimage`, `data_range=255`). É a métrica que o
  paper cita para imagens (N4). Corresponde ao regime **perceptual**.
- **Não medido**: o regime **semântico** (texto, áudio). O paper usa distância de
  embedding, e não há modelo de embedding disponível offline neste ambiente.
- **Código Rust não envolvido**: o decodificador é de referência, em Python. A via com
  perda não passa pela VM STB.

## Regras declaradas

**stb-lossy-v1**
- Blocos 8×8, em ordem de varredura.
- Para cada bloco, o primeiro gene que satisfaz `SSIM_local(bloco, gene) ≥ τ`, na ordem:
  - `FLAT`: valor médio do bloco (1 byte);
  - `REF`: um dos últimos 1024 blocos já decodificados (2 bytes);
  - `PLANE`: gradiente a + b·j + c·i, com b e c quantizados em passo 0,25 (3 bytes);
  - `RES`: sempre aceito; o bloco é quantizado com passo q (64 bytes).
- `SSIM_local` é a fórmula do SSIM aplicada ao bloco inteiro, sem janela deslizante, com
  as constantes C1 e C2 do SSIM.
- Γ não é um arquivo separado: a biblioteca são os blocos decodificados, e o custo está
  nas próprias instruções que os produzem.
- Fluxos (escolhas, valores, REF, resíduo): cada um com a menor entre cru e LZMA2 raw 9e.
- Custo: 40 B de capsídeo (como no fluxos-v1) + fluxos.
- Grade: q ∈ {1, 2, 4, 8, 16, 32} × τ ∈ {0,9999; 0,99; 0,97; 0,94; 0,90; 0,80}.
- Variante **sem REF**: a mesma grade, com REF desligado.

**Referências**
- **Q+xz** (ablação): o mesmo quantizador do resíduo, aplicado a todos os pixels, sem
  genes, com LZMA2 raw 9e. Serve para isolar o efeito dos genes.
- **JPEG** e **WebP** (Pillow 13): qualidades 10 a 95. Pagam o arquivo inteiro.
- **zstd-19**: referência sem perda, sobre os pixels crus.

**Seleção**: para cada alvo de SSIM, a configuração de menor bpp com SSIM ≥ alvo, por
imagem. As comparações usam média geométrica dos bpp, nas imagens em que os dois
codecs atingem o alvo.

## Resultados

Taxa em bits por pixel (bpp). Razão em relação a 8 bpp = 8 / bpp.

### Contagem por imagem (quem tem menor bpp no alvo)

| Alvo SSIM | stb-lossy-v1 vs JPEG | vs WebP | vs Q+xz | vs sem REF |
|---|---|---|---|---|
| 0,90 | melhor 1, pior 7 (geo 1,51) | melhor 0, pior 8 (geo 2,28) | melhor 6, empate 1, pior 1 (geo 0,82) | melhor 4, empate 1, pior 3 (geo 1,04) |
| 0,95 | melhor 0, pior 8 (geo 1,69) | melhor 0, pior 8 (geo 2,58) | melhor 7, pior 1 (geo 0,85) | melhor 2, pior 6 (geo 1,19) |
| 0,98 | melhor 3, pior 5 (geo 1,15) | melhor 1, pior 7 (geo 1,77) | melhor 5, pior 3 (geo 0,94) | melhor 1, empate 1, pior 6 (geo 1,14) |
| 0,9999 (quase sem perda) | sem configuração comparável | sem configuração comparável | melhor 4, pior 3 (geo 1,02) | empate 6, pior 1 (geo 1,00) |

"geo" é a média geométrica de bpp(stb-lossy-v1) / bpp(referência). Abaixo de 1 favorece o STB.

### Alvo SSIM ≥ 0,95, por imagem (bpp)

| Imagem | stb-lossy-v1 | sem REF | Q+xz | JPEG | WebP |
|---|---|---|---|---|---|
| camera | 1,556 | 1,131 | 1,852 | 1,211 | 0,723 |
| astronaut | 1,990 | 1,618 | 2,990 | 0,741 | 0,447 |
| moon | 0,615 | 0,289 | 0,642 | 0,289 | 0,172 |
| brick | 0,684 | 0,673 | 1,215 | 0,406 | 0,172 |
| grass | 3,016 | 3,043 | 3,039 | 2,282 | 1,801 |
| gravel | 2,645 | 2,655 | 2,583 | 1,620 | 1,221 |
| page | 2,336 | 2,170 | 2,475 | 1,430 | 1,146 |
| coffee | 2,082 | 1,977 | 2,300 | 1,386 | 1,073 |

Os alvos 0,90 e 0,98 estão no JSON e seguem a mesma ordem.

### Razão 8/bpp no alvo SSIM ≥ 0,90

| Imagem | stb-lossy-v1 | JPEG | WebP |
|---|---|---|---|
| camera | 8,3× | 13,8× | 17,5× |
| astronaut | 6,1× | 18,1× | 24,9× |
| moon | 72,9× | 50,3× | 153,8× |
| brick | 26,8× | 32,3× | 55,2× |
| grass | 3,9× | 5,6× | 6,5× |
| gravel | 4,8× | 7,4× | 9,3× |
| page | 4,8× | 7,1× | 11,6× |
| coffee | 5,7× | 11,6× | 14,3× |

## Leitura

1. **Contra os codecs perceptuais, o STB-lossy-v1 perde.** Em 0,90 e 0,95, perde para WebP
   em todas as 8 imagens e para JPEG em 7 e 8 imagens, respectivamente. Em 0,98 ganha
   de JPEG em 3 imagens e de WebP em 1, mas a média geométrica continua pior (1,15× o
   JPEG, 1,77× o WebP).
2. **Os genes ajudam, mas pouco, em relação à mesma quantização sem genes.** Contra Q+xz,
   o STB economiza 18% em 0,90, 15% em 0,95 e 6% em 0,98. Sem perda, não há ganho
   (+2% contra xz sobre os pixels crus).
3. **O REF piora o resultado.** Desligá-lo reduz o bpp em 4% a 19%, dependendo do alvo.
   O único mecanismo do paper que se parece com a substituição de Xa não ajuda aqui. Uma
   hipótese, não testada: a aceitação gananciosa por limiar por bloco não é ótima em taxa
   e distorção. Um REF aceito com SSIM logo acima de τ pode custar mais SSIM global do
   que economiza em bits.
4. **A razão de compressão do paper não aparece.** O paper estima ~530× para uma foto
   DSLR. Aqui, a melhor configuração em SSIM ≥ 0,90 dá 17,5× para uma foto de câmera
   (WebP, camera). Ainda assim, o alvo 0,90 é baixo, e o paper não define o limiar
   perceptual que usa.
5. **O resultado sem perda não favorece o STB.** O STB sem perda (quantização com
   q = 1, sem genes) é equivalente ao Q+xz com q = 1. Ele fica 2% atrás do xz sobre os
   pixels crus. Mais um dado: o zstd-19 sobre os pixels fica atrás do xz em todas as
   imagens (por exemplo, 4,90 contra 4,36 bpp na camera). Por isso, comparar STB com
   zstd sem perda superestima o STB.

## Piloto descartado

Um primeiro teste usou MSE como critério de aceitação de bloco. Ele aceitava blocos
texturados trocados por média plana, com MSE baixo e SSIM global ruim (camera: SSIM 0,82
com 3112 blocos FLAT). Foi trocado por SSIM local. O piloto não está no JSON final.

## Limitações

- 8 imagens em tons de cinza, de um único pacote. Não há conjunto de treino separado,
  porque Γ é construído por imagem.
- Grade discreta: o "menor bpp no alvo" depende dos pontos testados. Alguns resultados
  são não monotônicos (por exemplo, o STB não atinge 0,9999 em page com REF, mas com
  REF desligado atinge).
- Ψ (purificação) não foi calibrado: a regra de escolha é fixa (FLAT → REF → PLANE → RES),
  e os pesos `psi_score` do Rust não são usados.
- Os fluxos de escolha usam LZMA2 sobre 2 bits por bloco. Não há modelo de contexto,
  diferente do fluxos-v1.
- JPEG e WebP foram usados com configurações padrão do Pillow, sem otimização de Huffman
  nem ajuste por imagem. Podem ser um pouco melhores com ajuste.
- A via com perda não está na VM STB, nem no Rust. Um decodificador para ela não existe
  em Rust.
