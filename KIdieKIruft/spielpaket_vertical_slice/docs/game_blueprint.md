# Game Blueprint

## Projektkontext

Dieses Dokument definiert das Spielziel und die minimalen Design-Entscheidungen fuer den 4-Wochen-Zeitraum. Es priorisiert eine kleine, testbare und schnell iterierbare Umsetzung.

## Genre

Top-Down Survival-Arcade mit leichter Rogue-Lite-Struktur (zunaechst als minimaler, lokal lauffaehiger Prototyp).

## Spielerziel

Der Spieler sammelt 3 Energiezellen, aktiviert danach den Extraktionspunkt und erreicht diesen lebend.

## Win-Bedingung

- Genau 3 Energiezellen wurden eingesammelt.
- Der Extraktionspunkt wurde aktiviert.
- Die Spielfigur erreicht den Extraktionspunkt bei verbleibenden Lebenspunkten.

## Fail-Bedingung

- Lebenspunkte fallen auf 0.
- Optionaler Missions-Timer laeuft ab, bevor der Extraktionspunkt erreicht wurde.

## Hauptmechanik

1. Bewegung und Positionierung:
   Der Spieler bewegt sich aktiv ueber das Spielfeld, um Ressourcen zu sammeln und Gefahren auszuweichen.
2. Risiko gegen Fortschritt:
   Das Einsammeln von Energiezellen erhoeht die Bedrohung (z. B. Gegnerdruck oder Spawn-Rate).
3. Ressourcen-Management:
   Kurzzeitressource (z. B. Ausdauer fuer Sprint/Ausweichen) erzwingt Entscheidungen statt Daueraktion.
4. Klarer Endzustand:
   Nach Aktivierung des Extraktionspunkts wechselt der Fokus von Sammeln zu sicherem Escape.

## Core-Loop (Gameplay)

1. Lage lesen (Gefahren, Ressourcen, Weg zum Ziel).
2. Aktion ausfuehren (bewegen, ausweichen, sammeln).
3. Systemreaktion verarbeiten (Bedrohung, Schaden, Fortschritt).
4. Naechste Entscheidung treffen bis Win oder Fail.

## Difficulty-Kurve (Kampagne)

- Die Kampagne nutzt eine zentrale, datengetriebene Level-Tabelle im Code.
- Pro Level werden mindestens `starting_hp`, `turn_limit`, `hazard_density`, `hazard_count` und `enemy_turns_per_round` festgelegt.
- Zielregel: spaetere Level sind objektiv bedrohlicher als fruehe (mehr Gefahren und/oder engeres Zeitlimit).

## Milestones (4 Wochen)

- Woche 1:
  Blueprint finalisieren, technische Leitplanken festlegen, Startzustand und Datenmodell vorbereiten.
- Woche 2:
  Vertical Slice mit Startpunkt, Input-Verarbeitung und einer Win/Lose-Bedingung lauffaehig machen.
- Woche 3:
  Hauptmechanik vertiefen (Bedrohung + Ressource), Spieltempo justieren, erste Balance-Iteration.
- Woche 4:
  Stabilisieren, Smoke-Checks festziehen, Doku fuer Dispatch/Review und Build-/Run-Schritte finalisieren.

## Explizite Annahmen

- Das Ziel fuer Woche 2 ist ein minimal spielbarer Slice, nicht ein content-reiches Vollspiel.
- Eine lokale Ausfuehrung ohne externe Services ist ausreichend.
- Eingaben erfolgen ueber Tastatur; Controller-Support ist nicht Teil des 4-Wochen-Scopes.
- Erstes Target ist Desktop/Linux in der Entwicklungsumgebung dieses Repos.
- Gegner- und Levelvielfalt bleibt bewusst klein (ein Kernmodus, ein klarer Missionsfluss).
