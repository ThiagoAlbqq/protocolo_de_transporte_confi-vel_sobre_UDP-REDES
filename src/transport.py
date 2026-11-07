import argparse
import json
from typing import Any, Dict, List, Optional, Tuple
import random
import socket

# Note: In this starter code, we annotate types where
# appropriate. While it is optional, both in python and for this
# course, we recommend it since it makes programming easier.

# =====================================================================
#  TRABALHO: PROTOCOLO DE TRANSPORTE CONFIÁVEL SOBRE UDP
#
#  Você deve completar APENAS as classes Receiver e Sender (marcadas
#  com TODO). Pode criar funções auxiliares, atributos e métodos
#  extras à vontade. NÃO altere start_receiver, start_sender e main:
#  os testes usam essas funções exatamente como estão.
#
#  Não use bibliotecas que já resolvam o problema (ex.: pacotes de
#  "interval trees"/"range sets"). A biblioteca padrão básica (listas,
#  dicionários, tuplas, sorted, etc.) é suficiente.
#
#  Como testar:   cd testes && python -m pytest -q
#  Nota estimada: cd testes && python corrigir.py
#  Visualizar:    cd visualizacao && python visualizar.py --lista
# =====================================================================

# The maximum size of the data contained within one packet
payload_size = 1200
# The maximum size of a packet including all the JSON formatting
packet_size = 1500


