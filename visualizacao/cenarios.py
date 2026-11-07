"""
Cenários roteirizados que exercitam os fluxos alternativos do protocolo.

Cada cenário define os parâmetros do simulador (testes/netsim.py) e um texto
"o que observar", que é impresso no terminal e no topo da figura.
Para criar um cenário novo, copie um dos dicionários e altere os parâmetros.
"""
from netsim import drop_ack_ids, drop_first_k_containing, drop_ids

# Parâmetros de tempo usados em todas as visualizações (pacotes mais espaçados
# que nos testes, para o diagrama ficar legível).
TEMPO = dict(one_way_delay=1.0, tx_time=0.35, rto=4.0)

CENARIOS = {
    "caminho-feliz": dict(
        titulo="Caminho feliz: janela deslizante sem perdas",
        tamanho=8000, recv_window=6000,
        observar=("Com janela de 6000 B cabem 4 pacotes em voo. Cada ACK devolve 1200 B de "
                  "'espaço' e o emissor imediatamente envia mais um pacote: a janela 'desliza'. "
                  "O receptor entrega cada pacote à aplicação assim que chega, pois está em ordem."),
    ),
    "perda-retransmissao-rapida": dict(
        titulo="Perda de dados detectada por ACKs posteriores (retransmissão rápida)",
        tamanho=12000, recv_window=7500, drop_data=drop_ids({1}),
        observar=("O pacote #1 se perde. Os pacotes seguintes chegam e o receptor os guarda no "
                  "buffer SEM entregá-los (há uma lacuna). Os SACKs passam a ter dois intervalos. "
                  "Depois de ACKs de pacotes enviados 3 posições depois, o emissor conclui que #1 se "
                  "perdeu e o retransmite — sem esperar timeout. Ao preencher a lacuna, o receptor "
                  "entrega tudo de uma vez."),
    ),
    "perda-de-ack": dict(
        titulo="Perda de ACK: o SACK seguinte cobre o pacote",
        tamanho=8000, recv_window=6000, drop_ack=drop_ack_ids({1}),
        observar=("O pacote #1 chega, mas o ACK dele se perde. Como cada ACK carrega TODOS os "
                  "intervalos recebidos, o ACK de #2 já mostra que os bytes de #1 chegaram. "
                  "Nada precisa ser retransmitido; repare que o ACK de #2 libera 2400 B "
                  "(pacotes #1 e #2)."),
    ),
    "perda-na-cauda-timeout": dict(
        titulo="Perda do último pacote: só o timeout salva",
        tamanho=6000, recv_window=7500, drop_data=drop_ids({4}),
        observar=("O último pacote (#4) se perde. Não há pacotes depois dele, logo não chegam ACKs "
                  "que denunciem a perda. O emissor fica esperando até o TIMEOUT; então "
                  "start_sender zera 'inflight', chama Sender.timeout() e o pacote é reenviado."),
    ),
    "retransmissao-perdida": dict(
        titulo="A retransmissão também se perde",
        tamanho=12000, recv_window=7500, drop_data=drop_first_k_containing(1500, 2),
        observar=("O pacote com o byte 1500 se perde duas vezes: a transmissão original e a "
                  "retransmissão rápida. Como a retransmissão é um pacote NOVO (novo id), a "
                  "detecção recomeça; quando não há mais ACKs posteriores, só o timeout resolve."),
    ),
    "rajada-de-perdas": dict(
        titulo="Rajada de perdas: SACK evita reenviar o que já chegou",
        tamanho=12000, recv_window=7500, drop_data=drop_ids({2, 3, 4}),
        observar=("Três pacotes seguidos se perdem. Graças aos SACKs, o emissor sabe exatamente "
                  "quais intervalos faltam e retransmite apenas eles — nunca bytes já confirmados."),
    ),
    "reordenacao": dict(
        titulo="Reordenação leve: pacote atrasado, sem retransmissão",
        tamanho=8000, recv_window=7500, extra_delay={1: 0.9},
        observar=("O pacote #1 atrasa e chega depois de #2 e #3. O receptor guarda #2 e #3 no "
                  "buffer e, quando #1 chega, entrega os três de uma vez. O atraso é menor que o "
                  "limiar de detecção, então o emissor NÃO considera #1 perdido."),
    ),
    "reordenacao-retransmissao-espuria": dict(
        titulo="Reordenação forte: retransmissão espúria e duplicata",
        tamanho=10000, recv_window=7500, extra_delay={1: 2.2},
        observar=("O atraso de #1 é tão grande que chegam ACKs de 3 pacotes posteriores antes dele: "
                  "o emissor conclui (erradamente) que #1 se perdeu e o retransmite. Depois chegam o "
                  "original e a cópia: o receptor precisa descartar a duplicata sem entregá-la duas "
                  "vezes, e o emissor não pode descontar os mesmos bytes duas vezes de 'inflight'."),
    ),
    "janela-pare-e-espere": dict(
        titulo="Janela mínima (pare-e-espere): toda perda vira timeout",
        tamanho=5000, recv_window=3000, drop_data=drop_ids({2}),
        observar=("Com janela de 3000 B só cabe 1 pacote em voo (inflight + 1500 < 3000). Sem "
                  "pacotes posteriores, nenhuma perda pode ser detectada por ACKs: cada perda custa "
                  "um timeout inteiro. Compare a duração com o cenário de retransmissão rápida."),
    ),
    "buffer-de-reordenacao-do-simulador": dict(
        titulo="--pkts_to_reorder 3: pacotes retidos no buffer do código-base",
        tamanho=6000, recv_window=7500, pkts_to_reorder=3, seed=4,
        observar=("Com --pkts_to_reorder k, start_sender só põe pacotes na rede quando acumula k "
                  "deles e então os embaralha. No fim da transferência podem sobrar pacotes retidos: "
                  "nenhum ACK chega, ocorre timeout e os bytes são retransmitidos. Por isso aparecem "
                  "timeouts mesmo sem perdas quando se usa essa opção."),
    ),
}
