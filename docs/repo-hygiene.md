# Repo-Hygiene: fremdes Material, Zwischenfälle, Backup

Dieses Repository ist **öffentlich**. Das hat Konsequenzen, die nicht offensichtlich sind,
bis man einmal dagegen läuft. Am 2026-08-02 ist genau das passiert. Dieses Dokument hält
die Regel, das Runbook für den Fehlerfall und die Backup-Prozedur fest.

> **Was hier bewusst *nicht* steht:** die Commit-SHAs des Zwischenfalls und die
> Identifikation des betroffenen Fremdmaterials. Der Inhalt verwaister Commits ist nur
> auffindbar, wenn man den SHA kennt — ihn in eine öffentliche Datei zu schreiben würde ihn
> jedem in die Hand geben und die Exposition vergrößern statt verkleinern. Die Fallakte
> liegt lokal in `INCIDENT-*.local.md` (per `.gitignore` ausgeschlossen).

---

## 1. Die Regel

**Fremdes urheberrechtlich geschütztes Material gehört nicht in dieses Repo.** Weder als
Original noch abgeleitet.

Das ist weiter gefasst, als es klingt. Bei einem OCR-Werkzeug betrifft es vier Dinge, und
drei davon werden regelmäßig übersehen:

| | |
|---|---|
| Das Material selbst | PDFs, gerenderte Seiten — offensichtlich |
| **Transkriptionen** | Eine OCR-Ausgabe ist derselbe Inhalt in anderer Form, kein neutrales Messartefakt |
| **Der Bericht** | Nennt Kurs, Autor, Copyright-Zeile — identifiziert das Werk vollständig |
| **Die Skripte** | Tragen Quell-Dateinamen und lokale Pfade |

Beim Zwischenfall haben die letzten beiden geleakt, nicht die ersten beiden. Die
`.gitignore` hatte Korpus und Ergebnisse korrekt blockiert — und Bericht und Skripte
durchgelassen, weil sie global freigeschaltet waren.

## 2. Wie die `.gitignore` das durchsetzt

Die `.gitignore` arbeitet als Allowlist: Zeile 2 ist `*`, alles Weitere sind Ausnahmen. Das
ist gut, hat aber eine Falle: **eine Ausnahme wie `!README.md` greift auf jeder
Verzeichnistiefe.** Genau daran ist der Bericht durchgerutscht.

Unter `benchmarks/` gilt deshalb Deny-by-default. Gesperrt sind `README.md`, `scripts/*`,
`pages/`, `results/`, `logs/`, `corpus/`, `ground_truth.json`, `page_map.json` und
`openrouter_models_*.json`. Freigegeben wird **pro Verzeichnis, einzeln, nach Prüfung**.

Aktuell freigegeben: `benchmarks/ocr_model_selection/` — der Korpus wird von
`scripts/make_corpus.py` aus dem Code gezeichnet, siehe dessen `CORPUS.md`.

### Neues Benchmark-Verzeichnis hinzufügen

1. Herkunft des Korpus klären. Selbst erzeugt oder nachweislich gemeinfrei? Wenn nein:
   **nicht freigeben**, lokal lassen.
2. Herkunft in einer `CORPUS.md` im Verzeichnis dokumentieren.
3. Erst dann die Pfade einzeln in der `.gitignore` freischalten.
4. Gegenprobe fahren:

   ```bash
   git add -An benchmarks/<neu>/       # zeigt, was aufgenommen würde
   git check-ignore -v <pfad>          # zeigt, welche Regel greift
   ```

   Und die Sperre gegenprüfen, indem man ein Wegwerf-Verzeichnis mit `README.md`,
   `scripts/x.py`, `pages/x.png` anlegt und bestätigt, dass `git add -An` **nichts** ausgibt.

> Die Freigabe gilt für das ganze Verzeichnis. Wer später echtes Fremdmaterial in einen
> freigegebenen Korpusordner kopiert, umgeht die Sperre. Das ist der Preis dafür, dass
> generierte Korpora mitversioniert werden können.

## 3. Runbook: es ist doch etwas durchgerutscht

Reihenfolge einhalten. Schritt 1 ist zeitkritisch, alles Weitere nicht.

**1 — Sichtbarkeit feststellen.**

```bash
gh repo view <owner>/<repo> --json visibility,forks_count
```

Bei `PRIVATE` und 0 Forks ist es unkritisch; trotzdem bereinigen. Bei `PUBLIC` weiter.

**2 — Aus der Historie entfernen, nicht nur löschen.** Ein `git rm` in einem neuen Commit
lässt den Inhalt in der Historie. Der betroffene Branch muss neu geschrieben werden:

```bash
git reset --soft <letzter-sauberer-commit>
git add -A            # nimmt die Löschung mit auf
git commit -F -       # Historie ohne den belasteten Commit neu aufbauen
git push --force-with-lease origin <branch>
```

