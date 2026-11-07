"""
Configuração comum dos testes.

Variáveis de ambiente:
  TRANSPORT_IMPL     caminho do transport.py a ser testado (padrão: ../src/transport.py)
  SEMENTE_CORRECAO   inteiro somado a todas as sementes aleatórias (o professor pode
                     trocá-la na correção para evitar soluções "decoradas")
"""
import os
import signal
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from netsim import load_impl, default_impl_path  # noqa: E402

SEMENTE = int(os.environ.get("SEMENTE_CORRECAO", "0"))
TEMPO_LIMITE_PADRAO = 20  # segundos por teste


def pytest_configure(config):
    config.addinivalue_line("markers", "tempo_limite(segundos): tempo máximo do teste")


@pytest.fixture(scope="session")
def impl():
    return load_impl(default_impl_path())


@pytest.fixture(scope="session")
def impl_path():
    return default_impl_path()


@pytest.fixture(autouse=True)
def _tempo_limite(request):
    """Interrompe testes que entram em laço infinito (apenas Unix)."""
    if not hasattr(signal, "SIGALRM"):
        yield
        return
    m = request.node.get_closest_marker("tempo_limite")
    limite = m.args[0] if m else TEMPO_LIMITE_PADRAO

    def estourou(signum, frame):
        raise TimeoutError(f"teste excedeu {limite}s (laço infinito?)")

    antigo = signal.signal(signal.SIGALRM, estourou)
    signal.alarm(limite)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, antigo)
