from pathlib import Path

def show_tree(path: str | Path = "nimcf", prefix: str = "", max_depth: int = 5):
    """
    Zeigt die Verzeichnisstruktur als Baum.
    - path: Wurzelpfad (standard: nimcf)
    - max_depth: wie tief soll angezeigt werden
    """
    path = Path(path)
    if not path.exists():
        print(f"❌ Pfad {path} nicht gefunden.")
        return

    def _show(current: Path, prefix: str, depth: int):
        if depth > max_depth:
            return
        files = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        for i, f in enumerate(files):
            connector = "└── " if i == len(files) - 1 else "├── "
            print(prefix + connector + f.name)
            if f.is_dir():
                extension = "    " if i == len(files) - 1 else "│   "
                _show(f, prefix + extension, depth + 1)

    print(path.name)
    _show(path, prefix, 1)

if __name__ == "__main__":
    show_tree("nimcf")
