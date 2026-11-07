"""Categoria RECEPTOR — testes unitários da classe Receiver."""
import json
import random

import pytest

from conftest import SEMENTE
from netsim import merge, random_text

CATEGORIA = "receptor"

DADOS = random_text(5000, seed=42)


def norm(sacks):
    """Converte a lista de SACKs para [(int, int), ...] verificando o formato."""
    assert isinstance(sacks, (list, tuple)), f"SACKs devem ser uma lista, veio {type(sacks).__name__}"
    out = []
    for r in sacks:
        assert len(r) == 2, f"cada SACK deve ter 2 números (início, fim), veio {r!r}"
        out.append((int(r[0]), int(r[1])))
    return out


def rx(r, s, e):
    """Entrega o pacote [s, e) de DADOS ao receptor e normaliza a saída."""
    sacks, app = r.data_packet((s, e), DADOS[s:e])
    assert isinstance(app, str), "os dados para a aplicação devem ser str"
    return norm(sacks), app


def test_pacote_unico_em_ordem(impl):
    r = impl.Receiver()
    sacks, app = rx(r, 0, 100)
    assert app == DADOS[0:100]
    assert sacks == [(0, 100)]


def test_varios_pacotes_em_ordem(impl):
    r = impl.Receiver()
    total = ""
    for s in range(0, 3600, 1200):
        sacks, app = rx(r, s, s + 1200)
        assert app == DADOS[s:s + 1200], "pacote em ordem deve ser entregue imediatamente"
        assert sacks == [(0, s + 1200)]
        total += app
    assert total == DADOS[:3600]


def test_pacote_fora_de_ordem_fica_no_buffer(impl):
    r = impl.Receiver()
    sacks, app = rx(r, 100, 200)
    assert app == "", "bytes depois de uma lacuna NÃO podem ser entregues à aplicação"
    assert sacks == [(100, 200)]


def test_lacuna_preenchida_entrega_tudo(impl):
    r = impl.Receiver()
    rx(r, 100, 200)
    sacks, app = rx(r, 0, 100)
    assert app == DADOS[0:200], "ao fechar a lacuna, tudo o que ficou contíguo deve ser entregue"
    assert sacks == [(0, 200)]


def test_exemplo_do_enunciado(impl):
    r = impl.Receiver()
    entregue = ""
    for s, e in [(0, 100), (100, 200), (500, 600), (300, 400), (700, 800)]:
        sacks, app = rx(r, s, e)
        entregue += app
    assert sacks == [(0, 200), (300, 400), (500, 600), (700, 800)]
    assert entregue == DADOS[:200]
    for s, e in [(200, 300), (400, 500)]:
        sacks, app = rx(r, s, e)
        entregue += app
    assert sacks == [(0, 600), (700, 800)]
    assert entregue == DADOS[:600]


def test_sacks_ordenados_e_unidos(impl):
    r = impl.Receiver()
    rx(r, 300, 400)
    rx(r, 200, 300)
    sacks, app = rx(r, 100, 200)
    assert app == ""
    assert sacks == [(100, 400)], "intervalos adjacentes devem ser unidos e a lista ordenada"


def test_pacote_duplicado_nao_reentrega(impl):
    r = impl.Receiver()
    s1, a1 = rx(r, 0, 100)
    s2, a2 = rx(r, 0, 100)
    assert a1 == DADOS[:100]
    assert a2 == "", "um pacote repetido não pode entregar dados de novo"
    assert s2 == [(0, 100)]


def test_duplicado_fora_de_ordem(impl):
    r = impl.Receiver()
    entregue = ""
    for s, e in [(200, 300), (200, 300), (100, 200), (200, 300), (0, 100), (100, 200)]:
        _, app = rx(r, s, e)
        entregue += app
    assert entregue == DADOS[:300]


def test_sobreposicao_parcial_apos_entrega(impl):
    r = impl.Receiver()
    rx(r, 0, 100)
    sacks, app = rx(r, 50, 150)
    assert app == DADOS[100:150], "só a parte nova (100-150) deve ser entregue"
    assert sacks == [(0, 150)]


def test_sobreposicao_no_buffer(impl):
    r = impl.Receiver()
    entregue = ""
    for s, e in [(100, 200), (150, 300), (250, 280), (0, 100)]:
        _, app = rx(r, s, e)
        entregue += app
    assert entregue == DADOS[:300]


def test_pacote_antigo_apos_entrega(impl):
    r = impl.Receiver()
    _, app = rx(r, 0, 300)
    assert app == DADOS[:300]
    sacks, app = rx(r, 100, 200)
    assert app == ""
    assert sacks == [(0, 300)]


def test_muitas_lacunas(impl):
    r = impl.Receiver()
    entregue = ""
    for i in range(1, 1000, 2):
        sacks, app = rx(r, i, i + 1)
        entregue += app
    assert entregue == ""
    assert len(sacks) == 500
    for i in range(0, 1000, 2):
        sacks, app = rx(r, i, i + 1)
        entregue += app
    assert entregue == DADOS[:1000]
    assert sacks == [(0, 1000)]


@pytest.mark.parametrize("semente", [1, 2, 3])
def test_aleatorio_fragmentacao_ordem_e_duplicatas(impl, semente):
    rng = random.Random(semente + SEMENTE)
    n = len(DADOS)
    # fatias aleatórias (com sobreposições) que cobrem todos os dados
    fatias, pos = [], 0
    while pos < n:
        tam = rng.randint(1, 400)
        fatias.append((pos, min(n, pos + tam)))
        pos += tam
    for _ in range(len(fatias) // 2):
        a = rng.randrange(n)
        fatias.append((a, min(n, a + rng.randint(1, 300))))
    rng.shuffle(fatias)

    r = impl.Receiver()
    recebidos, entregue = [], ""
    for s, e in fatias:
        sacks, app = rx(r, s, e)
        entregue += app
        recebidos = merge(recebidos + [(s, e)])
        assert sacks == recebidos, f"após receber {(s, e)} os SACKs deveriam ser {recebidos}"
        prefixo = recebidos[0][1] if recebidos[0][0] == 0 else 0
        assert entregue == DADOS[:prefixo], "a aplicação deve ter recebido exatamente o prefixo contíguo"
    assert entregue == DADOS
    assert sacks == [(0, n)]


def test_formato_serializavel_em_json(impl):
    r = impl.Receiver()
    sacks, app = r.data_packet((0, 10), DADOS[:10])
    texto = json.dumps({"type": "ack", "sacks": sacks, "id": 0})
    volta = json.loads(texto)["sacks"]
    assert [tuple(x) for x in volta] == [(0, 10)]


def test_finish_apos_transferencia(impl):
    r = impl.Receiver()
    entregue = ""
    for s in [100, 0, 300, 200, 500, 400, 700, 600, 900, 800]:
        entregue += rx(r, s, s + 100)[1]
    assert entregue == DADOS[:1000]
    r.finish()  # não deve lançar exceção


def test_receptores_sao_independentes(impl):
    """Dois objetos Receiver não podem compartilhar estado (cuidado com atributos de classe!)."""
    a = impl.Receiver()
    b = impl.Receiver()
    rx(a, 0, 100)
    sacks, app = rx(b, 100, 200)
    assert app == ""
    assert sacks == [(100, 200)]
