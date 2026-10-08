"""Pré-remplissage d'un contrat à partir de son texte, par règles (sans IA, sans réseau).

Chaque valeur trouvée est accompagnée de la phrase du contrat qui la justifie (« preuves »). Ce qui est
incertain reste vide ou est signalé dans « points à vérifier » : rien n'est inventé.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

from .extraction import ResultatAnalyse
from .outils import ajouter_mois, sans_accents
from .schema import VERSION_SCHEMA, valider

MOIS = {m: i for i, m in enumerate(
    ["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout", "septembre", "octobre",
     "novembre", "decembre"], start=1)}
NOMBRES = {"un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8,
           "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "quinze": 15, "dix-huit": 18, "vingt": 20,
           "vingt-quatre": 24, "trente": 30, "trente-six": 36, "quarante-cinq": 45, "soixante": 60,
           "quatre-vingt-dix": 90, "cent vingt": 120}
RE_DATE = re.compile(
    r"(?P<j>\d{1,2})\s*(?:er)?\s+(?P<m>janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[ûu]t|septembre|octobre|"
    r"novembre|d[ée]cembre)\s+(?P<a>\d{4})|(?P<j2>\d{1,2})[/.\-](?P<m2>\d{1,2})[/.\-](?P<a2>\d{4})",
    re.IGNORECASE)
RE_NOMBRE = r"(?P<n>\d+|[a-zéèêûîô\- ]{2,22}?)(?:\s*\(\s*(?P<np>\d+)\s*\))?"
UNITES = {"jour": 1, "jours": 1, "semaine": 7, "semaines": 7, "mois": 30, "an": 365, "ans": 365,
          "année": 365, "années": 365}
INDICES = [("Syntec", r"syntec"), ("ICC", r"\bICC\b|co[ûu]t de la construction"), ("ILC", r"\bILC\b|loyers commerciaux"),
           ("ILAT", r"\bILAT\b"), ("IPC", r"\bIPC\b|prix à la consommation"), ("IPAMPA", r"IPAMPA"),
           ("Indice du coût horaire du travail", r"co[ûu]t horaire du travail|\bICHT\b")]
ACTIVITE_MOTS = {
    "Accueil": ["hôtesse", "hotesse", "accueil", "standard", "visiteurs", "réception", "reception"],
    "Conciergerie": ["conciergerie", "concierge", "multiservices", "multi-services", "services aux occupants"],
    "Hospitalité": ["hospitalité", "hospitality", "café", "événementiel", "evenementiel", "traiteur",
                    "accueil premium", "restauration"],
}


def _nombre(texte: str | None, entre_parentheses: str | None = None) -> int | None:
    if entre_parentheses:
        return int(entre_parentheses)
    if not texte:
        return None
    t = texte.strip().lower()
    if t.isdigit():
        return int(t)
    return NOMBRES.get(t)


def phrases(texte: str) -> list[str]:
    """Découpe en phrases/lignes (la citation d'une preuve = la phrase entière)."""
    morceaux = re.split(r"(?<=[.;!?])\s+(?=[A-ZÀ-Ý\d«\"(-])|\n+", texte)
    return [m.strip() for m in morceaux if m and len(m.strip()) > 3]


def trouver_dates(phrase: str) -> list[date]:
    dates = []
    for m in RE_DATE.finditer(phrase):
        try:
            if m.group("j"):
                mois = MOIS[sans_accents(m.group("m")).lower()]
                dates.append(date(int(m.group("a")), mois, int(m.group("j"))))
            else:  # jj/mm/aaaa : les contrats sont rédigés en français, jour en premier
                dates.append(date(int(m.group("a2")), int(m.group("m2")), int(m.group("j2"))))
        except ValueError:
            continue
    return dates


def _coupe(phrase: str, n: int = 320) -> str:
    phrase = re.sub(r"\s+", " ", phrase).strip()
    return phrase if len(phrase) <= n else phrase[: n - 1] + "…"


def _premiere(phs: list[str], motifs: list[str], flags=re.IGNORECASE):
    for p in phs:
        for motif in motifs:
            m = re.search(motif, p, flags)
            if m:
                return p, m
    return None, None


def _client(texte: str) -> str | None:
    forme = r"(?:SAS|SARL|SASU|EURL|SA|SCI|SNC|SELARL)"
    nom_re = (rf"(?:\b{forme}\b|[Ss]oci[ée]t[ée])\s+(?:(?:anonyme|par actions simplifi[ée]e|[àa] responsabilit[ée] limit[ée]e)\s+)?"
              r"(?:\b(?:SAS|SARL|SASU|EURL|SA|SCI|SNC)\b\s+)?"
              r"([A-ZÀ-Ý][\w&’'.\-]*(?:\s+(?:[A-ZÀ-Ý&][\w&’'.\-]*|de|du|des|d’|d'))*)")
    for m in re.finditer(r"ci[- ]apr[èe]s[^«\"“\n]{0,40}[«\"“]\s*(?:le |la |l[’'])?\s*(Client|Donneur d.ordre|"
                         r"B[ée]n[ée]ficiaire|Preneur)", texte, re.IGNORECASE):
        avant = texte[max(0, m.start() - 320): m.start()]
        cand = re.findall(nom_re, avant)
        if cand:
            nom = re.split(r",|\bau capital\b|\bdont\b|\bimmatricul|\bsituée?\b", cand[-1])[0].strip(" .-")
            if 2 <= len(nom) <= 60:
                return nom
    return None


def _sites(texte: str) -> list[tuple[str, str]]:
    """(site, phrase) pour les lignes du type « Site : Tour Pleyel » ou « site de Lyon »."""
    trouves: list[tuple[str, str]] = []
    for m in re.finditer(r"^\s*(?:[-•*]\s*)?(?:Site|Établissement|Etablissement|Immeuble)\s*(?:n°\s*\d+\s*)?[:–-]\s*([^\n,;(]{3,60})",
                         texte, re.MULTILINE | re.IGNORECASE):
        nom = m.group(1).strip(" .")
        if nom and nom.lower() not in {s.lower() for s, _ in trouves}:
            trouves.append((nom, m.group(0).strip()))
    return trouves


def _site_unique(phs: list[str]) -> tuple[str | None, str | None]:
    p, m = _premiere(phs, [r"\b(?:sur le|du|au|le)\s+site\s+(?:de |du |d[’'])?[«\"“]?([A-ZÀ-Ý][\w’'\-]*(?:\s+[A-ZÀ-Ý][\w’'\-]*){0,3})",
                           r"\b(?:locaux|immeuble|tour)\s+(?:de |du |d[’'])?[«\"“]?([A-ZÀ-Ý][\w’'\-]*(?:\s+[A-ZÀ-Ý][\w’'\-]*){0,3})"], flags=0)
    return (m.group(1).strip(), p) if m else (None, None)


def _activite(texte: str):
    bas = texte.lower()
    scores = {a: sum(bas.count(mot) for mot in mots) for a, mots in ACTIVITE_MOTS.items()}
    ordre = sorted(scores.items(), key=lambda kv: -kv[1])
    (a1, s1), (_, s2) = ordre[0], ordre[1]
    if s1 >= 2 and s1 >= s2 + 2:
        return a1, scores
    return None, scores


def _montants(phs: list[str]):
    """Montants en euros, avec la périodicité lue autour."""
    res = []
    for p in phs:
        for m in re.finditer(r"(\d{1,3}(?:[  .]\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)\s*(?:€|euros?|EUR)\b(\s*(?:HT|H\.T\.|hors taxes?))?",
                             p, re.IGNORECASE):
            valeur = float(re.sub(r"[  .]", "", m.group(1)).replace(",", "."))
            ctx = sans_accents(p.lower())
            per = None
            if re.search(r"par mois|mensuel|/ ?mois|chaque mois", ctx):
                per = "mensuel"
            elif re.search(r"par trimestre|trimestriel|/ ?trimestre", ctx):
                per = "trimestriel"
            elif re.search(r"par an|annuel|/ ?an\b|annee", ctx):
                per = "annuel"
            elif re.search(r"forfait unique|une seule fois|ponctuel", ctx):
                per = "ponctuel"
            res.append({"valeur": valeur, "ht": bool(m.group(2)), "per": per, "phrase": p})
    return res


def _duree(phs: list[str]):
    p, m = _premiere(phs, [rf"dur[ée]e\s+(?:initiale\s+)?(?:de|d[’'])\s*{RE_NOMBRE}\s*(?P<u>mois|ans?|ann[ée]es?)\b",
                           rf"pour\s+une\s+dur[ée]e\s+(?:de|d[’'])\s*{RE_NOMBRE}\s*(?P<u>mois|ans?|ann[ée]es?)\b"])
    if not m:
        return None, None
    n = _nombre(m.group("n"), m.group("np"))
    if n is None:
        return None, p
    return (n if m.group("u").lower() == "mois" else n * 12), p


def _delai_jours(m) -> int | None:
    n = _nombre(m.group("n"), m.group("np"))
    return None if n is None else n * UNITES.get(m.group("u").lower(), 1)


def analyser_texte(texte: str, nom_fichier: str = "") -> ResultatAnalyse:
    phs = phrases(texte)
    brut: dict = {"version_schema": VERSION_SCHEMA, "devise": "EUR", "preuves": {}}
    preuves: dict[str, str] = brut["preuves"]
    points: list[str] = ["Champs pré-remplis automatiquement par lecture du texte (sans IA) : relisez chacun "
                         "en vous appuyant sur la citation affichée à côté."]
    debut = texte[:700].lower()

    # type de document
    if re.search(r"\bavenant\b", debut):
        brut["type_document"] = "avenant"
        m = re.search(r"avenant\s*(?:n°|numéro|no|n o)?\s*(\d+)", texte[:1500], re.IGNORECASE)
        brut["numero_avenant"] = int(m.group(1)) if m else None
        _, mp = _premiere(phs, [r"contrat\s+(?:cadre\s+)?(?:n°|r[ée]f[ée]rence|r[ée]f\.?)\s*:?\s*([\w\-/]+)"])
        brut["contrat_parent"] = mp.group(1) if mp else None
    else:
        brut["type_document"] = "contrat"

    # client
    brut["client"] = _client(texte)
    if not brut["client"]:
        points.append("Client non identifié dans le texte : à saisir.")

    # sites
    sites = _sites(texte)
    site_u, phrase_site = _site_unique(phs)
    if len(sites) >= 2:
        brut["multi_site"] = True
        brut["sites_detectes"] = [{"site": s, "preuve": _coupe(p)} for s, p in sites]
        points.append(f"{len(sites)} sites repérés dans le texte : le contrat doit être scindé ; les montants "
                      "par site ne sont pas déduits.")
    else:
        brut["multi_site"] = False
        brut["sites_detectes"] = []
        brut["site"] = (sites[0][0] if sites else site_u)
        if not brut["site"]:
            points.append("Site non identifié dans le texte : à saisir.")

    # activité
    activite, scores = _activite(texte)
    if activite:
        brut["activite"] = activite
        mots = ACTIVITE_MOTS[activite]
        meilleur = max(phs, key=lambda ph: (sum(ph.lower().count(mot) for mot in mots), len(ph) < 400), default=None)
        preuves["activite"] = _coupe(meilleur) if meilleur else None
    else:
        points.append("Activité non tranchée (Accueil / Conciergerie / Hospitalité) : à choisir vous-même. "
                      f"Mots repérés : {', '.join(f'{a} {n}' for a, n in scores.items())}.")

    # montant
    montants = _montants(phs)
    ht = [m for m in montants if m["ht"]] or montants
    if ht:
        distincts = sorted({m["valeur"] for m in ht})
        choisi = ht[0]
        if not brut["multi_site"]:
            brut["montant_ht"] = choisi["valeur"]
            brut["periodicite"] = choisi["per"]
            preuves["montant_ht"] = _coupe(choisi["phrase"])
            if not choisi["ht"]:
                points.append("Montant trouvé sans mention « HT » : vérifiez s'il est hors taxes.")
            if choisi["per"] is None:
                points.append("Périodicité du montant non lisible : à préciser (mensuel, trimestriel, annuel).")
        if len(distincts) > 1:
            points.append("Plusieurs montants dans le texte (" + ", ".join(f"{v:g}" for v in distincts[:6]) +
                          ") : vérifiez lequel est la redevance.")
        if brut["multi_site"]:
            points.append("Contrat multi-site : aucun montant n'est réparti automatiquement, saisissez-les par site.")
    else:
        points.append("Aucun montant en euros trouvé : à saisir.")

    # dates : effet et échéance
    p_eff, _ = _premiere(phs, [r"prend effet|prendra effet|entre en vigueur|[àa] compter du|date d[’']effet|d[èe]s le"])
    d_eff = next(iter(trouver_dates(p_eff)), None) if p_eff else None
    p_ech, _ = _premiere(phs, [r"jusqu[’']au|expire le|prend fin le|arriv\w+ [àa] terme|prendra fin le|expirera le|[ée]ch[ée]ance|se terminera le"])
    d_ech = next(iter(trouver_dates(p_ech)), None) if p_ech and not re.search(r"pr[ée]avis", p_ech, re.I) else None
    brut["date_effet"] = d_eff.isoformat() if d_eff else None
    brut["date_echeance"] = d_ech.isoformat() if d_ech else None
    if d_ech:
        preuves["date_echeance"] = _coupe(p_ech)
    duree, p_duree = _duree(phs)
    brut["duree_mois"] = duree
    if duree is None and d_eff and d_ech:
        brut["duree_mois"] = max(1, round(((d_ech - d_eff).days + 1) / 30.4375))
        points.append("Durée déduite des dates d'effet et d'échéance.")
    if d_eff and duree and not d_ech:
        calc = ajouter_mois(d_eff, duree) - timedelta(days=1)
        brut["date_echeance"] = calc.isoformat()
        preuves["date_echeance"] = _coupe(p_duree or "")
        points.append(f"Échéance CALCULÉE ({calc.strftime('%d/%m/%Y')}) = date d'effet + durée − 1 jour : "
                      "aucune date de fin n'est écrite, à confirmer.")
    if not d_eff:
        points.append("Date d'effet non trouvée : à saisir.")
    if not brut["date_echeance"]:
        points.append("Date d'échéance non trouvée (contrat à durée indéterminée ?) : à saisir.")

    # reconduction
    p_rec, m_rec = _premiere(phs, [r"tacite reconduction|reconduit(?:e|s)? tacitement|reconduction tacite|renouvel[ée]e? tacitement",
                                   r"ne sera pas reconduit|sans reconduction|aucune reconduction|prendra fin de plein droit"])
    if p_rec:
        negatif = bool(re.search(r"ne sera pas reconduit|sans (?:tacite )?reconduction|aucune reconduction|de plein droit", p_rec, re.I)
                       ) and not re.search(r"tacite", p_rec, re.I)
        brut["reconduction_tacite"] = False if negatif else True
        pr = f"{_coupe(p_rec)}"
        preuves.setdefault("reconduction_tacite", pr)
        _, mr = _premiere(phs, [rf"p[ée]riodes?\s+(?:successives?\s+)?(?:de|d[’'])\s*{RE_NOMBRE}\s*(?P<u>mois|ans?|ann[ée]es?)\b",
                                rf"reconduit\w*\s+(?:pour|par)\s+(?:des\s+)?(?:p[ée]riodes?\s+)?(?:successives?\s+)?(?:de|d[’'])\s*{RE_NOMBRE}\s*(?P<u>mois|ans?|ann[ée]es?)\b"])
        if mr:
            n = _nombre(mr.group("n"), mr.group("np"))
            if n:
                brut["duree_reconduction_mois"] = n if mr.group("u").lower() == "mois" else n * 12
    else:
        brut["reconduction_tacite"] = None

    # préavis
    p_pre, m_pre = _premiere(phs, [rf"pr[ée]avis\s+(?:minimum\s+|minimal\s+)?(?:de|d[’'])\s*{RE_NOMBRE}\s*(?P<u>jours|semaines?|mois)\b",
                                   rf"{RE_NOMBRE}\s*(?P<u>jours|semaines?|mois)\s+(?:au moins\s+)?avant\s+(?:l[’'])?(?:[ée]ch[ée]ance|le terme|la fin)"])
    if m_pre:
        jours = _delai_jours(m_pre)
        if jours:
            brut["preavis_denonciation_jours"] = jours
            preuves["preavis_denonciation_jours"] = _coupe(p_pre)
            if m_pre.group("u").lower().startswith("mois"):
                points.append(f"Préavis exprimé en mois, converti en {jours} jours (mois de 30 jours) : "
                              "vérifiez la date limite exacte.")
    else:
        points.append("Préavis de dénonciation non trouvé : à saisir.")

    # indexation
    p_idx, _ = _premiere(phs, [r"index(?:ation|[ée]e?s?|er)\b|revalorisation|clause de r[ée]vision|r[ée]vis[ée]e?s?\s+(?:chaque|annuellement)|\bsyntec\b"])
    idx: dict = {"indice": None, "formule": None, "date_revision": None, "indice_reference": None}
    if p_idx:
        preuves["indexation"] = _coupe(p_idx)
        zone = " ".join(phs[max(0, phs.index(p_idx) - 1): phs.index(p_idx) + 4])
        for nom, motif in INDICES:
            if re.search(motif, zone, re.IGNORECASE):
                idx["indice"] = nom
                break
        mf = re.search(r"P1\s*=\s*P0[^.\n]{0,120}", zone)
        if mf:
            idx["formule"] = mf.group(0).strip(" .")
        mref = re.search(r"(?:indice|valeur)\s+(?:de r[ée]f[ée]rence|initial|de base)[^.;\n]{0,120}", zone, re.IGNORECASE)
        if mref:
            idx["indice_reference"] = mref.group(0).strip(" .")
        d_idx = next(iter(trouver_dates(zone)), None)
        if d_idx:
            idx["date_revision"] = d_idx.isoformat()
        elif d_eff and re.search(r"date anniversaire|chaque ann[ée]e|annuellement", zone, re.I):
            aujourd = date.today()
            prochaine = date(aujourd.year, d_eff.month, min(d_eff.day, 28))
            while prochaine <= aujourd:
                prochaine = date(prochaine.year + 1, prochaine.month, prochaine.day)
            idx["date_revision"] = prochaine.isoformat()
            points.append(f"Date de révision CALCULÉE ({prochaine.strftime('%d/%m/%Y')}) : prochaine date anniversaire "
                          "de la date d'effet. À confirmer.")
        if not idx["indice"]:
            points.append("Clause de révision trouvée mais indice non reconnu : à saisir. Aucune valeur d'indice n'est déduite.")
    brut["indexation"] = idx

    brut["preuves"] = {k: v for k, v in preuves.items() if v}
    brut["points_a_verifier"] = points
    donnees, erreurs = valider(brut)
    return ResultatAnalyse(donnees=donnees, brut=brut, json_texte=json.dumps(brut, ensure_ascii=False, indent=2),
                           erreurs=erreurs)
