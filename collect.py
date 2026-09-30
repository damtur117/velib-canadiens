"""Relève chaque minute l'état de la station Vélib' « Gare RER - Canadiens »
(Joinville-le-Pont) et l'ajoute à data/canadiens.csv."""
import csv, json, os, subprocess, time, urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

STATION_ID = 19941915381          # Gare RER - Canadiens
CAPACITE = 40                     # nombre de places de la station
URL = "https://velib-metropole-opendata.smovengo.cloud/opendata/Velib_Metropole/station_status.json"
FICHIER = "data/canadiens.csv"
DUREE_MAX = 345 * 60              # un passage dure 5 h 45, puis le suivant prend le relais
COMMIT_TOUTES_LES = 15 * 60       # sauvegarde sur GitHub toutes les 15 minutes
PARIS = ZoneInfo("Europe/Paris")
COLONNES = ["horodatage_utc", "heure_paris", "maj_station_paris", "velos_mecaniques",
            "velos_electriques", "velos_total", "places_libres", "taux_places_libres_pct",
            "station_en_service"]


def releve():
    req = urllib.request.Request(URL, headers={"User-Agent": "collecte-velib-open-data"})
    with urllib.request.urlopen(req, timeout=30) as r:
        stations = json.load(r)["data"]["stations"]
    s = next(x for x in stations if x["station_id"] == STATION_ID)
    types = s.get("num_bikes_available_types") or []
    meca = sum(t.get("mechanical", 0) for t in types)
    elec = sum(t.get("ebike", 0) for t in types)
    maintenant = datetime.now(timezone.utc)
    return {
        "horodatage_utc": maintenant.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "heure_paris": maintenant.astimezone(PARIS).strftime("%Y-%m-%d %H:%M"),
        "maj_station_paris": datetime.fromtimestamp(s["last_reported"], PARIS).strftime("%Y-%m-%d %H:%M"),
        "velos_mecaniques": meca,
        "velos_electriques": elec,
        "velos_total": s["num_bikes_available"],
        "places_libres": s["num_docks_available"],
        "taux_places_libres_pct": round(100 * s["num_docks_available"] / CAPACITE, 1),
        "station_en_service": int(bool(s["is_renting"] and s["is_returning"])),
    }


def ecrire(ligne):
    nouveau = not os.path.exists(FICHIER)
    os.makedirs(os.path.dirname(FICHIER), exist_ok=True)
    with open(FICHIER, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLONNES)
        if nouveau:
            w.writeheader()
        w.writerow(ligne)


def sauvegarder():
    subprocess.run(["git", "add", FICHIER], check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        return
    subprocess.run(["git", "commit", "-q", "-m", "Relevés Vélib"], check=True)
    for _ in range(3):
        subprocess.run(["git", "pull", "-q", "--rebase"])
        if subprocess.run(["git", "push", "-q"]).returncode == 0:
            return
        time.sleep(10)


def main():
    debut = derniere_sauvegarde = time.time()
    while time.time() - debut < DUREE_MAX:
        try:
            ligne = releve()
            ecrire(ligne)
            print(ligne["heure_paris"], ligne["places_libres"], "places libres", ligne["taux_places_libres_pct"], "%", flush=True)
        except Exception as e:  # une panne ponctuelle de l'API ne doit pas arrêter la collecte
            print("Relevé manqué :", e, flush=True)
        if time.time() - derniere_sauvegarde >= COMMIT_TOUTES_LES:
            sauvegarder()
            derniere_sauvegarde = time.time()
        time.sleep(60 - time.time() % 60)  # attend le début de la minute suivante
    sauvegarder()


if __name__ == "__main__":
    main()
