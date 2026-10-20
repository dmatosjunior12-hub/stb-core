# Códigos de símbolo e transporte: exp_rede-v1

Este documento mede uma parte da proposta "G-REC" (símbolos de 6 bits, correção por
vizinhança Gray, transporte com perda). Ele não implementa o protocolo descrito: não há
AVX-512, nem pipeline A/P/E, nem TCP/QUIC. A versão medida é **exp_rede-v1**, em
`bench/exp_rede.py`. Resultados brutos: `bench/results/rede_exp_rede-v1.json` (ignorado
pelo Git). Reprodução: `python bench/exp_rede.py` (cerca de 1 minuto; semente fixa).

## O que foi medido

**Nível de símbolo** (N = 300 000 símbolos por ponto; BSC com erro por bit q):

| Esquema | Bits úteis por símbolo de 6 bits | Detecção/correção |
|---|---|---|
| bruto-6bits | 6 (taxa 1,000) | nenhuma |
| par-5bits | 5 (taxa 0,833) | detecta 1 erro (apagamento) |
| SEC-3bits | 3 (taxa 0,500) | corrige 1 erro (código de 8 palavras, distância 3) |
| G-REC-48 | log2(48) ≈ 5,585 (taxa 0,931) | decodifica para a palavra de dados mais próxima; sem garantia |

Erro por símbolo e taxa efetiva (taxa × (1 − erro − apagamento)):

| q | bruto: erro / efetiva | G-REC-48: erro / efetiva | SEC-3bits: erro / efetiva |
|---|---|---|---|
| 1e-3 | 0,00636 / 0,9936 | 0,00552 / 0,9257 | 0,00000 / 0,5000 |
| 1e-2 | 0,05957 / 0,9404 | 0,05501 / 0,8796 | 0,00134 / 0,4993 |
| 5e-2 | 0,26492 / 0,7351 | 0,25296 / 0,6954 | 0,03069 / 0,4847 |

**Nível de pacote** (arquivo de 10 MB; pacote de 8000 bits; canal de 10 Mbit/s; RTT de 50 ms
e 600 ms). Vazão = bits úteis do arquivo / tempo total. Melhor resultado por cenário:

| q | RTT | Melhor esquema e transporte | Vazão (Mbit/s) |
|---|---|---|---|
| 1e-6 | 50 ms | sem código interno, ARQ-SR | 9,89 |
| 1e-6 | 600 ms | sem código interno, fountain | 9,38 |
| 1e-5 | 50 ms | sem código interno, ARQ-SR | 9,17 |
| 1e-5 | 600 ms | sem código interno, fountain | 8,75 |
| 1e-4 | 50 ms | SEC-3bits, ARQ-SR | 4,99 |
| 1e-4 | 600 ms | SEC-3bits, ARQ-SR | 4,91 |
| 1e-3 | 50 ms | SEC-3bits, ARQ-SR | 4,89 |
| 1e-3 | 600 ms | SEC-3bits, fountain | 4,72 |

Perda de pacote sem código interno: 0,8% em q = 1e-6; 7,7% em 1e-5; 55% em 1e-4; 99,97% em 1e-3.
Com SEC-3bits: 0,02% em 1e-4; 2% em 1e-3.

Tabela completa (todos os esquemas e transportes) no JSON.

## Leitura

1. **G-REC-48 não corrige o suficiente para compensar a taxa.** Com q = 1e-2, o erro cai de
   5,96% para 5,50%, enquanto a taxa cai 6,9%. A taxa efetiva fica abaixo do bruto em todos
   os pontos medidos.
2. **Correção de 1 erro por símbolo custa 50% da taxa** (3 bits em 6). Detecção de 1 erro
   custa 17% (paridade, 5 bits). Um código de 48 palavras não detecta todo erro de 1 bit:
   Q6 tem 32 pares de palavras a distância 1, e 48 palavras contêm pelo menos 16 desses pares
   (argumento em `limite_par_hipercubo`, verificado).
3. **Código interno só compensa com BER bruto alto.** Abaixo de ~1e-5 (perda de pacote até
   8%), o código interno só reduz a vazão. A partir de ~1e-4, a perda sem código
   domina e o SEC-3bits passa a ganhar.
4. **FEC de transporte (fountain, 2% de sobrecarga) supera ARQ-SR em RTT longo** quando a
   perda é moderada: 8,75 contra 7,87 Mbit/s em 1e-5 com RTT de 600 ms; 4,33 contra 3,16 em
   1e-4. Em RTT curto, o ARQ ideal é um pouco melhor (9,89 contra 9,70 em 1e-6), porque o
   fountain paga 2% de sobrecarga mesmo sem perda.

## Limitações (importantes)

- **ARQ-SR é idealizado.** Sem timeouts, sem perda de ACK, sem controle de congestionamento,
  com janela fixa de 2·BDP e com o emissor sabendo da perda exatamente após o RTT.
  Por isso o ARQ aqui é um limite superior do ARQ real.
- **TCP e QUIC não foram simulados.** Qualquer afirmação sobre "vencer TCP" ou "vencer QUIC
  em satélite" continua não medida.
- **Fountain é idealizado:** sobrecarga fixa de 2%, sem falha de decodificação, sem custo de
  CPU.
- **Modelo de erro:** BSC iid. Não há rajadas, nem traços reais de satélite.
- **SEC no nível de pacote:** qualquer pacote com 2 ou mais erros num símbolo de 6 bits
  conta como perda. Isso é pessimista: alguns padrões de 2 erros são decodificados sem erro.
  O nível de símbolo, por outro lado, mede o decodificador SEC exato.
- **G-REC-48 no nível de pacote** é tratado como o bruto, só com a taxa reduzida. Não há
  nenhuma correção modelada, porque o nível de símbolo mostrou que a correção por vizinhança
  é desprezível.
- Um único par de RTTs e uma única seed. Não há intervalos de confiança.

## Afirmações do G-REC que não se sustentam (resumo)

- "48 dados + 16 de controle corrigem por vizinhança": não. Com 48 palavras sobram pelo
  menos 16 pares a distância 1, e a correção por vizinhança não tem prior para dados uniformes.
- "Base 64 aumenta a capacidade": não. Base 4 com códons de 3 letras tem a mesma capacidade
  (6 bits por códon). O código genético padrão rende ~4,32 bits por códon útil.
- Referências: HEDGES (PNAS) é código de correção para DNA (indels); não se aplica a
  protocolo de rede. Crowder & Li (2010) é descrição combinatória, sem medida de correção.
