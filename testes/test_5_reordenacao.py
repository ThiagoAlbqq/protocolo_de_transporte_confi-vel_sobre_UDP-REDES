"""Categoria REORDENAÇÃO — pacotes chegam fora da ordem de envio."""
import pytest

from conftest import SEMENTE
from netsim import Simulation, random_text

CATEGORIA = "reordenacao"


@pytest.mark.parametrize("k", [2, 3, 5, 10])
def test_reordenacao_sem_perdas(impl, k):
    res = Simulation(impl, random_text(50_000, k), pkts_to_reorder=k, seed=k + SEMENTE).run()
    assert res.ok, res.explain()


@pytest.mark.parametrize("perda", [0.05, 0.1])
@pytest.mark.parametrize("semente", [1, 2])
def test_reordenacao_com_perdas(impl, perda, semente):
    res = Simulation(impl, random_text(50_000, semente), pkts_to_reorder=5, loss=perda,
                     seed=semente + 10 + SEMENTE).run()
    assert res.ok, res.explain()


def test_reordenacao_forte_com_perdas(impl):
    res = Simulation(impl, random_text(50_000, 3), pkts_to_reorder=10, loss=0.2, seed=33 + SEMENTE).run()
    assert res.ok, res.explain()


def test_pacote_atrasado_chega_depois_dos_seguintes(impl):
    res = Simulation(impl, random_text(20_000, 4), extra_delay={2: 0.8}).run()
    assert res.ok, res.explain()


def test_original_atrasado_chega_apos_retransmissao(impl):
    """Atraso grande: o emissor retransmite e depois o original também chega (duplicata)."""
    res = Simulation(impl, random_text(20_000, 5), extra_delay={1: 4.0, 4: 6.0}).run()
    assert res.ok, res.explain()


def test_janela_minima_com_reordenacao(impl):
    res = Simulation(impl, random_text(15_000, 6), recv_window=3000, pkts_to_reorder=3,
                     loss=0.05, seed=6 + SEMENTE).run()
    assert res.ok, res.explain()
