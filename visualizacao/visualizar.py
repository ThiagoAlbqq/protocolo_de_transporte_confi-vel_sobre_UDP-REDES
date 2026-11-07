#!/usr/bin/env python3
"""
visualizar.py — desenha a execução de um cenário do protocolo de transporte.

Para cada cenário gera uma figura com:
  (esquerda)        diagrama de sequência emissor <-> receptor
  (direita, topo)   gráfico tempo x número de sequência
  (direita, base)   bytes em voo ("inflight") x janela
e imprime no terminal um traço textual, evento a evento.

Uso:
    python visualizar.py --lista                      # lista os cenários
    python visualizar.py perda-de-ack                 # um cenário
    python visualizar.py todos                        # todos
    python visualizar.py perda-de-ack --impl ../solucao/transport.py
    python visualizar.py perda-de-ack --sem-texto     # só a figura

Por padrão usa ../src/transport.py (a SUA implementação): é uma ótima
ferramenta de depuração — se a figura não bater com o "o que observar",
há algo a investigar.
"""
import argparse
import os
import sys
import textwrap

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "testes"))

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.gridspec import GridSpec  # noqa: E402

from netsim import Simulation, load_impl, random_text, default_impl_path  # noqa: E402
from cenarios import CENARIOS, TEMPO  # noqa: E402

# Paleta (categórica validada + cor de status "crítico" para perdas/timeout)
AZUL, LARANJA, VERDE, VIOLETA, VERMELHO = "#2a78d6", "#eb6834", "#1baf7a", "#6250d6", "#d03b3b"
TINTA, TINTA2, GRADE, FUNDO = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


def fmt_r(r):
    return f"[{r[0]},{r[1]})"


def fmt_sacks(sacks):
    return "[" + ", ".join(f"{s}-{e}" for s, e in sacks) + "]"


