"""
Executa o start_receiver ORIGINAL do aluno, mas grava em arquivo os dados que
o Receiver entrega à aplicação (o código-base só imprime um resumo).

Uso: python _udp_receptor.py <transport.py> <ip> <porta> <prefixo_saida>
"""
import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from netsim import load_impl  # noqa: E402


def main():
    impl_path, ip, port, prefixo = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
    mod = load_impl(impl_path)
    Original = mod.Receiver
    contador = itertools.count()

    class Gravador(Original):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._arq = f"{prefixo}.{next(contador)}"
            open(self._arq, "w").close()

        def data_packet(self, seq_range, data):
            sacks, app = super().data_packet(seq_range, data)
            with open(self._arq, "a") as f:
                f.write(app)
            return sacks, app

    mod.Receiver = Gravador
    mod.start_receiver(ip, port)


if __name__ == "__main__":
    main()
