"""Categoria INTEGRAÇÃO — Sender + Receiver juntos no simulador, sem reordenação."""
import pytest

from conftest import SEMENTE
from netsim import Simulation, random_text

CATEGORIA = "integracao"


@pytest.mark.parametrize("tamanho", [1, 1199, 1200, 1201, 50_000])
def test_sem_perdas(impl, tamanho):
    res = Simulation(impl, random_text(tamanho, tamanho)).run()
    assert res.ok, res.explain()


@pytest.mark.parametrize("perda", [0.01, 0.05, 0.1, 0.2, 0.3])
@pytest.mark.parametrize("semente", [1, 2])
def test_perdas_aleatorias(impl, perda, semente):
    res = Simulation(impl, random_text(100_000, semente), loss=perda, seed=semente + SEMENTE).run()
    assert res.ok, res.explain()


@pytest.mark.parametrize("semente", [1, 2])
def test_metade_dos_pacotes_perdidos(impl, semente):
    res = Simulation(impl, random_text(30_000, semente), loss=0.5, seed=semente + SEMENTE).run()
    assert res.ok, res.explain()


def test_perda_extrema_90_por_cento(impl):
    res = Simulation(impl, random_text(2_500, 9), loss=0.9, seed=9 + SEMENTE,
                     max_consecutive_timeouts=2000).run()
    assert res.ok, res.explain()


def test_janela_minima_pare_e_espere(impl):
    """Janela de 3000 bytes: cabe apenas um pacote em voo por vez."""
    res = Simulation(impl, random_text(30_000, 3), recv_window=3000, loss=0.1, seed=3 + SEMENTE).run()
    assert res.ok, res.explain()


def test_janela_grande(impl):
    res = Simulation(impl, random_text(200_000, 4), recv_window=100_000, loss=0.1, seed=4 + SEMENTE).run()
    assert res.ok, res.explain()


def test_somente_acks_perdidos(impl):
    res = Simulation(impl, random_text(100_000, 5), loss=0.0, ack_loss=0.3, seed=5 + SEMENTE).run()
    assert res.ok, res.explain()


@pytest.mark.parametrize("semente", [1, 2])
def test_nunca_reenvia_bytes_confirmados(impl, semente):
    res = Simulation(impl, random_text(100_000, 7), loss=0.1, seed=semente + 50 + SEMENTE).run()
    assert res.ok, res.explain()
    assert not res.violations, "send() devolveu bytes que já haviam sido confirmados: " + "; ".join(res.violations[:3])
