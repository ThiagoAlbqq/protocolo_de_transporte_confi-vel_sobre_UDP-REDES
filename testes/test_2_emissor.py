"""Categoria EMISSOR — comportamento básico da classe Sender (sem perdas)."""
from netsim import merge, PAYLOAD_SIZE

CATEGORIA = "emissor"


def drenar(sender, prox_id, limite=2000):
    """Chama send() até devolver intervalo vazio ou None.
    Devolve (lista de (id, (s, e)), último retorno, próximo id)."""
    enviados = []
    for _ in range(limite):
        seq = sender.send(prox_id)
        if seq is None or seq[0] == seq[1]:
            return enviados, seq, prox_id
        enviados.append((prox_id, (int(seq[0]), int(seq[1]))))
        prox_id += 1
    raise AssertionError(f"send() devolveu {limite} intervalos seguidos sem nunca esperar por ACKs")


def test_primeiro_pacote_comeca_em_zero(impl):
    seq = impl.Sender(5000).send(0)
    assert seq is not None
    s, e = seq
    assert s == 0 and 0 < e <= PAYLOAD_SIZE


def test_pacotes_contiguos_cobrem_todos_os_dados(impl):
    env, _, _ = drenar(impl.Sender(10000), 0)
    faixas = [r for _, r in env]
    assert faixas, "nenhum pacote foi enviado"
    assert faixas[0][0] == 0
    for (s1, e1), (s2, e2) in zip(faixas, faixas[1:]):
        assert e1 == s2, f"dados novos devem ser enviados em sequência: {(s1, e1)} seguido de {(s2, e2)}"
    assert merge(faixas) == [(0, 10000)]


def test_respeita_payload_e_fim_dos_dados(impl):
    env, _, _ = drenar(impl.Sender(2401), 0)
    for _, (s, e) in env:
        assert 0 < e - s <= PAYLOAD_SIZE
        assert e <= 2401
    assert merge([r for _, r in env]) == [(0, 2401)]


def test_intervalo_vazio_quando_tudo_esta_em_voo(impl):
    snd = impl.Sender(3000)
    _, ultimo, pid = drenar(snd, 0)
    assert ultimo is not None, "send() não pode devolver None enquanto há bytes não confirmados"
    assert ultimo[0] == ultimo[1]
    seq = snd.send(pid)
    assert seq is not None and seq[0] == seq[1], "sem ACKs novos, deve continuar devolvendo intervalo vazio"


def test_none_apos_tudo_confirmado(impl):
    snd = impl.Sender(3000)
    env, _, pid = drenar(snd, 0)
    assert merge([r for _, r in env]) == [(0, 3000)]
    recebido = []
    for i, (s, e) in env:
        recebido = merge(recebido + [(s, e)])
        snd.ack_packet([list(x) for x in recebido], i)
    assert snd.send(pid) is None


def test_nao_termina_com_bytes_pendentes(impl):
    snd = impl.Sender(3000)
    env, _, pid = drenar(snd, 0)
    recebido = []
    for i, (s, e) in env[:-1]:
        recebido = merge(recebido + [(s, e)])
        snd.ack_packet([list(x) for x in recebido], i)
    assert snd.send(pid) is not None, "o último pacote ainda não foi confirmado"


def test_dados_vazios(impl):
    assert impl.Sender(0).send(0) is None, "sem dados, não há nada a enviar nem a confirmar"
    assert tuple(impl.Sender(1).send(0)) == (0, 1)


def test_arquivo_menor_que_um_pacote(impl):
    snd = impl.Sender(10)
    assert tuple(snd.send(0)) == (0, 10)
    seq = snd.send(1)
    assert seq is not None and seq[0] == seq[1]
    assert snd.ack_packet([[0, 10]], 0) == 10
    assert snd.send(1) is None


def test_ack_packet_retorna_bytes_do_pacote(impl):
    snd = impl.Sender(3000)
    env, _, _ = drenar(snd, 0)
    assert merge([r for _, r in env]) == [(0, 3000)]
    recebido = []
    for i, (s, e) in env:
        recebido = merge(recebido + [(s, e)])
        liberado = snd.ack_packet([list(x) for x in recebido], i)
        assert isinstance(liberado, int)
        assert liberado == e - s, f"ACK do pacote {i} {(s, e)} deveria liberar {e - s} bytes, liberou {liberado}"


def test_ack_repetido_retorna_zero(impl):
    snd = impl.Sender(3000)
    s, e = snd.send(0)
    assert snd.ack_packet([[s, e]], 0) == e - s
    assert snd.ack_packet([[s, e]], 0) == 0, "o valor devolvido é INCREMENTAL: o mesmo pacote não conta duas vezes"


def test_janela_desliza_apos_ack(impl):
    snd = impl.Sender(10000)
    a = snd.send(0)
    b = snd.send(1)
    snd.ack_packet([[0, int(b[1])]], 0)
    c = snd.send(2)
    assert c is not None and c[0] == b[1], "após um ACK, o emissor deve continuar com dados novos"


def test_nao_reenvia_bytes_ja_confirmados(impl):
    snd = impl.Sender(6000)
    env, _, pid = drenar(snd, 0)
    faixas = dict(env)
    perdido = env[1][0]
    recebido = []
    for i, r in env:
        if i == perdido:
            continue
        recebido = merge(recebido + [r])
        snd.ack_packet([list(x) for x in recebido], i)
    reenv, ultimo, pid = drenar(snd, pid)
    if not reenv:
        snd.timeout()
        reenv, ultimo, pid = drenar(snd, pid)
    assert reenv, "o pacote perdido nunca foi retransmitido"
    assert merge([r for _, r in reenv]) == [faixas[perdido]], (
        f"só deveria retransmitir {faixas[perdido]}; retransmitiu {[r for _, r in reenv]}")
