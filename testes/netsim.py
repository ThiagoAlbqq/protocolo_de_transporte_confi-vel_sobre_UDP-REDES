"""
netsim.py — simulador determinístico de rede para o trabalho de transporte.

Este módulo reproduz, em tempo VIRTUAL, exatamente o laço de controle de
`start_sender` / `start_receiver` do código-base (mesma contabilidade de
`inflight`, mesma regra de janela, mesmo tratamento de timeout, mesmo
buffer de reordenação), mas sem sockets. Isso permite:

  * testar a implementação de forma rápida e reprodutível (semente fixa);
  * provocar perdas ESPECÍFICAS (ex.: "perca o pacote de id 3",
    "perca o ACK do pacote 5", "atrase o pacote 2");
  * registrar todos os eventos para gerar visualizações.

Modelo de tempo (unidades arbitrárias):
  * cada envio ocupa `tx_time` unidades do emissor;
  * atraso de propagação em cada sentido = `one_way_delay`;
  * o receptor responde cada pacote de dados imediatamente com um ACK;
  * se o emissor espera mais de `rto` unidades sem ACK, ocorre timeout
    (no código real, 0,5 s sem receber nada).

Uso típico:

    from netsim import load_impl, Simulation
    impl = load_impl("../src/transport.py")
    res = Simulation(impl, dados, loss=0.1, seed=1).run()
    assert res.ok, res.explain()
"""
from __future__ import annotations

import heapq
import importlib.util
import itertools
import json
import os
import random
import sys
import traceback
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

PAYLOAD_SIZE = 1200
PACKET_SIZE = 1500


class SimulationError(Exception):
    """Erro fatal: no programa real, isto derrubaria o emissor/receptor."""


# ---------------------------------------------------------------------------
# Carregamento da implementação a ser testada
# ---------------------------------------------------------------------------
_counter = itertools.count()


def default_impl_path() -> str:
    env = os.environ.get("TRANSPORT_IMPL")
    if env:
        return os.path.abspath(env)
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "src", "transport.py"))


def load_impl(path: Optional[str] = None):
    """Importa um transport.py a partir do caminho (sem depender do sys.path)."""
    path = os.path.abspath(path or default_impl_path())
    name = f"transport_impl_{next(_counter)}"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Utilidades de intervalos
# ---------------------------------------------------------------------------
def merge(ranges) -> List[Tuple[int, int]]:
    rs = sorted((s, e) for s, e in ranges if e > s)
    out: List[Tuple[int, int]] = []
    for s, e in rs:
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def overlap_len(rng: Tuple[int, int], covered: List[Tuple[int, int]]) -> int:
    s, e = rng
    return sum(max(0, min(e, ce) - max(s, cs)) for cs, ce in covered)


# ---------------------------------------------------------------------------
# Fábricas de regras de perda/atraso para cenários roteirizados
# ---------------------------------------------------------------------------
def drop_ids(ids) -> Callable:
    """Perde os pacotes de DADOS com estes ids."""
    ids = set(ids)
    return lambda pid, seq, nth: pid in ids


def drop_ack_ids(ids) -> Callable:
    """Perde os ACKs gerados pelos pacotes com estes ids."""
    ids = set(ids)
    return lambda pid: pid in ids


def drop_first_k_containing(byte: int, k: int) -> Callable:
    """Perde as k primeiras transmissões de qualquer pacote que contenha `byte`."""
    def rule(pid, seq, nth_containing):
        return seq[0] <= byte < seq[1] and nth_containing(byte) <= k
    rule.watch_byte = byte
    return rule


def combine(*rules) -> Callable:
    rules = [r for r in rules if r]
    return lambda *a: any(r(*a) for r in rules)


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------
@dataclass
class Result:
    data: str
    delivered: str = ""
    completed: bool = False
    error: Optional[str] = None
    events: List[dict] = field(default_factory=list)
    timeouts: int = 0
    packets_sent: int = 0          # inclui os "perdidos" pelo simulador
    data_dropped: int = 0
    acks_dropped: int = 0
    bytes_sent: int = 0
    retransmitted_bytes: int = 0
    violations: List[str] = field(default_factory=list)
    final_time: float = 0.0

    @property
    def ok(self) -> bool:
        return self.completed and self.error is None and self.delivered == self.data

    def explain(self) -> str:
        if self.error:
            return f"ERRO: {self.error}"
        if not self.completed:
            return "a transmissão não terminou (send() nunca retornou None)"
        if self.delivered != self.data:
            d, x = self.delivered, self.data
            i = next((i for i in range(min(len(d), len(x))) if d[i] != x[i]), min(len(d), len(x)))
            return (f"dados entregues à aplicação diferem dos enviados: entregues {len(d)} bytes, "
                    f"esperados {len(x)}; primeira divergência no byte {i}")
        return "ok"

    def summary(self) -> str:
        return (f"ok={self.ok} pacotes={self.packets_sent} timeouts={self.timeouts} "
                f"retransmitidos={self.retransmitted_bytes}B perdas_dados={self.data_dropped} "
                f"perdas_ack={self.acks_dropped} tempo={self.final_time:.1f}")