# ---------------------------------------------------------------------------
# Traço textual
# ---------------------------------------------------------------------------
def traco_texto(res):
    linhas = []
    evs = sorted(enumerate(res.events), key=lambda x: (x[1]["t"], x[0]))
    for _, ev in evs:
        t = f"t={ev['t']:6.2f}"
        if ev["type"] == "send":
            tipo = "RETRANSMITE" if ev["retx"] else "envia      "
            extra = "  -> PERDIDO na rede" if ev["dropped"] else ""
            linhas.append(f"{t}  EMISSOR   {tipo} #{ev['id']:<3} {fmt_r(ev['seq']):<14} em voo={ev['inflight']}{extra}")
        elif ev["type"] == "arrive":
            o_que = f"entrega {ev['delivered']} B à aplicação" if ev["delivered"] else "nada a entregar (lacuna ou duplicata)"
            linhas.append(f"{t}  RECEPTOR  recebe #{ev['id']:<3} {fmt_r(ev['seq']):<14} {o_que}; responde SACK {fmt_sacks(ev['sacks'])}")
        elif ev["type"] == "ack":
            if ev["dropped"]:
                linhas.append(f"{t}  EMISSOR   ACK de #{ev['id']} PERDIDO na rede")
            else:
                linhas.append(f"{t}  EMISSOR   ACK de #{ev['id']:<3} SACK {fmt_sacks(ev['sacks'])} -> ack_packet devolveu "
                              f"{ev['freed']} B (em voo={ev['inflight']})")
        elif ev["type"] == "timeout":
            linhas.append(f"{t}  EMISSOR   *** TIMEOUT *** inflight := 0 e Sender.timeout()")
        elif ev["type"] == "fin":
            linhas.append(f"{t}  EMISSOR   send() devolveu None -> envia FIN (fim)")
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Figura
# ---------------------------------------------------------------------------
def desenhar(nome, cen, res, janela, saida):
    evs = res.events
    sends = {e["id"]: e for e in evs if e["type"] == "send"}
    arrives = {e["id"]: e for e in evs if e["type"] == "arrive"}
    acks = [e for e in evs if e["type"] == "ack"]
    timeouts = [e["t"] for e in evs if e["type"] == "timeout"]
    fins = [e["t"] for e in evs if e["type"] == "fin"]
    t_fim = max([e["t"] for e in evs] + [1.0]) + 0.8
    D = TEMPO["one_way_delay"]

    altura = max(7.5, 1.8 + t_fim * 0.78)
    fig = plt.figure(figsize=(16, altura), facecolor=FUNDO)
    gs = GridSpec(2, 2, width_ratios=[1.25, 1], height_ratios=[1.6, 1], figure=fig,
                  left=0.03, right=0.98, top=1 - 1.45 / altura, bottom=0.6 / altura, wspace=0.12, hspace=0.25)
    fig.suptitle(cen["titulo"], x=0.03, ha="left", fontsize=15, fontweight="bold", color=TINTA,
                 y=1 - 0.25 / altura)
    fig.text(0.03, 1 - 0.55 / altura, "\n".join(textwrap.wrap("O que observar: " + cen["observar"], 175)),
             ha="left", va="top", fontsize=9.5, color=TINTA2)

    # ---- diagrama de sequência -------------------------------------------
    ax = fig.add_subplot(gs[:, 0])
    ax.set_facecolor(FUNDO)
    XE, XR = 0.0, 1.0
    for x, rot in [(XE, "EMISSOR"), (XR, "RECEPTOR")]:
        ax.plot([x, x], [0, t_fim], color=TINTA2, lw=2, zorder=1)
        ax.text(x, -0.35, rot, ha="center", va="bottom", fontsize=11, fontweight="bold", color=TINTA)

    for pid, s in sends.items():
        cor = LARANJA if s["retx"] else AZUL
        t0 = s["t"]
        if s["dropped"]:
            ax.annotate("", xy=(0.45, t0 + 0.45 * D), xytext=(XE, t0),
                        arrowprops=dict(arrowstyle="-", color=cor, lw=1.6))
            ax.plot(0.45, t0 + 0.45 * D, marker="X", ms=12, color=VERMELHO, mec=FUNDO, mew=1.5, zorder=5)
            ax.text(0.48, t0 + 0.45 * D, "perdido", color=VERMELHO, fontsize=8, va="center", fontweight="bold")
        elif pid in arrives:
            ax.annotate("", xy=(XR, arrives[pid]["t"]), xytext=(XE, t0),
                        arrowprops=dict(arrowstyle="-|>", color=cor, lw=1.6, mutation_scale=12))
        rot = ("RETX " if s["retx"] else "") + f"#{pid} {fmt_r(s['seq'])}"
        ax.text(XE + 0.015, t0 - 0.03, rot, fontsize=7.5, color=cor, ha="left", va="bottom",
                fontweight="bold" if s["retx"] else "normal",
                bbox=dict(boxstyle="square,pad=0.1", fc=FUNDO, ec="none", alpha=0.9), zorder=4)

    rot_dir, rot_esq = [], []   # rótulos à direita do receptor / à esquerda do emissor
    for pid, a in arrives.items():
        o_que = f"entrega {a['delivered']} B" if a["delivered"] else "guarda/descarta (0 B)"
        rot_dir.append((a["t"], f"#{pid} chega: {o_que}\nSACK {fmt_sacks(a['sacks'])}",
                        VIOLETA if a["delivered"] else TINTA2))

    for a in acks:
        t0, t1 = a["t_sent"], a["t"]
        if a["dropped"]:
            ax.annotate("", xy=(0.55, t0 + 0.45 * (t1 - t0)), xytext=(XR, t0),
                        arrowprops=dict(arrowstyle="-", color=VERDE, lw=1.3, ls="--"))
            ax.plot(0.55, t0 + 0.45 * (t1 - t0), marker="X", ms=11, color=VERMELHO, mec=FUNDO, mew=1.5, zorder=5)
            ax.text(0.52, t0 + 0.45 * (t1 - t0), "ACK perdido", color=VERMELHO, fontsize=8, va="center",
                    ha="right", fontweight="bold")
        else:
            ax.annotate("", xy=(XE, t1), xytext=(XR, t0),
                        arrowprops=dict(arrowstyle="-|>", color=VERDE, lw=1.3, ls="--", mutation_scale=11))
            rot_esq.append((t1, f"ACK #{a['id']}: libera {a['freed']} B\n(em voo {a['inflight']})", TINTA2))

    for t in timeouts:
        ax.plot(XE, t, marker="o", ms=10, color=VERMELHO, zorder=6)
        rot_esq.append((t, "TIMEOUT", VERMELHO))

    caixa = ax.get_position()
    folga_padrao = 0.27 * (t_fim + 0.6) / (caixa.height * altura)   # ~2 linhas de texto, em unidades de tempo

    def espalhar(rotulos, x, ha, folga=folga_padrao):
        """Desce rótulos que cairiam em cima do anterior."""
        ultimo = -1e9
        for y, txt, cor in sorted(rotulos, key=lambda r: r[0]):
            y2 = max(y, ultimo + folga)
            if y2 - y > 0.05:
                ax.plot([x, x + (0.015 if ha == "left" else -0.015)], [y, y2], color=GRADE, lw=0.8)
            ax.text(x + (0.02 if ha == "left" else -0.02), y2, txt, fontsize=7.2 if txt != "TIMEOUT" else 9,
                    fontweight="bold" if txt == "TIMEOUT" else "normal", color=cor, ha=ha, va="center")
            ultimo = y2

    espalhar(rot_dir, XR, "left")
    espalhar(rot_esq, XE, "right")
    for t in fins:
        ax.plot(XE, t, marker="s", ms=8, color=TINTA, zorder=6)
        ax.text(XE + 0.03, t + 0.12, "FIN (send() devolveu None)", color=TINTA, fontsize=8.5,
                fontweight="bold", ha="left", va="top")

    ax.set_xlim(-0.42, 1.55)
    ax.set_ylim(t_fim, -0.6)
    ax.set_xticks([])
    ax.set_ylabel("tempo (unidades do simulador; RTT = 2)", color=TINTA2)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(colors=TINTA2)
    ax.grid(axis="y", color=GRADE, lw=0.6)
    ax.set_axisbelow(True)
    ax.set_title("Diagrama de sequência", loc="left", fontsize=11, color=TINTA)

    # ---- tempo x número de sequência ----------------------------------------
    bx = fig.add_subplot(gs[0, 1])
    bx.set_facecolor(FUNDO)
    rot_usados = set()

    def rot1(r):
        if r in rot_usados:
            return None
        rot_usados.add(r)
        return r

    for s in sends.values():
        cor = LARANJA if s["retx"] else AZUL
        bx.plot([s["t"], s["t"]], [s["seq"][0], s["seq"][1]], color=cor, lw=3, solid_capstyle="round",
                label=rot1("retransmissão" if s["retx"] else "envio de dados"))
        if s["dropped"]:
            bx.plot(s["t"], (s["seq"][0] + s["seq"][1]) / 2, marker="X", ms=10, color=VERMELHO, mec=FUNDO,
                    label=rot1("pacote perdido"))
    xs, ys = [0.0], [0]
    for a in sorted([a for a in acks if not a["dropped"]], key=lambda a: a["t"]):
        cum = a["sacks"][0][1] if a["sacks"] and a["sacks"][0][0] == 0 else 0
        xs += [a["t"], a["t"]]
        ys += [ys[-1], max(ys[-1], cum)]
        for sk in a["sacks"][1:] if cum else a["sacks"]:
            bx.plot([a["t"], a["t"]], sk, color=VERDE, lw=1.5, alpha=0.45, label=rot1("bloco SACK acima da lacuna"))
    bx.plot(xs + [t_fim], ys + [ys[-1]], color=VERDE, lw=2, ls="--", label="maior byte contíguo confirmado")
    ap_x, ap_y = [0.0], [0]
    for a in sorted(arrives.values(), key=lambda a: a["t"]):
        ap_x += [a["t"], a["t"]]
        ap_y += [ap_y[-1], a["app_total"]]
    bx.plot(ap_x + [t_fim], ap_y + [ap_y[-1]], color=VIOLETA, lw=2, label="bytes entregues à aplicação")
    for t in timeouts:
        bx.axvline(t, color=VERMELHO, lw=1.2, ls=":", label=rot1("timeout"))
    bx.set_xlim(0, t_fim)
    bx.set_ylabel("número de sequência (byte)", color=TINTA2)
    bx.set_title("Tempo × número de sequência", loc="left", fontsize=11, color=TINTA)
    bx.legend(fontsize=8, loc="upper left", frameon=True, facecolor=FUNDO, edgecolor="none", framealpha=0.92)
    bx.grid(color=GRADE, lw=0.6)
    for sp in ("top", "right"):
        bx.spines[sp].set_visible(False)
    bx.tick_params(colors=TINTA2)

    # ---- bytes em voo ---------------------------------------------------------
    cx = fig.add_subplot(gs[1, 1], sharex=bx)
    cx.set_facecolor(FUNDO)
    pts = [(e["t"], e["inflight"]) for e in evs
           if e["type"] == "send" or (e["type"] == "ack" and not e["dropped"]) or e["type"] == "timeout"]
    pts = [(t, 0 if v is None else v) for t, v in pts]
    tx_, iy = [0.0], [0]
    for t, v in pts:
        tx_ += [t, t]
        iy += [iy[-1], v]
    cx.plot(tx_, iy, color=AZUL, lw=2, label="inflight (bytes em voo)")
    cx.axhline(janela - 1500, color=TINTA2, lw=1.2, ls="--", label=f"limite p/ enviar: janela − 1500 = {janela - 1500}")
    for t in timeouts:
        cx.axvline(t, color=VERMELHO, lw=1.2, ls=":")
    cx.set_xlabel("tempo", color=TINTA2)
    cx.set_ylabel("bytes", color=TINTA2)
    cx.set_title("Bytes em voo × janela", loc="left", fontsize=11, color=TINTA)
    cx.legend(fontsize=8, loc="upper right", frameon=True, facecolor=FUNDO, edgecolor="none", framealpha=0.92)
    cx.grid(color=GRADE, lw=0.6)
    cx.set_ylim(0, max(janela, max(iy) + 1200) * 1.4)
    for sp in ("top", "right"):
        cx.spines[sp].set_visible(False)
    cx.tick_params(colors=TINTA2)

    status = "OK — dados entregues corretamente" if res.ok else f"FALHOU — {res.explain()}"
    fig.text(0.03, 0.12 / altura, f"{status}  |  {res.summary()}", ha="left", va="bottom", fontsize=8.5,
             color=TINTA if res.ok else VERMELHO)
    os.makedirs(os.path.dirname(saida) or ".", exist_ok=True)
    fig.savefig(saida, dpi=110, facecolor=FUNDO)
    plt.close(fig)


