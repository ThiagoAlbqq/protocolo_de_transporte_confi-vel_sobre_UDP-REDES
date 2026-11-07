#!/usr/bin/env python3
"""
corrigir.py — executa a suíte de testes e calcula a nota (1 a 10).

Uso:
    python corrigir.py                              # testa ../src/transport.py
    python corrigir.py --impl caminho/transport.py  # testa outro arquivo
    python corrigir.py --semente 7                  # troca as sementes aleatórias
    python corrigir.py --saida relatorio.md         # também salva o relatório
    python corrigir.py --turma entregas/            # corrige vários arquivos -> notas.csv
        (entregas/ contém um .py por aluno, ou uma subpasta por aluno com transport.py)

Cálculo da nota:
    Cada categoria tem um peso (soma = 100 pontos). Dentro de uma categoria,
    todos os testes valem o mesmo. A pontuação P (0 a 100) vira nota com
        nota = 1 + 9 * P / 100
    ou seja: nada funcionando -> 1,0 ; tudo funcionando -> 10,0.
"""
import argparse
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

AQUI = os.path.dirname(os.path.abspath(__file__))

# categoria: (arquivo de teste, peso, descrição)
CATEGORIAS = {
    "receptor":    ("test_1_receptor",    20, "Receiver: buffer, entrega em ordem e SACKs"),
    "emissor":     ("test_2_emissor",     15, "Sender: envio, janela e término"),
    "perdas":      ("test_3_perdas",      15, "Detecção de perdas, retransmissão e timeout"),
    "integracao":  ("test_4_integracao",  20, "Transferência completa com perdas (simulador)"),
    "reordenacao": ("test_5_reordenacao", 15, "Transferência com reordenação de pacotes"),
    "eficiencia":  ("test_6_eficiencia",   5, "Sem desperdício: retransmissão rápida, uso da janela"),
    "udp":         ("test_7_udp",         10, "Programa real sobre sockets UDP"),
}
NOTA_MIN, NOTA_MAX = 1.0, 10.0


def rodar_pytest(impl, semente, limite):
    xml = tempfile.NamedTemporaryFile(suffix=".xml", delete=False).name
    env = dict(os.environ, TRANSPORT_IMPL=os.path.abspath(impl), SEMENTE_CORRECAO=str(semente),
               PYTHONDONTWRITEBYTECODE="1")
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={xml}",
           "-o", "junit_family=xunit1", AQUI]
    try:
        proc = subprocess.run(cmd, cwd=AQUI, env=env, capture_output=True, text=True, timeout=limite)
        saida = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        saida = f"A suíte excedeu {limite}s e foi interrompida."
    return xml, saida


def ler_resultados(xml):
    """Devolve {modulo: [(nome, passou, motivo), ...]}."""
    res = {}
    if not os.path.exists(xml) or os.path.getsize(xml) == 0:
        return res
    for tc in ET.parse(xml).getroot().iter("testcase"):
        modulo = tc.get("classname", "").split(".")[-1]
        nome = tc.get("name")
        falha = tc.find("failure")
        if falha is None:
            falha = tc.find("error")
        pulado = tc.find("skipped") is not None
        if falha is not None:
            motivo = (falha.get("message") or "").strip().splitlines()
            motivo = motivo[0] if motivo else "falhou"
            res.setdefault(modulo, []).append((nome, False, motivo[:160]))
        else:
            res.setdefault(modulo, []).append((nome, not pulado, "pulado" if pulado else ""))
    return res


def corrigir(impl, semente, limite):
    """Devolve (nota, pontos_por_categoria, relatorio_markdown)."""
    xml, saida = rodar_pytest(impl, semente, limite)
    resultados = ler_resultados(xml)
    try:
        os.remove(xml)
    except OSError:
        pass

    linhas = [f"# Relatório de correção — {os.path.abspath(impl)}", "",
              f"Semente: {semente}", "",
              "| Categoria | Peso | Testes OK | Pontos |", "|---|---:|---:|---:|"]
    total_pts, falhas, por_cat = 0.0, [], {}
    for cat, (mod, peso, desc) in CATEGORIAS.items():
        testes = resultados.get(mod, [])
        ok = sum(1 for _, p, _ in testes if p)
        pts = peso * ok / len(testes) if testes else 0.0
        por_cat[cat] = pts
        total_pts += pts
        linhas.append(f"| {cat} — {desc} | {peso} | {ok}/{len(testes) or '?'} | {pts:.1f} |")
        falhas += [(cat, n, m) for n, p, m in testes if not p]
    nota = NOTA_MIN + (NOTA_MAX - NOTA_MIN) * total_pts / 100.0
    linhas += [f"| **Total** | **100** | | **{total_pts:.1f}** |", "",
               f"## Nota: {nota:.1f} (escala de {NOTA_MIN:.0f} a {NOTA_MAX:.0f})", ""]
    if not resultados:
        linhas += ["Nenhum resultado de teste foi produzido. Saída do pytest:", "```", saida[-3000:], "```"]
    elif falhas:
        linhas += ["## Testes que falharam", ""]
        linhas += [f"- [{c}] `{n}` — {m}" for c, n, m in falhas]
    return nota, por_cat, "\n".join(linhas)


def entregas_da_turma(pasta):
    """Lista (nome_do_aluno, caminho_do_transport.py)."""
    itens = []
    for nome in sorted(os.listdir(pasta)):
        cam = os.path.join(pasta, nome)
        if os.path.isfile(cam) and nome.endswith(".py"):
            itens.append((nome[:-3], cam))
        elif os.path.isdir(cam):
            alvo = os.path.join(cam, "transport.py")
            if os.path.exists(alvo):
                itens.append((nome, alvo))
    return itens


def main():
    ap = argparse.ArgumentParser(description="Corretor automático do trabalho de transporte")
    ap.add_argument("--impl", default=os.path.join(AQUI, "..", "src", "transport.py"))
    ap.add_argument("--semente", type=int, default=0)
    ap.add_argument("--saida", help="arquivo para salvar o relatório (markdown)")
    ap.add_argument("--turma", help="pasta com as entregas; gera notas.csv e um relatório por aluno")
    ap.add_argument("--limite", type=int, default=1200, help="tempo máximo total por entrega (s)")
    args = ap.parse_args()

    if args.turma:
        import csv
        itens = entregas_da_turma(args.turma)
        if not itens:
            sys.exit(f"Nenhuma entrega encontrada em {args.turma}")
        pasta_rel = os.path.join(args.turma, "relatorios")
        os.makedirs(pasta_rel, exist_ok=True)
        with open(os.path.join(args.turma, "notas.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["aluno", "nota"] + list(CATEGORIAS))
            for aluno, cam in itens:
                nota, por_cat, rel = corrigir(cam, args.semente, args.limite)
                with open(os.path.join(pasta_rel, f"{aluno}.md"), "w") as r:
                    r.write(rel + "\n")
                w.writerow([aluno, f"{nota:.1f}"] + [f"{por_cat[c]:.1f}" for c in CATEGORIAS])
                print(f"{aluno:<30} {nota:4.1f}")
        print(f"\nNotas em {os.path.join(args.turma, 'notas.csv')}; relatórios em {pasta_rel}/")
        return

    if not os.path.exists(args.impl):
        sys.exit(f"Arquivo não encontrado: {args.impl}")
    nota, _, relatorio = corrigir(args.impl, args.semente, args.limite)
    print(relatorio)
    if args.saida:
        with open(args.saida, "w") as f:
            f.write(relatorio + "\n")


if __name__ == "__main__":
    main()