# ---------------------------------------------------------------------------
# Simulação
# ---------------------------------------------------------------------------
class Simulation:
    def __init__(self, impl, data: str, recv_window: int = 15000, loss: float = 0.0,
                 ack_loss: Optional[float] = None, pkts_to_reorder: int = 1, seed: int = 0,
                 drop_data: Optional[Callable] = None, drop_ack: Optional[Callable] = None,
                 extra_delay: Optional[Dict[int, float]] = None,
                 one_way_delay: float = 1.0, tx_time: float = 0.1, rto: float = 5.0,
                 max_consecutive_timeouts: int = 400, max_packets: Optional[int] = None,
                 record: bool = True):
        self.impl = impl
        self.data = data
        self.recv_window = recv_window
        self.loss = loss
        self.ack_loss = loss if ack_loss is None else ack_loss
        self.reorder = max(1, pkts_to_reorder)
        self.rng = random.Random(seed)
        self.drop_data = drop_data
        self.drop_ack = drop_ack
        self.extra_delay = extra_delay or {}
        self.D = one_way_delay
        self.tx = tx_time
        self.rto = rto
        self.max_ct = max_consecutive_timeouts
        npk = len(data) // PAYLOAD_SIZE + 1
        self.max_packets = max_packets or (60 * npk + 2000)
        self.record = record

    # -- registro ----------------------------------------------------------
    def _log(self, **ev):
        if self.record:
            self.res.events.append(ev)

    # -- rede ----------------------------------------------------------------
    def _transmit(self, pkt):
        pid = pkt["id"]
        t = self.now + self.D + self.extra_delay.get(pid, 0.0)
        heapq.heappush(self.heap, (t, next(self.tie), "data", pkt))

    def _deliver_data(self, t, pkt):
        seq = tuple(pkt["seq"])
        try:
            out = self.receiver.data_packet(seq, pkt["payload"])
            sacks, app = out
        except Exception as e:
            raise SimulationError(f"Receiver.data_packet({seq}, ...) lançou {type(e).__name__}: {e}\n"
                                  + traceback.format_exc(limit=-3)) from e
        if not isinstance(app, str):
            raise SimulationError(f"Receiver.data_packet deve devolver dados do tipo str, devolveu {type(app).__name__}")
        try:
            sacks_json = json.loads(json.dumps({"sacks": sacks}))["sacks"]
        except TypeError as e:
            raise SimulationError(f"SACKs não serializáveis em JSON: {sacks!r}") from e
        self.res.delivered += app
        self._log(type="arrive", t=t, id=pkt["id"], seq=seq, delivered=len(app),
                  app_total=len(self.res.delivered), sacks=[tuple(x) for x in sacks_json])
        heapq.heappush(self.heap, (t + self.D, next(self.tie), "ack",
                                   {"id": pkt["id"], "sacks": sacks_json, "t_sent": t}))

    def _next_ack(self, deadline):
        """Processa chegadas ao receptor até achar um ACK com tempo <= deadline."""
        while self.heap:
            t, _, kind, obj = self.heap[0]
            if t > deadline:
                return None
            heapq.heappop(self.heap)
            if kind == "data":
                self._deliver_data(t, obj)
            else:
                return t, obj
        return None

    def _flush(self):
        self.rng.shuffle(self.send_buf)
        for p in self.send_buf:
            self._transmit(p)
        self.send_buf = []

    # -- contagem para regras roteirizadas -------------------------------------
    def _nth_containing(self, byte):
        return self.contain_count.get(byte, 0)

    # -- laço principal (espelho de start_sender) -------------------------------
    def run(self) -> Result:
        self.res = Result(data=self.data)
        try:
            self._run()
        except SimulationError as e:
            self.res.error = str(e)
        self.res.final_time = self.now
        return self.res

    def _call(self, what, fn, *args):
        try:
            return fn(*args)
        except Exception as e:
            raise SimulationError(f"{what} lançou {type(e).__name__}: {e}\n"
                                  + traceback.format_exc(limit=-3)) from e

    def _run(self):
        impl, data, res = self.impl, self.data, self.res
        self.now = 0.0
        self.heap: list = []
        self.tie = itertools.count()
        self.send_buf: list = []
        self.contain_count: Dict[int, int] = {}
        self.receiver = self._call("Receiver()", impl.Receiver)
        sender = self._call("Sender()", impl.Sender, len(data))

        acked_known: List[Tuple[int, int]] = []   # SACKs que o emissor já recebeu
        ever_sent: List[Tuple[int, int]] = []
        inflight = 0
        packet_id = 0
        wait = False
        consecutive_timeouts = 0
        watch = [getattr(r, "watch_byte", None) for r in (self.drop_data,)]

        while True:
            if inflight + PACKET_SIZE < self.recv_window and not wait:
                seq = self._call(f"Sender.send({packet_id})", sender.send, packet_id)
                if seq is None:
                    if self.send_buf:
                        self._flush()
                    # FIN: o receptor processa o que já está a caminho e encerra
                    self._log(type="fin", t=self.now)
                    while self.heap:
                        t, _, kind, obj = heapq.heappop(self.heap)
                        if kind == "data" and t <= self.now + self.D:
                            self._deliver_data(t, obj)
                    self._call("Receiver.finish()", self.receiver.finish)
                    res.completed = True
                    return
                try:
                    s, e = int(seq[0]), int(seq[1])
                    assert len(seq) == 2
                except Exception:
                    raise SimulationError(f"Sender.send deve devolver None ou uma tupla (início, fim); devolveu {seq!r}")
                if e == s:
                    wait = True
                    continue
                if e < s or s < 0:
                    raise SimulationError(f"Sender.send devolveu intervalo inválido {seq!r}")
                if e - s > PAYLOAD_SIZE:
                    raise SimulationError(f"Sender.send devolveu {seq!r}: {e - s} bytes > payload_size ({PAYLOAD_SIZE}) "
                                          "(no programa real: AssertionError)")
                if e > len(data):
                    raise SimulationError(f"Sender.send devolveu {seq!r}, além do fim dos dados ({len(data)}) "
                                          "(no programa real: AssertionError)")
                ov = overlap_len((s, e), acked_known)
                if ov:
                    res.violations.append(f"pacote {packet_id} {(s, e)} reenviou {ov} bytes já confirmados")
                retx = overlap_len((s, e), ever_sent)
                res.retransmitted_bytes += retx
                ever_sent = merge(ever_sent + [(s, e)])
                for b in watch:
                    if b is not None and s <= b < e:
                        self.contain_count[b] = self.contain_count.get(b, 0) + 1

                dropped = False
                if self.drop_data is not None:
                    dropped = bool(self.drop_data(packet_id, (s, e), self._nth_containing))
                elif self.loss and self.rng.random() < self.loss:
                    dropped = True
                pkt = {"type": "data", "seq": [s, e], "id": packet_id, "payload": data[s:e]}
                inflight += e - s
                self._log(type="send", t=self.now, id=packet_id, seq=(s, e), dropped=dropped,
                          retx=retx > 0, inflight=inflight)
                if dropped:
                    res.data_dropped += 1
                else:
                    if len(self.send_buf) < self.reorder:
                        self.send_buf.append(pkt)
                    if len(self.send_buf) == self.reorder:
                        self._flush()
                res.packets_sent += 1
                res.bytes_sent += e - s
                packet_id += 1
                self.now += self.tx
                if res.packets_sent > self.max_packets:
                    raise SimulationError(f"mais de {self.max_packets} pacotes enviados sem terminar "
                                          "(laço infinito ou retransmissões excessivas?)")
            else:
                wait = False
                got = self._next_ack(self.now + self.rto)
                if got is None:
                    self.now += self.rto
                    # entregas ao receptor que ocorreram durante a espera
                    while self.heap and self.heap[0][0] <= self.now and self.heap[0][2] == "data":
                        t, _, _, obj = heapq.heappop(self.heap)
                        self._deliver_data(t, obj)
                    inflight = 0
                    res.timeouts += 1
                    consecutive_timeouts += 1
                    self._log(type="timeout", t=self.now, inflight=0)
                    self._call("Sender.timeout()", sender.timeout)
                    if consecutive_timeouts > self.max_ct:
                        raise SimulationError(f"{self.max_ct} timeouts seguidos sem receber ACK: "
                                              "o emissor parou de transmitir sem ter terminado")
                    continue
                consecutive_timeouts = 0
                t, ack = got
                self.now = max(self.now, t)
                ack_dropped = False
                if self.drop_ack is not None:
                    ack_dropped = bool(self.drop_ack(ack["id"]))
                elif self.ack_loss and self.rng.random() < self.ack_loss:
                    ack_dropped = True
                if ack_dropped:
                    res.acks_dropped += 1
                    self._log(type="ack", t=self.now, t_sent=ack["t_sent"], id=ack["id"],
                              sacks=[tuple(x) for x in ack["sacks"]], dropped=True, freed=0, inflight=inflight)
                    continue
                acked_known = merge(acked_known + [tuple(x) for x in ack["sacks"]])
                freed = self._call(f"Sender.ack_packet({ack['sacks']}, {ack['id']})",
                                   sender.ack_packet, ack["sacks"], ack["id"])
                if not isinstance(freed, int):
                    raise SimulationError(f"Sender.ack_packet deve devolver int, devolveu {freed!r}")
                inflight -= freed
                self._log(type="ack", t=self.now, t_sent=ack["t_sent"], id=ack["id"],
                          sacks=[tuple(x) for x in ack["sacks"]], dropped=False, freed=freed, inflight=inflight)
                if inflight < 0:
                    raise SimulationError(
                        f"inflight ficou negativo ({inflight}) após ack_packet(id={ack['id']}) devolver {freed}: "
                        "bytes contados duas vezes (no programa real: AssertionError)")


def random_text(n: int, seed: int = 0) -> str:
    """Texto ASCII imprimível pseudoaleatório de tamanho n."""
    rng = random.Random(seed)
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,;:!?-\n"
    return "".join(rng.choice(alphabet) for _ in range(n))
