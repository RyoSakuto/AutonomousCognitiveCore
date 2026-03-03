# Repo Bootstrap

Ziel: sauberen Workspace als neues GitHub-Repository starten.

## 1. Lokales Git initialisieren

```bash
cd /home/rico/Tests/AutonomousCognitiveCore
git init
git branch -M main
git add .
git commit -m "Initial clean ACC baseline"
```

## 2. GitHub-Repo verbinden

Mit `gh` CLI:

```bash
gh repo create AutonomousCognitiveCore --private --source=. --remote=origin --push
```

Oder manuell:

```bash
git remote add origin git@github.com:<dein-user>/AutonomousCognitiveCore.git
git push -u origin main
```

## 3. Empfohlene Branch-Regeln

1. `main` nur via PR mergen.
2. Schutzregel: mindestens 1 Review.
3. CI-Check verpflichtend (mindestens `python3 -m compileall acc main.py`).

## 4. Vor jedem Push

```bash
python3 -m compileall acc main.py
python3 main.py --cycles 1
```
