"""Categoria PERDAS — detecção de perdas, retransmissão e timeout."""
from conftest import SEMENTE
from netsim import (Simulation, drop_ack_ids, drop_first_k_containing, drop_ids, merge,
                    random_text)
from test_2_emissor import drenar

CATEGORIA = "perdas"


def _seis_pacotes_com_perda_do_segundo(impl):
    """Envia 7200 bytes (6 pacotes), perde o 2º e entrega os ACKs dos demais
    exatamente como o Receiver real os geraria. Devolve (sender, envios, retornos, próximo id)."""
    snd = impl.Sender(7200)
    env, _, pid = drenar(snd, 0)
    assert len(env) >= 3
    perdido = env[1]
    recebido, retornos = [], []
    for i, r in env:
        if (i, r) == perdido:
            continue
        recebido = merge(recebido + [r])
        retornos.append(snd.ack_packet([list(x) for x in recebido], i))
    return snd, env, perdido, retornos, pid


def test_perda_detectada_por_acks_posteriores(impl):
    """ack_packet deve devolver também os bytes dos pacotes considerados perdidos."""
    snd, env, perdido, retornos, _ = _seis_pacotes_com_perda_do_segundo(impl)
    assert sum(retornos) == 7200, (
        f"após 4 ACKs de pacotes posteriores, o pacote {perdido[1]} deveria ter sido dado como perdido; "
        f"soma dos retornos de ack_packet = {sum(retornos)}, esperado 7200")


def test_retransmissao_rapida_sem_timeout(impl):
    """Os ACKs posteriores bastam para retransmitir — sem esperar o timeout."""
    snd, env, perdido, _, pid = _seis_pacotes_com_perda_do_segundo(impl)
    reenv, _, _ = drenar(snd, pid)
    assert merge([r for _, r in reenv]) == [perdido[1]], (
        f"esperava retransmitir {perdido[1]} sem timeout; send() devolveu {[r for _, r in reenv]}")


def test_sem_dupla_contagem_quando_ack_atrasado_chega(impl):
    """Pacote dado como perdido cujo ACK chega depois: não pode ser descontado duas vezes."""
    snd, env, perdido, retornos, _ = _seis_pacotes_com_perda_do_segundo(impl)
    tardio = snd.ack_packet([[0, 7200]], perdido[0])
    assert sum(retornos) + tardio == 7200, (
        f"cada byte enviado deve sair de 'em voo' exatamente uma vez; total devolvido = {sum(retornos) + tardio}")


def test_perda_isolada_recuperada_sem_timeout(impl):
    """Um único pacote perdido no meio da transferência: os ACKs seguintes devem bastar."""
    res = Simulation(impl, random_text(100_000, 11), drop_data=drop_ids({10})).run()
    assert res.ok, res.explain()
    assert res.timeouts == 0, f"houve {res.timeouts} timeout(s): a perda não foi detectada pelos ACKs posteriores"


def test_perdas_espalhadas_recuperadas_sem_timeout(impl):
    res = Simulation(impl, random_text(100_000, 12), drop_data=drop_ids({5, 30, 55})).run()
    assert res.ok, res.explain()
    assert res.timeouts == 0, f"houve {res.timeouts} timeout(s): as perdas não foram detectadas pelos ACKs posteriores"


def test_timeout_retransmite_tudo_que_estava_em_voo(impl):
    snd = impl.Sender(3000)
    env, _, pid = drenar(snd, 0)
    snd.timeout()
    reenv, _, _ = drenar(snd, pid)
    assert merge([r for _, r in reenv]) == [(0, 3000)]


def test_ack_atrasado_apos_timeout_retorna_zero(impl):
    """start_sender zera `inflight` no timeout; um ACK antigo que chega depois não pode descontar nada."""
    snd = impl.Sender(3000)
    env, _, pid = drenar(snd, 0)
    snd.timeout()
    i0, r0 = env[0]
    assert snd.ack_packet([list(r0)], i0) == 0, "no programa real isto deixaria inflight negativo (AssertionError)"
    reenv, _, _ = drenar(snd, pid)
    assert merge([r for _, r in reenv]) == [(r0[1], 3000)], "bytes confirmados pelo ACK tardio não devem ser reenviados"


def test_retransmissao_tambem_perdida(impl):
    dados = random_text(20000, 1)
    res = Simulation(impl, dados, drop_data=drop_first_k_containing(5000, 3)).run()
    assert res.ok, res.explain()


def test_perda_do_ultimo_pacote(impl):
    """Perda na cauda: não há ACKs posteriores, só o timeout recupera."""
    dados = random_text(10000, 2)
    res = Simulation(impl, dados, drop_data=drop_first_k_containing(len(dados) - 1, 1)).run()
    assert res.ok, res.explain()


def test_perda_do_primeiro_pacote(impl):
    res = Simulation(impl, random_text(20000, 3), drop_data=drop_ids({0})).run()
    assert res.ok, res.explain()


def test_rajada_de_perdas(impl):
    res = Simulation(impl, random_text(30000, 4), drop_data=drop_ids(range(3, 13))).run()
    assert res.ok, res.explain()


def test_todos_os_acks_de_uma_janela_perdidos(impl):
    res = Simulation(impl, random_text(30000, 5), drop_ack=drop_ack_ids(range(0, 12))).run()
    assert res.ok, res.explain()


def test_perdas_aleatorias_sem_dupla_contagem(impl):
    for s in range(3):
        res = Simulation(impl, random_text(40000, 6), loss=0.2, seed=100 + s + SEMENTE).run()
        assert res.ok, res.explain()
