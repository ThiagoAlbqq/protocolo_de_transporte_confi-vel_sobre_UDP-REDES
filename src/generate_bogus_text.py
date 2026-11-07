import argparse
import random

try:
    import lorem  # pip install lorem
except ImportError:  # alternativa sem dependência externa
    lorem = None

_PALAVRAS = ("lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor "
             "incididunt ut labore et dolore magna aliqua ut enim ad minim veniam quis nostrud "
             "exercitation ullamco laboris nisi aliquip ex ea commodo consequat").split()


def _paragrafo():
    if lorem is not None:
        return lorem.paragraph()
    frases = []
    for _ in range(random.randint(4, 8)):
        f = " ".join(random.choice(_PALAVRAS) for _ in range(random.randint(6, 14)))
        frases.append(f.capitalize() + ".")
    return " ".join(frases)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tool to generate the given amount of data")
    parser.add_argument("size", type=int, help="How many bytes (approximately) should we generate?")
    args = parser.parse_args()
    print(args.size, type(args.size))

    generated = 0
    while generated < args.size:
        para = _paragrafo() + "\n"
        generated += len(para)
        print(para)
