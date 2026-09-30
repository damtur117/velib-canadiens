"""Relève chaque minute l'état de toutes les stations Vélib'.
Un fichier compressé par heure : data/reseau/AAAA-MM-JJ/HH.csv.gz (heure de Paris).
Chaque fichier commence par l'état complet de toutes les stations ; ensuite, une ligne
n'est écrite pour une station que lorsque son état change.
La liste des stations (nom, position, capacité) est enregistrée une fois par jour."""
import csv, gzip, io, json, os, subprocess, time, urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BASE = "https://velib-metropole-opendata.smovengo.cloud/opendata/Velib_Metropole/"
DOSSIER = "data/reseau"
INTERVALLE = 60                   # un relevé chaque minute
DUREE_MAX = 345 * 60              # un passage dure 5 h 45, puis le suivant prend le relais
PARIS = ZoneInfo("Europe/Paris")
COLONNES = ["horodatage_utc", "station_id", "velos_mecaniques", "velos_electriques",
            "places_libres", "station_en_service"]


def telecharger(nom):
    req = urllib.request.Request(BASE + nom, headers={"User-Agent": "collecte-velib-open-data"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["data"]["stations"]


def releve():
    horodatage = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lignes = []
    for s in telecharger("station_status.json"):
        types = s.get("num_bikes_available_types") or []
        lignes.append([horodatage, s["station_id"],
                       sum(t.get("mechanical", 0) for t in types),
                       sum(t.get("ebike", 0) for t in types),
                       s["num_docks_available"],
                       int(bool(s["is_renting"] and s["is_returning"]))])
    return lignes


def ecrire_heure(cle, lignes):
    """Écrit un fichier compressé pour une heure terminée (jamais réécrit ensuite)."""
    jour, heure = cle
    chemin = f"{DOSSIER}/{jour}/{heure}.csv.gz"
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    if os.path.exists(chemin):  # heure déjà en partie sauvegardée par le passage précédent
        with gzip.open(chemin, "rt", encoding="utf-8") as f:
            anciennes = list(csv.reader(f))[1:]
        lignes = anciennes + lignes
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(COLONNES)
    w.writerows(lignes)
    with gzip.open(chemin, "wt", encoding="utf-8") as f:
        f.write(buf.getvalue())
    return chemin


def ecrire_stations(jour):
    chemin = f"{DOSSIER}/{jour}/stations.csv"
    if os.path.exists(chemin):
        return None
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["station_id", "nom", "latitude", "longitude", "capacite"])
        for s in telecharger("station_information.json"):
            w.writerow([s["station_id"], s["name"].strip(), s["lat"], s["lon"], s["capacity"]])
    return chemin


def sauvegarder(fichiers):
    if not fichiers:
        return
    subprocess.run(["git", "add", *fichiers], check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        return
    subprocess.run(["git", "commit", "-q", "-m", "Relevés réseau Vélib"], check=True)
    for _ in range(5):
        subprocess.run(["git", "pull", "-q", "--rebase"])
        if subprocess.run(["git", "push", "-q"]).returncode == 0:
            return
        time.sleep(15)


def main():
    debut = time.time()
    en_cours, tampon = None, []
    dernier = {}                                  # dernier état connu de chaque station
    while True:
        maintenant = datetime.now(PARIS)
        cle = (maintenant.strftime("%Y-%m-%d"), maintenant.strftime("%H"))
        if en_cours and cle != en_cours:          # l'heure est terminée : on sauvegarde
            fichiers = [ecrire_heure(en_cours, tampon)]
            try:
                fichiers.append(ecrire_stations(cle[0]))
            except Exception as e:
                print("Liste des stations non récupérée :", e, flush=True)
            sauvegarder([f for f in fichiers if f])
            tampon = []
            dernier = {}                          # nouvelle heure : on repart d'un état complet
        en_cours = cle
        if time.time() - debut >= DUREE_MAX:
            break
        try:
            lignes = releve()
            changees = [l for l in lignes if dernier.get(l[1]) != l[2:]]
            for l in changees:
                dernier[l[1]] = l[2:]
            tampon.extend(changees)
            print(maintenant.strftime("%H:%M"), len(lignes), "stations relevées,", len(changees), "changements", flush=True)
        except Exception as e:  # une panne ponctuelle de l'API ne doit pas arrêter la collecte
            print("Relevé manqué :", e, flush=True)
        time.sleep(INTERVALLE - time.time() % INTERVALLE)  # début de la minute suivante
    if tampon:                                     # fin du passage : on sauvegarde l'heure entamée
        sauvegarder([ecrire_heure(en_cours, tampon)])


if __name__ == "__main__":
    main()