def executar(nome, impl, pasta, texto=True):
    cen = CENARIOS[nome]
    kw = {k: cen[k] for k in ("recv_window", "drop_data", "drop_ack", "extra_delay", "pkts_to_reorder", "seed", "loss")
          if k in cen}
    kw.update(TEMPO)
    janela = cen.get("recv_window", 15000)
    res = Simulation(impl, random_text(cen["tamanho"], 1), **kw).run()
    saida = os.path.join(pasta, f"{nome}.png")
    desenhar(nome, cen, res, janela, saida)
    if texto:
        print("=" * 100)
        print(f"{nome}: {cen['titulo']}")
        print("\n".join(textwrap.wrap("O que observar: " + cen["observar"], 100)))
        print("-" * 100)
        print(traco_texto(res))
        print("-" * 100)
        print(("OK" if res.ok else "FALHOU: " + res.explain()) + " | " + res.summary())
    print(f"figura salva em {saida}")
    return res


def main():
    ap = argparse.ArgumentParser(description="Visualiza cenários do trabalho de transporte")
    ap.add_argument("cenario", nargs="?", help="nome do cenário ou 'todos'")
    ap.add_argument("--impl", default=None, help="transport.py a usar (padrão: ../src/transport.py)")
    ap.add_argument("--saida", default=os.path.join(AQUI, "figuras"), help="pasta das figuras")
    ap.add_argument("--lista", action="store_true", help="lista os cenários disponíveis")
    ap.add_argument("--sem-texto", action="store_true", help="não imprime o traço textual")
    args = ap.parse_args()

    if args.lista or not args.cenario:
        for n, c in CENARIOS.items():
            print(f"  {n:<38} {c['titulo']}")
        return
    impl = load_impl(args.impl or default_impl_path())
    nomes = list(CENARIOS) if args.cenario == "todos" else [args.cenario]
    for n in nomes:
        if n not in CENARIOS:
            sys.exit(f"cenário desconhecido: {n} (use --lista)")
        executar(n, impl, args.saida, texto=not args.sem_texto)


if __name__ == "__main__":
    main()
