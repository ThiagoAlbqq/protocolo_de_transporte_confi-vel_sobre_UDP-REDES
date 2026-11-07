"""Categoria EFICIÊNCIA — a implementação está correta E não desperdiça a rede?"""
import pytest

from conftest import SEMENTE
from netsim import Simulation, random_text
from test_2_emissor import drenar

CATEGORIA = "eficiencia"


def test_sem_perdas_nao_retransmite_nem_estoura_timeout(impl):
    res = Simulation(impl, random_text(200_000, 1)).run()
    assert res.ok, res.explain()
    assert res.retransmitted_bytes == 0, f"{res.retransmitted_bytes} bytes retransmitidos sem nenhuma perda"
    assert res.timeouts == 0, f"{res.timeouts} timeouts sem nenhuma perda"


def test_usa_a_janela_inteira(impl):
    """Com janela de 15000 bytes, vários pacotes devem estar em voo ao mesmo tempo
    (pare-e-espere levaria ~84 RTTs para 100 KB)."""
    res = Simulation(impl, random_text(100_000, 2)).run()
    assert res.ok, res.explain()
    rtts = res.final_time / 2.0
    assert rtts < 20, f"a transferência levou {rtts:.0f} RTTs; o emissor não está enchendo a janela"


@pytest.mark.parametrize("semente", [1, 2, 3])
def test_vazao_com_perdas_isoladas(impl, semente):
    """Com 5% de perda, a retransmissão rápida mantém a transferência quase tão rápida quanto
    sem perdas. Quem só recupera por timeout fica parado RTO a RTO."""
    dados = random_text(200_000, semente)
    base = Simulation(impl, dados).run()
    assert base.ok, base.explain()
    res = Simulation(impl, dados, loss=0.05, ack_loss=0.0, seed=semente + 200 + SEMENTE).run()
    assert res.ok, res.explain()
    razao = res.final_time / base.final_time
    assert razao <= 1.75, (
        f"com 5% de perda a transferência levou {razao:.2f}x o tempo sem perdas ({res.timeouts} timeouts); "
        "as perdas estão sendo recuperadas só por timeout?")


def test_ack_perdido_nao_prende_a_janela(impl):
    """Se o ACK do pacote 1 se perde mas o ACK do pacote 2 mostra (via SACK) que o 1 chegou,
    o pacote 1 também deve sair de 'em voo'."""
    snd = impl.Sender(12000)
    env, _, _ = drenar(snd, 0)
    (i0, r0), (i1, r1), (i2, r2) = env[:3]
    assert snd.ack_packet([[0, r0[1]]], i0) == r0[1] - r0[0]
    liberado = snd.ack_packet([[0, r2[1]]], i2)
    assert liberado == (r1[1] - r1[0]) + (r2[1] - r2[0]), (
        f"o ACK do pacote {i2} confirma {r1} e {r2}; deveria liberar ambos, liberou {liberado}")


@pytest.mark.parametrize("semente", [1, 2])
def test_poucas_retransmissoes_desnecessarias(impl, semente):
    res = Simulation(impl, random_text(150_000, semente), loss=0.1, seed=semente + 300 + SEMENTE).run()
    assert res.ok, res.explain()
    limite = int(1.5 * res.data_dropped * 1200) + 2400
    assert res.retransmitted_bytes <= limite, (
        f"{res.retransmitted_bytes} bytes retransmitidos para {res.data_dropped} pacotes perdidos (limite {limite})")