`--force-with-lease` statt `--force`: bricht ab, falls jemand anders zwischenzeitlich
gepusht hat.

**3 — Prüfen, dass es weg ist.**

```bash
git log --all --name-only --pretty=format: | sort -u | grep <pfad>   # muss leer sein
git branch -a --contains <alter-sha>                                  # muss leer sein
```

**4 — Akzeptieren, dass es damit nicht gelöscht ist.** Ein Force-Push macht einen Commit
verwaist, er entfernt ihn nicht. GitHub liefert ihn weiterhin aus, wenn man den SHA kennt.
Nachprüfbar:

```bash
gh api "repos/<owner>/<repo>/contents/<pfad>?ref=<alter-sha>" --jq '.size'
```

Liefert das eine Zahl, ist der Inhalt noch abrufbar.

**5 — Alle betroffenen SHAs sammeln, nicht nur den ersten.** Wurde auf dem belasteten
Commit weitergearbeitet, tragen auch die Folge-Commits das Material in ihrem Baum. Prüfen:

```bash
git ls-tree -r --name-only <sha> | grep <pfad>
```

**6 — Support-Ticket.** <https://support.github.com/request>, Kategorie *„sensitive data
removed from your own repository history"*. Alle SHAs, den betroffenen Pfad, den Nachweis
der Nichterreichbarkeit und die Fork-Zahl angeben.

**Nicht** das Private-Information-Formular nehmen, außer es sind tatsächlich Zugangsdaten
oder personenbezogene Daten betroffen — jene Policy verlangt ein konkretes Sicherheitsrisiko
mit Datei und Zeilennummer. Ein Projektordnerpfad ohne Benutzernamen ist keins, und ein
unbelegter Antrag wird abgelehnt.

**7 — Bei Absage: Schritt 4 unten.** Die Doku sagt ausdrücklich, dass Support keine
*nicht-sensiblen* Daten entfernt. Ohne Zugangsdaten ist eine Absage ein realistischer
Ausgang, kein Sonderfall.

## 4. Wenn Support ablehnt: Repo löschen und neu anlegen

Das ist der einzige Weg, der garantiert funktioniert — alle Objekte verschwinden, auch die
verwaisten. **Vorher backupen**, sonst gehen Issues verloren.

```bash
tools/backup_repo.sh                      # siehe Abschnitt 5
gh repo delete <owner>/<repo> --yes
gh repo create <owner>/<repo> --public --source=. --push
```

Was das kostet, ehrlich benannt:

| bleibt erhalten | geht verloren |
|---|---|
| gesamte Git-Historie (aus dem lokalen Klon) | Issues (nur als JSON gesichert, kein Bulk-Import) |
| alle Branches und Tags | Stars, Watcher, Forks |
| Code, Tags, Releases (aus dem Backup) | Erstellungsdatum, Traffic-Statistiken |

Vor dem Löschen die Zahlen prüfen — bei 0 Stars und 0 Forks ist der Verlust gering:

```bash
gh api repos/<owner>/<repo> \
  --jq '"stars: \(.stargazers_count) forks: \(.forks_count) issues: \(.open_issues_count)"'
```

## 5. Backup

`tools/backup_repo.sh` sichert, was ein `git clone` **nicht** mitnimmt.

```bash
tools/backup_repo.sh                     # -> ../package_pdf2anki-backup-<datum>/
tools/backup_repo.sh /pfad/zum/ziel
```

Was hineingeht:

| | |
|---|---|
| `repo.git/` | `--mirror`-Klon: **alle** Refs, nicht nur der Default-Branch |
| `issues.json`, `issue-comments.json` | das Einzige, was ein lokaler Klon nicht ersetzen kann |
| `releases.json`, `release-assets/` | Release-Binaries liegen nicht in git |
| `repo-metadata.json`, `labels.json` | Beschreibung, Topics, Sichtbarkeit, Default-Branch |
| `RESTORE.md` | Wiederherstellungsanleitung, wird mitgeschrieben |

Ohne `gh` läuft nur der Git-Mirror; das Skript sagt das ausdrücklich, statt es still zu
überspringen.

**Backup prüfen, nicht nur anlegen:**

```bash
git --git-dir=<backup>/repo.git fsck                  # muss still sein
git --git-dir=<backup>/repo.git rev-list --all --count
git --git-dir=<backup>/repo.git for-each-ref
```

## 6. Vor jedem Push, wenn Messdaten oder Fremdmaterial im Spiel sind

```bash
gh repo view <owner>/<repo> --json visibility   # PUBLIC? -> Abschnitt 1 gilt strikt
git add -An .                                   # was würde ein `git add .` aufnehmen?
git diff --cached --name-only                   # was ist bereits gestaged?
```

Nie blind `git add .` in einem Repo mit Allowlist-`.gitignore`: dort entscheidet eine Regel
auf beliebiger Tiefe, was durchrutscht.
