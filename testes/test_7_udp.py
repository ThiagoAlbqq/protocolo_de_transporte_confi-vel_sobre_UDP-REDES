"""Categoria UDP — o programa real (start_sender/start_receiver) sobre sockets UDP locais."""
import glob
import os
import socket
import subprocess
import sys
import time

import pytest

from netsim import random_text

CATEGORIA = "udp"
AQUI = os.path.dirname(os.path.abspath(__file__))


def porta_livre():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def espera_receptor(porta, limite=10.0):
    """Envia um FIN 'vazio' até o receptor existir (sem receptor, o SO devolve ICMP port unreachable)."""
    fim = time.time() + limite
    while time.time() < fim:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("127.0.0.1", porta))
            s.settimeout(0.2)
            try:
                s.send(b'{"type": "fin"}')
                s.recv(1500)
                return
            except socket.timeout:
                return
            except (ConnectionRefusedError, ConnectionResetError):  # Linux/macOS | Windows
                time.sleep(0.1)
    raise AssertionError("o receptor não começou a escutar")


def transferir(impl_path, tmp_path, dados, *args, limite=90):
    arq = tmp_path / "entrada.txt"
    arq.write_text(dados)
    prefixo = str(tmp_path / "recebido")
    porta = porta_livre()
    rec = subprocess.Popen([sys.executable, os.path.join(AQUI, "_udp_receptor.py"), impl_path,
                            "127.0.0.1", str(porta), prefixo],
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        espera_receptor(porta)
        env = subprocess.run([sys.executable, impl_path, "--ip", "127.0.0.1", "--port", str(porta),
                              "--sendfile", str(arq), *args, "sender"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=limite)
        time.sleep(0.2)
    finally:
        rec.kill()
        _, err_rec = rec.communicate()
    assert env.returncode == 0, f"o emissor terminou com código {env.returncode}:\n{env.stderr.decode()[-1500:]}"
    saidas = [open(p).read() for p in glob.glob(prefixo + ".*")]
    recebido = max(saidas, key=len) if saidas else ""
    assert recebido == dados, (f"dados recebidos ({len(recebido)} bytes) diferem dos enviados ({len(dados)} bytes)\n"
                               + err_rec.decode()[-1500:])


@pytest.mark.tempo_limite(120)
def test_udp_sem_perdas(impl_path, tmp_path):
    transferir(impl_path, tmp_path, random_text(200_000, 1))


@pytest.mark.tempo_limite(120)
def test_udp_com_perdas(impl_path, tmp_path):
    transferir(impl_path, tmp_path, random_text(50_000, 2), "--simloss", "0.1")


@pytest.mark.tempo_limite(120)
def test_udp_com_perdas_e_reordenacao(impl_path, tmp_path):
    transferir(impl_path, tmp_path, random_text(50_000, 3), "--simloss", "0.05", "--pkts_to_reorder", "5")
