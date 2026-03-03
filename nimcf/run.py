import pathlib
import sys
from pprint import pprint

sys.path.append(str(pathlib.Path(__file__).resolve().parent / "src"))

from core.api import add_experience, boot, cluster_memory, get_safety_log, query_memory, run_task


if __name__ == "__main__":
    boot()

    add_experience("Ich habe heute ein neues Solarpanel montiert.", {"valenz": 0.6, "arousal": 0.5})
    add_experience(
        "Der Speicherregler hat nicht funktioniert, Fehlermeldung 404.",
        {"valenz": -0.7, "arousal": 0.8},
    )
    add_experience("Ben hat im Garten Tomaten gepflanzt.", {"valenz": 0.8, "arousal": 0.4})

    print("\n🧠 Memory recall for 'Solar Fehler':")
    for hit in query_memory("Solar Fehler"):
        print(f"[{hit['score']:.3f}] {hit['text']}")

    print("\n🧭 Coordinator meta-planning:")
    plan = run_task("Diagnose Speicherfehler", capabilities=["plan", "memory-search"])
    pprint(plan)

    print("\n🗂️ Themen-Cluster Übersicht:")
    clusters = cluster_memory(limit=20)
    pprint(clusters)

    print("\n🛡️ Safety-Log:")
    pprint(get_safety_log(limit=5))