def merge_intervals(ranges: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    '''Une intervalos sobrepostos ou adjacentes, ordenando por início.'''
    rs = sorted((int(s), int(e)) for s, e in ranges if int(e) > int(s))
    out: List[Tuple[int, int]] = []
    for s, e in rs:
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def merge_chunks(chunks: List[Tuple[int, int, str]]) -> List[Tuple[int, int, str]]:
    '''Une pedaços de dados sobrepostos ou adjacentes, preservando o texto exato.'''
    if not chunks:
        return []
    sorted_chunks = sorted(chunks, key=lambda x: (x[0], x[1]))
    merged = [sorted_chunks[0]]
    for s, e, d in sorted_chunks[1:]:
        prev_s, prev_e, prev_d = merged[-1]
        if s <= prev_e:
            if e > prev_e:
                merged[-1] = (prev_s, e, prev_d + d[prev_e - s:])
        else:
            merged.append((s, e, d))
    return merged


def subtract_intervals(s: int, e: int, covered: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    '''Subtrai os intervalos em `covered` de [s, e), devolvendo os pedaços não cobertos.'''
    rem = [(s, e)]
    for cs, ce in covered:
        new_rem: List[Tuple[int, int]] = []
        for rs, re in rem:
            if ce <= rs or cs >= re:
                new_rem.append((rs, re))
            else:
                if rs < cs:
                    new_rem.append((rs, cs))
                if ce < re:
                    new_rem.append((ce, re))
        rem = new_rem
    return [r for r in rem if r[1] > r[0]]


def is_fully_covered(rng: Tuple[int, int], covered: List[Tuple[int, int]]) -> bool:
    '''Verifica se [rng[0], rng[1]) está completamente contido nos intervalos de covered.'''
    s, e = rng
    for cs, ce in covered:
        if cs <= s and e <= ce:
            return True
    return False


class Receiver:
    def __init__(self):
        '''Chamado uma vez por emissor (um objeto por conexão).'''
        self.delivered_up_to: int = 0
        self.sacks: List[Tuple[int, int]] = []
        self.buffer: List[Tuple[int, int, str]] = []

    def data_packet(self, seq_range: Tuple[int, int], data: str) -> Tuple[List[Tuple[int, int]], str]:
        '''Chamado sempre que um pacote de dados chega.'''
        s, e = int(seq_range[0]), int(seq_range[1])
        if e <= s:
            return (self.sacks, '')

        # Atualiza a lista de todos os intervalos recebidos
        self.sacks = merge_intervals(self.sacks + [(s, e)])

        # Se já foi tudo entregue, não há nada a bufferizar nem a entregar
        if e <= self.delivered_up_to:
            return (self.sacks, '')

        # Descarta eventual prefixo que já foi entregue à aplicação
        if s < self.delivered_up_to:
            data = data[self.delivered_up_to - s:]
            s = self.delivered_up_to

        # Mescla no buffer de dados aguardando entrega
        self.buffer = merge_chunks(self.buffer + [(s, e, data)])

        # Se a cabeça do buffer agora começa exatamente onde parou a entrega
        app_data = ''
        if self.buffer and self.buffer[0][0] == self.delivered_up_to:
            first_s, first_e, first_d = self.buffer.pop(0)
            self.delivered_up_to = first_e
            app_data = first_d

        return (self.sacks, app_data)

    def finish(self):
        '''Chamado quando chega o pacote `fin` do emissor.'''
        pass


class PacketInfo:
    '''Metadados de uma transmissão individual de pacote.'''
    def __init__(self, pid: int, seq: Tuple[int, int]):
        self.pid: int = pid
        self.seq: Tuple[int, int] = seq
        self.size: int = seq[1] - seq[0]
        self.in_flight: bool = True
        self.status: str = 'in_flight'  # 'in_flight', 'acked', 'lost'


class Sender:
    def __init__(self, data_len: int):
        '''`data_len` é o número total de bytes a enviar (sequências 0 até data_len - 1).'''
        self.data_len: int = data_len
        self.next_unsent: int = 0
        self.confirmed_sacks: List[Tuple[int, int]] = []
        self.largest_acked_id: int = -1
        self.packets: Dict[int, PacketInfo] = {}
        self.retransmit_queue: List[Tuple[int, int]] = []

    def timeout(self):
        '''Chamado quando o emissor passa 0,5 s sem receber nenhum ACK.
        start_sender já zerou inflight antes de chamar este método.
        '''
        # Como inflight foi zerado pelo chamador, todos os pacotes em voo
        # deixam de contar como em voo. Seus bytes não confirmados devem ser retransmitidos.
        for p in self.packets.values():
            if p.in_flight:
                p.in_flight = False
                if not is_fully_covered(p.seq, self.confirmed_sacks):
                    p.status = 'lost'
                    unconf = subtract_intervals(p.seq[0], p.seq[1], self.confirmed_sacks)
                    self.retransmit_queue.extend(unconf)

        if self.retransmit_queue:
            cleaned: List[Tuple[int, int]] = []
            for s, e in self.retransmit_queue:
                cleaned.extend(subtract_intervals(s, e, self.confirmed_sacks))
            self.retransmit_queue = merge_intervals(cleaned)

    def ack_packet(self, sacks: List[Tuple[int, int]], packet_id: int) -> int:
        '''Chamado a cada ACK recebido.'''
        freed = 0
        sacks_tuples = [(int(x[0]), int(x[1])) for x in sacks]
        self.confirmed_sacks = merge_intervals(self.confirmed_sacks + sacks_tuples)

        if packet_id > self.largest_acked_id:
            self.largest_acked_id = packet_id

        # 1. Libera pacotes em voo cujos bytes foram confirmados
        for p in self.packets.values():
            if p.in_flight:
                if is_fully_covered(p.seq, self.confirmed_sacks):
                    p.in_flight = False
                    p.status = 'acked'
                    freed += p.size

        # 2. Retransmissão rápida: pacotes ultrapassados por pelo menos 3 posições
        for p in self.packets.values():
            if p.in_flight and (self.largest_acked_id - p.pid >= 3):
                if not is_fully_covered(p.seq, self.confirmed_sacks):
                    p.in_flight = False
                    p.status = 'lost'
                    freed += p.size
                    unconf = subtract_intervals(p.seq[0], p.seq[1], self.confirmed_sacks)
                    self.retransmit_queue.extend(unconf)

        # Limpa e funde intervalos pendentes na fila de retransmissão
        if self.retransmit_queue:
            cleaned: List[Tuple[int, int]] = []
            for s, e in self.retransmit_queue:
                cleaned.extend(subtract_intervals(s, e, self.confirmed_sacks))
            self.retransmit_queue = merge_intervals(cleaned)

        return freed

    def send(self, packet_id: int) -> Optional[Tuple[int, int]]:
        '''Chamado quando start_sender tem espaço na janela para mandar um pacote.'''
        # Limpa qualquer intervalo que já tenha sido confirmado
        if self.retransmit_queue:
            cleaned: List[Tuple[int, int]] = []
            for s, e in self.retransmit_queue:
                cleaned.extend(subtract_intervals(s, e, self.confirmed_sacks))
            self.retransmit_queue = merge_intervals(cleaned)

        # Prioridade 1: retransmitir lacunas / perdas
        if self.retransmit_queue:
            s, e = self.retransmit_queue.pop(0)
            if e - s > payload_size:
                to_send = (s, s + payload_size)
                self.retransmit_queue.insert(0, (s + payload_size, e))
            else:
                to_send = (s, e)
            self.packets[packet_id] = PacketInfo(packet_id, to_send)
            return to_send

        # Prioridade 2: novos dados nunca enviados
        if self.next_unsent < self.data_len:
            s = self.next_unsent
            e = min(s + payload_size, self.data_len)
            self.next_unsent = e
            to_send = (s, e)
            self.packets[packet_id] = PacketInfo(packet_id, to_send)
            return to_send

        # Prioridade 3: tudo enviado. Tudo confirmado?
        if self.data_len == 0 or (len(self.confirmed_sacks) == 1 and self.confirmed_sacks[0] == (0, self.data_len)):
            return None

        # Há pacotes ainda em trânsito aguardando confirmação ou timeout
        return (0, 0)


# =====================================================================
#  CÓDIGO-BASE — NÃO MODIFIQUE DAQUI PARA BAIXO.
#  Mas LEIA com atenção: é ele quem chama os seus métodos.
#    * start_receiver: recebe pacotes, chama Receiver.data_packet e
#      devolve um ACK {"sacks": ..., "id": ...} para cada pacote.
#    * start_sender: mantém `inflight` (bytes em voo), só chama
#      Sender.send quando `inflight + packet_size < recv_window`,
#      simula perdas (--simloss) e reordenação (--pkts_to_reorder),
#      e chama Sender.timeout após 0,5 s sem ACK.
# =====================================================================

def start_receiver(ip: str, port: int):
    '''Starts a receiver thread. For each source address, we start a new
    `Receiver` class. When a `fin` packet is received, we call the
    `finish` function of that class.

    We start listening on the given IP address and port. By setting
    the IP address to be `0.0.0.0`, you can make it listen on all
    available interfaces. A network interface is typically a device
    connected to a computer that interfaces with the physical world to
    send/receive packets. The WiFi and ethernet cards on personal
    computers are examples of physical interfaces.

    Sometimes, when you start listening on a port and the program
    terminates incorrectly, it might not release the port
    immediately. It might take some time for the port to become
    available again, and you might get an error message saying that it
    could not bind to the desired port. In this case, just pick a
    different port. The old port will become available soon. Also,
    picking a port number below 1024 usually requires special
    permission from the OS. Pick a larger number. Numbers in the
    8000-9000 range are conventional.

    Virtual interfaces also exist. The most common one is `localhost',
    which has the default IP address of `127.0.0.1` (a universal
    constant across most machines). The Mahimahi network emulator also
    creates virtual interfaces that behave like real interfaces, but
    really only emulate a network link in software that shuttles
    packets between different virtual interfaces. Use `ifconfig` in a
    terminal to find out what interfaces exist in your machine or
    inside a Mahimahi shell

    '''

    receivers: Dict[str, Tuple[Receiver, Any]] = {}
    received_data = ''
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server_socket:
        server_socket.bind((ip, port))

        while True:
            print("======= Waiting =======")
            data, addr = server_socket.recvfrom(packet_size)
            if addr not in receivers:
                outfile = None  # open(f'rcvd-{addr[0]}-{addr[1]}', 'w')
                receivers[addr] = (Receiver(), outfile)

            received = json.loads(data.decode())
            if received["type"] == "data":
                # Format check. Real code will have much more
                # carefully designed checks to defend against
                # attacks. Can you think of ways to exploit this
                # transport layer and cause problems at the receiver?
                # This is just for fun. It is not required as part of
                # the assignment.
                assert type(received["seq"]) is list
                assert type(received["seq"][0]) is int and type(received["seq"][1]) is int
                assert type(received["payload"]) is str
                assert len(received["payload"]) <= payload_size

                # Deserialize the packet. Real transport layers use
                # more efficient and standardized ways of packing the
                # data. One option is to use protobufs (look it up)
                # instead of json. Protobufs can automatically design
                # a byte structure given the data structure. However,
                # for an internet standard, we usually want something
                # more custom and hand-designed.
                sacks, app_data = receivers[addr][0].data_packet(tuple(received["seq"]), received["payload"])
                # Note: we immediately write the data to file
                # receivers[addr][1].write(app_data)
                print(f"Received seq: {received['seq']}, id: {received['id']}, sending sacks: {sacks}")
                received_data += app_data

                # Send the ACK
                server_socket.sendto(json.dumps({"type": "ack", "sacks": sacks, "id": received["id"]}).encode(), addr)
            elif received["type"] == "fin":
                receivers[addr][0].finish()
                # Check if the file is received and send fin-ack
                if received_data:
                    print("received data (summary): ", received_data[:100], "...", len(received_data))
                    # print("received file is saved into: ", receivers[addr][1].name)
                    server_socket.sendto(json.dumps({"type": "fin"}).encode(), addr)
                    received_data = ''

                del receivers[addr]

            else:
                assert False


def start_sender(ip: str, port: int, data: str, recv_window: int, simloss: float, pkts_to_reorder: int):
    sender = Sender(len(data))

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client_socket:
        # So we can receive messages
        client_socket.connect((ip, port))
        # When waiting for packets when we call receivefrom, we
        # shouldn't wait more than 500ms
        client_socket.settimeout(0.5)

        # Number of bytes that we think are inflight. We are only
        # including payload bytes here, which is different from how
        # TCP does things
        inflight = 0
        packet_id = 0
        wait = False
        send_buf = []

        while True:
            # Do we have enough room in recv_window to send an entire
            # packet?
            if inflight + packet_size < recv_window and not wait:
                seq = sender.send(packet_id)
                got_fin_ack = False
                if seq is None:
                    # We are done sending
                    # print("#######send_buf#########: ", len(send_buf))
                    if send_buf:
                        random.shuffle(send_buf)
                        for p in send_buf:
                            client_socket.send(p)
                        send_buf = []
                    client_socket.send('{"type": "fin"}'.encode())
                    try:
                        print("======= Final Waiting =======")
                        received = client_socket.recv(packet_size)
                        received = json.loads(received.decode())
                        if received["type"] == "ack":
                            client_socket.send('{"type": "fin"}'.encode())
                            continue
                        elif received["type"] == "fin":
                            print(f"Got FIN-ACK")
                            got_fin_ack = True
                            break
                    except socket.timeout:
                        inflight = 0
                        print("Timeout")
                        sender.timeout()
                        exit(1)
                    if got_fin_ack:
                        break
                    else:
                        continue

                elif seq[1] == seq[0]:
                    # No more packets to send until loss happens. Wait
                    wait = True
                    continue

                assert seq[1] - seq[0] <= payload_size
                assert seq[1] <= len(data)
                print(f"Sending seq: {seq}, id: {packet_id}")

                # Simulate random loss before sending packets
                if random.random() < simloss:
                    print("Dropped!")
                else:
                    pkt_str = json.dumps(
                        {"type": "data", "seq": seq, "id": packet_id, "payload": data[seq[0]:seq[1]]}
                    ).encode()
                    # pkts_to_reorder is a variable that bounds the maximum amount of reordering. To disable reordering, set to 1
                    if len(send_buf) < pkts_to_reorder:
                        send_buf += [pkt_str]

                    if len(send_buf) == pkts_to_reorder:
                        # Randomly shuffle send_buf
                        random.shuffle(send_buf)

                        for p in send_buf:
                            client_socket.send(p)
                        send_buf = []

                inflight += seq[1] - seq[0]
                packet_id += 1

            else:
                wait = False
                # Wait for ACKs
                try:
                    print("======= Waiting =======")
                    received = client_socket.recv(packet_size)
                    received = json.loads(received.decode())
                    assert received["type"] == "ack"

                    print(f"Got ACK sacks: {received['sacks']}, id: {received['id']}")
                    if random.random() < simloss:
                        print("Dropped ack!")
                        continue

                    inflight -= sender.ack_packet(received["sacks"], received["id"])
                    assert inflight >= 0
                except socket.timeout:
                    inflight = 0
                    print("Timeout")
                    sender.timeout()


def main():
    parser = argparse.ArgumentParser(description="Transport assignment")
    parser.add_argument("role", choices=["sender", "receiver"], help="Role to play: 'sender' or 'receiver'")
    parser.add_argument("--ip", type=str, required=True, help="IP address to bind/connect to")
    parser.add_argument("--port", type=int, required=True, help="Port number to bind/connect to")
    parser.add_argument("--sendfile", type=str, required=False,
                        help="If role=sender, the file that contains data to send")
    parser.add_argument("--recv_window", type=int, default=15000, help="Receive window size in bytes")
    parser.add_argument("--simloss", type=float, default=0.0,
                        help="Simulate packet loss. Provide the fraction of packets (0-1) that should be randomly dropped")
    parser.add_argument("--pkts_to_reorder", type=int, default=1, help="Number of packets to shuffle randomly")

    args = parser.parse_args()

    if args.role == "receiver":
        start_receiver(args.ip, args.port)
    else:
        if args.sendfile is None:
            print("No file to send")
            return

        with open(args.sendfile, 'r') as f:
            data = f.read()
            start_sender(args.ip, args.port, data, args.recv_window, args.simloss, args.pkts_to_reorder)


if __name__ == "__main__":
    main()
