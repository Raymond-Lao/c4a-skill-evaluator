import sys
from pathlib import Path

def compress(folder):
    for p in Path(folder).glob("*.png"):
        print("compress", p)
    return "done"

if __name__ == "__main__":
    compress(sys.argv[1])
