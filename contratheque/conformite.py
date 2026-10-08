"""Contrôle de conformité indicatif d'un contrat (droit français), clause par clause.

Ce module applique des règles écrites à l'avance, sans réseau ni IA. Les articles cités ont été relus
sur Légifrance le 2026-10-08 (liens fournis). Il NE recherche PAS de jurisprudence et ne remplace pas un
avis juridique : pour la jurisprudence, utilisez la demande prête à coller dans le Projet claude.ai
(connecteur Légifrance) générée par `demande_claude`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .prefill import phrases
from .schema import ContratJSON

DATE_VERIFICATION = "2026-10-08"
LG = "https://www.legifrance.gouv.fr/codes/article_lc/"
ARTICLES = {
    "cc1170": ("Code civil, art. 1170", LG + "LEGIARTI000032041115"),
    "cc1171": ("Code civil, art. 1171", LG + "LEGIARTI000036829836"),
    "cc1195": ("Code civil, art. 1195", LG + "LEGIARTI000032041302"),
    "cc1231-5": ("Code civil, art. 1231-5", LG + "LEGIARTI000032010131"),
    "cmf112-1": ("Code monétaire et financier, art. L112-1", LG + "LEGIARTI000020096520"),
    "cmf112-2": ("Code monétaire et financier, art. L112-2", LG + "LEGIARTI000024039949"),
    "cconso215-1": ("Code de la consommation, art. L215-1", LG + "LEGIARTI000046194176"),
    "ccom442-1": ("Code de commerce, art. L442-1 (version en vigueur depuis le 20/08/2026)", LG + "LEGIARTI000054716237"),
    "ccom441-10": ("Code de commerce, art. L441-10 (signalé abrogé à compter du 01/01/2027)", LG + "LEGIARTI000038414392"),
}
NIVEAUX = {"risque": "🔴 Risque", "verifier": "🟠 À vérifier", "ok": "🟢 Rien à signaler"}
ORDRE = {"risque": 0, "verifier": 1, "ok": 2}


@dataclass
class Constat:
    clause: str
    niveau: str  # risque | verifier | ok
    probleme: str
    recommandation: str
    extrait: str | None = None
    references: list[tuple[str, str]] = field(default_factory=list)


def _refs(*cles: str) -> list[tuple[str, str]]:
    return [ARTICLES[c] for c in cles]


def _trouver(phs: list[str], motif: str):
    for p in phs:
        m = re.search(motif, p, re.IGNORECASE)
        if m:
            return p, m
    return None, None


def _coupe(p: str, n: int = 300) -> str:
    p = re.sub(r"\s+", " ", p).strip()
    return p if len(p) <= n else p[: n - 1] + "…"


def analyser_conformite(texte: str, contrat: ContratJSON | None = None) -> list[Constat]:
    phs = phrases(texte)
    c: list[Constat] = []

    # 1. Reconduction tacite et dénonciation
    p, _ = _trouver(phs, r"tacite|tacitement")
    tacite = (contrat.reconduction_tacite if contrat and contrat.reconduction_tacite is not None else bool(p))
    preavis = contrat.preavis_denonciation_jours if contrat else None
    if tacite:
        if not preavis:
            c.append(Constat("Reconduction tacite", "risque",
                             "Reconduction tacite sans délai de préavis de dénonciation identifié : le contrat peut se "
                             "reconduire sans que la sortie soit clairement encadrée.",
                             "Fixez par écrit un préavis et la forme de la dénonciation (lettre recommandée), et programmez "
                             "un rappel avant la date limite.", _coupe(p) if p else None, _refs("cconso215-1")))
        else:
            c.append(Constat("Reconduction tacite", "verifier",
                             f"Reconduction tacite avec préavis de {preavis} jours : à surveiller pour ne pas laisser passer la "
                             "date limite. Si le client est un consommateur, le prestataire doit l'informer par écrit entre 3 mois "
                             "et 1 mois avant le terme de la période autorisant le rejet de la reconduction (sinon il peut y mettre fin gratuitement).",
                             "Gardez le rappel de dénonciation actif ; vérifiez la qualité du client (professionnel ou consommateur).",
                             _coupe(p) if p else None, _refs("cconso215-1")))

    # 2. Clause pénale
    candidates = [ph for ph in phs if re.search(r"p[ée]nalit[ée]s?\b|clause p[ée]nale|indemnit[ée] forfaitaire", ph, re.I)
                  and not re.search(r"p[ée]nalit[ée]s? de retard", ph, re.I)]
    p = next((ph for ph in candidates if re.search(r"€|euros?|%", ph)), candidates[0] if candidates else None)
    if p:
        montants = [float(re.sub(r"[  .]", "", x).replace(",", ".")) for x in
                    re.findall(r"(\d{1,3}(?:[  .]\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)\s*(?:€|euros?)", p)]
        annuel = None
        if contrat and contrat.montant_ht:
            annuel = contrat.montant_ht * {"mensuel": 12, "trimestriel": 4, "annuel": 1}.get(contrat.periodicite or "", 0)
        gros = bool(montants and annuel and max(montants) >= 0.25 * annuel)
        c.append(Constat(
            "Clause pénale", "risque" if gros else "verifier",
            "Une pénalité forfaitaire est prévue. Le juge peut la modérer ou l'augmenter si elle est manifestement excessive ou "
            "dérisoire." + (" Son montant atteint au moins 25 % du montant annuel (seuil purement indicatif de l'application)." if gros else ""),
            "Vérifiez que la pénalité est proportionnée au préjudice prévisible et réciproque entre les parties.",
            _coupe(p), _refs("cc1231-5")))

    # 3. Limitation / exclusion de responsabilité
    p, _ = _trouver(phs, r"limit\w+ (?:de )?(?:sa |leur )?responsabilit|exclu\w+ (?:toute )?responsabilit|responsabilit\w*[^.]{0,80}\b(?:limit[ée]e?s?|exclue?s?|plafonn[ée]e?s?)\b|n[’']engage pas sa responsabilit|ne pourra [êe]tre tenu")
    if p:
        c.append(Constat("Limitation de responsabilité", "verifier",
                         "Une limitation ou exclusion de responsabilité est prévue. Une clause qui prive de sa substance l'obligation "
                         "essentielle du débiteur est réputée non écrite.",
                         "Vérifiez que la limitation n'enlève pas son sens à la prestation principale (ex. : exclusion de toute "
                         "responsabilité en cas de défaut d'exécution du service).", _coupe(p), _refs("cc1170")))

    # 4. Résiliation unilatérale / déséquilibre
    p, _ = _trouver(phs, r"r[ée]sili\w+[^.]{0,60}(?:[àa] tout moment|unilat[ée]ralement|sans motif|sans pr[ée]avis|[àa] sa seule discr[ée]tion)|[àa] sa seule discr[ée]tion")
    if p:
        c.append(Constat("Résiliation / droits unilatéraux", "verifier",
                         "Un droit de résiliation ou de décision unilatéral apparaît. S'il n'est pas réciproque, il peut être invoqué "
                         "comme créant un déséquilibre significatif entre professionnels, ou, dans un contrat d'adhésion, comme clause "
                         "non négociable réputée non écrite.",
                         "Comparez les droits des deux parties (préavis, motifs, indemnités) et rendez-les réciproques si possible.",
                         _coupe(p), _refs("ccom442-1", "cc1171")))

    # 5. Délais de paiement
    p, m = _trouver(phs, r"(?:paiement|payable|r[èe]glement|r[èe]gl[ée]e?s?|factures?)[^.]{0,80}?(\d{1,3})\s*jours")
    if not m:
        p, m = _trouver(phs, r"(\d{1,3})\s*jours[^.]{0,40}(?:date de facture|r[ée]ception de la facture|fin de mois)")
    periodique = bool(contrat and contrat.periodicite in ("mensuel", "trimestriel"))
    if m:
        jours = int(m.group(1))
        fin_mois = bool(re.search(r"fin de mois", p, re.I))
        plafond = 45 if periodique and not fin_mois else 60
        if fin_mois and jours > 45:
            niv, txt = "risque", f"{jours} jours fin de mois dépasse le plafond de 45 jours fin de mois."
        elif jours > plafond:
            niv = "risque"
            txt = (f"Délai de paiement de {jours} jours : au-delà du plafond de {plafond} jours après l'émission de la facture"
                   + (" (facturation périodique : 45 jours)." if plafond == 45 else "."))
        else:
            niv, txt = "ok", f"Délai de {jours} jours, dans les limites habituelles."
        c.append(Constat(
            "Délai de paiement", niv,
            txt + " L'article L441-10 est signalé comme abrogé à compter du 01/01/2027 sur Légifrance : vérifiez le texte qui le remplace.",
            "Alignez le délai sur le plafond légal en vigueur à la date de signature." if niv != "ok" else
            "Vérifiez à nouveau après le 01/01/2027.", _coupe(p), _refs("ccom441-10")))
    else:
        c.append(Constat("Délai de paiement", "verifier", "Aucun délai de paiement repéré dans le texte.",
                         "Précisez le délai de règlement (plafonds légaux entre professionnels).", None, _refs("ccom441-10")))
    if not re.search(r"p[ée]nalit[ée]s? de retard|taux d[’']int[ée]r[êe]t", texte, re.I):
        c.append(Constat("Pénalités de retard", "verifier",
                         "Pas de pénalités de retard ni de taux repérés. Les conditions de règlement doivent préciser le taux des "
                         "pénalités de retard (jamais inférieur à trois fois le taux d'intérêt légal) et l'indemnité forfaitaire pour "
                         "frais de recouvrement.", "Ajoutez ces mentions (dans le contrat ou les conditions de règlement).",
                         None, _refs("ccom441-10")))

    # 6. Indexation / révision de prix
    p, _ = _trouver(phs, r"indexation|r[ée]vision|revalorisation|syntec|\bICC\b|\bILC\b|\bILAT\b|\bIPC\b")
    if p:
        general = bool(re.search(r"\bIPC\b|prix [àa] la consommation|niveau g[ée]n[ée]ral des prix|\bSMIC\b|salaire minimum", p, re.I))
        if general:
            c.append(Constat("Indexation", "risque",
                             "L'indice semble être un indice général des prix ou le SMIC : la loi interdit les clauses d'indexation "
                             "fondées sur le SMIC, le niveau général des prix ou des salaires, ou sur des prix sans relation directe "
                             "avec l'objet de la convention ou l'activité d'une des parties.",
                             "Remplacez-le par un indice en relation directe avec la prestation (par exemple un indice de services).",
                             _coupe(p), _refs("cmf112-2", "cmf112-1")))
        else:
            c.append(Constat("Indexation", "verifier",
                             "Une clause de révision de prix existe. L'indexation automatique des prix de services est interdite "
                             "sauf exceptions : l'indice doit avoir une relation directe avec l'objet du contrat ou l'activité d'une "
                             "partie, et la période de variation de l'indice ne doit pas dépasser la durée entre deux révisions "
                             "(sinon la clause est réputée non écrite).",
                             "Vérifiez l'indice choisi, sa périodicité, et que la période de comparaison de l'indice correspond à "
                             "l'intervalle entre deux révisions.", _coupe(p), _refs("cmf112-1", "cmf112-2")))
    elif contrat and (contrat.duree_mois or 0) > 12:
        c.append(Constat("Indexation", "verifier", "Contrat de plus d'un an sans clause de révision de prix repérée.",
                         "Prévoyez une clause de révision (ou acceptez de supporter l'inflation sur toute la durée).",
                         None, _refs("cmf112-1")))

    # 7. Imprévision
    p, _ = _trouver(phs, r"impr[ée]vision|1195|changement de circonstances|renonce\w* [àa] se pr[ée]valoir")
    if p:
        c.append(Constat("Imprévision", "verifier",
                         "Le contrat traite des changements de circonstances. Le Code civil permet de demander une renégociation si "
                         "un changement imprévisible rend l'exécution excessivement onéreuse pour une partie qui n'en avait pas "
                         "accepté le risque.", "Vérifiez si le contrat écarte cette faculté et si c'est voulu.", _coupe(p), _refs("cc1195")))

    # 8. Rupture et préavis
    if preavis is not None and preavis < 60:
        c.append(Constat("Préavis de rupture", "verifier",
                         f"Préavis de {preavis} jours. Entre professionnels, rompre brutalement une relation commerciale établie sans "
                         "préavis écrit suffisant engage la responsabilité de son auteur ; un préavis de dix-huit mois met à l'abri d'un "
                         "grief sur la durée.", "Pour une relation ancienne, appréciez si le préavis contractuel est suffisant.",
                         None, _refs("ccom442-1")))

    # 9. Droit applicable et juridiction
    if not re.search(r"droit fran[çc]ais|loi fran[çc]aise|tribunal de commerce|tribunaux? (?:comp[ée]tents?|de )|juridiction", texte, re.I):
        c.append(Constat("Droit applicable et juridiction", "verifier",
                         "Aucune clause de droit applicable ni de juridiction compétente repérée.",
                         "Ajoutez une clause attributive de compétence et de droit applicable.", None, []))

    c.sort(key=lambda x: ORDRE[x.niveau])
    if not any(x.niveau != "ok" for x in c):
        c.append(Constat("Synthèse", "ok", "Aucun point sensible repéré par les règles de l'application.",
                         "Cela ne vaut pas validation juridique.", None, []))
    return c


def demande_claude(nom_contrat: str) -> str:
    """Texte à coller dans le Projet claude.ai (connecteur Légifrance activé) avec le contrat en pièce jointe."""
    return (
        f"Contrôle de conformité du contrat « {nom_contrat} » (document joint), droit français.\n"
        "1) Parcours le contrat clause par clause.\n"
        "2) Pour chaque clause à risque (clauses abusives ou déséquilibrées, reconduction tacite, préavis, pénalités, limitation de "
        "responsabilité, délais de paiement, indexation, rupture), cherche dans Légifrance les textes applicables ET la jurisprudence "
        "pertinente (Cour de cassation, cours d'appel), et cite pour chacune sa référence exacte et son lien Légifrance.\n"
        "3) Ne cite aucun texte ni aucune décision que tu n'as pas retrouvé et lu ; si tu n'en trouves pas, dis-le.\n"
        "4) Rends un tableau : clause | extrait exact | risque (faible/moyen/élevé) | texte ou décision applicable | recommandation de rédaction.\n"
        "5) Termine par les 3 points à négocier en priorité."
    )


def rapport_markdown(nom_contrat: str, constats: list[Constat]) -> str:
    lignes = [f"# Contrôle de conformité – {nom_contrat}", "",
              f"_Contrôle indicatif par règles (droit français), articles relus sur Légifrance le {DATE_VERIFICATION}. "
              "Aucune jurisprudence recherchée. Ne remplace pas un avis juridique._", ""]
    for x in constats:
        lignes += [f"## {NIVEAUX[x.niveau]} – {x.clause}", x.probleme, f"**Recommandation** : {x.recommandation}"]
        if x.extrait:
            lignes.append(f"> {x.extrait}")
        for libelle, url in x.references:
            lignes.append(f"- [{libelle}]({url})")
        lignes.append("")
    return "\n".join(lignes)
