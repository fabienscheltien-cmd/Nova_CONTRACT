"""Contrathèque : page unique Streamlit (coller → valider → suivre)."""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from contratheque import config, db, extraction, multisite, revision, service, suivi
from contratheque.controles import CHAMPS_DATES, chercher_preuve, diagnostiquer_dates
from contratheque.outils import cle_contrat, formater_date, formater_montant, lire_date
from contratheque.schema import ACTIVITES, PERIODICITES, TYPES_DOCUMENT, valider

st.set_page_config(page_title="Contrathèque", page_icon="📑", layout="wide")

JAUNE = "background:#fff3bf;color:#212529;border-left:4px solid #f08c00;padding:4px 10px;border-radius:4px;margin-bottom:4px"


# --------------------------------------------------------------------------- démarrage

@st.cache_resource(show_spinner=False)
def demarrer() -> str:
    """Une fois par lancement : sauvegarde datée de la base, puis mise à jour des alertes."""
    config.DATA.mkdir(parents=True, exist_ok=True)
    db.sauvegarder_base(config.DB, config.SAUVEGARDES)
    conn = db.connecter(config.DB)
    db.initialiser(conn)
    cfg = config.charger()
    message = ""
    if cfg.get("racine_onedrive"):
        message = service.mettre_a_jour(conn, Path(cfg["racine_onedrive"]), bool(cfg.get("outlook_actif")))
    conn.close()
    return message


def premier_lancement() -> None:
    st.title("📑 Contrathèque")
    st.subheader("Bienvenue : où sont rangés vos contrats ?")
    st.write("Choisissez le dossier racine OneDrive. Les contrats y seront classés par client, "
             "site et activité. Vous ne le ferez qu'une fois.")

    def parcourir():
        choix = config.parcourir_dossier(st.session_state.get("racine_saisie", ""))
        if choix:
            st.session_state["racine_saisie"] = choix

    st.session_state.setdefault("racine_saisie", config.dossier_onedrive_probable())
    st.text_input("Dossier racine des contrats", key="racine_saisie")
    c1, c2, _ = st.columns([1, 1, 4])
    c1.button("Parcourir…", on_click=parcourir)
    if c2.button("Enregistrer", type="primary"):
        dossier = Path(st.session_state["racine_saisie"].strip().strip('"'))
        if dossier.is_dir():
            config.sauver({**config.charger(), "racine_onedrive": str(dossier)})
            st.rerun()
        else:
            st.error("Ce dossier n'existe pas. Vérifiez le chemin ou utilisez « Parcourir… ».")


# --------------------------------------------------------------------------- barre latérale et bandeau

def barre_laterale(conn, racine: Path, cfg: dict, aujourdhui: date) -> None:
    with st.sidebar:
        st.header("📑 Contrathèque")
        if st.button("🔄 Mettre à jour", help="Recalcule les alertes et le CA, régénère les fichiers .ics"):
            st.success(service.mettre_a_jour(conn, racine, bool(cfg.get("outlook_actif")), aujourdhui))
        st.divider()
        outlook = st.checkbox("Ajouter aussi les rappels à Outlook (si disponible)",
                              value=bool(cfg.get("outlook_actif")),
                              help="Outlook classique uniquement. Sinon, les fichiers .ics sont utilisés.")
        if outlook != bool(cfg.get("outlook_actif")):
            config.sauver({**cfg, "outlook_actif": outlook})
            st.rerun()
        st.caption(f"Dossier des contrats :\n\n`{racine}`")
        with st.expander("Changer de dossier"):
            nouveau = st.text_input("Nouveau dossier racine", value=str(racine), key="nouvelle_racine")
            if st.button("Enregistrer le dossier") and Path(nouveau).is_dir():
                config.sauver({**cfg, "racine_onedrive": nouveau})
                st.rerun()


def bandeau_a_traiter(conn, sits: list[dict], aujourdhui: date) -> None:
    a_faire = suivi.a_traiter(sits, db.jalons_traites(conn), aujourdhui)
    if not a_faire:
        return
    with st.container(border=True):
        st.markdown(f"### 🔔 À traiter ({len(a_faire)})")
        st.caption("Échéances, révisions et dates limites de dénonciation dans les 30 jours ou dépassées.")
        for k, j in enumerate(a_faire):
            ecart = (j.date - aujourdhui).days
            statut = (f"🔴 dépassé de {-ecart} j" if ecart < 0 else
                      "🔴 aujourd'hui" if ecart == 0 else f"🟠 dans {ecart} j")
            c1, c2, c3 = st.columns([2, 7, 1])
            c1.write(f"**{formater_date(j.date)}**  \n{statut}")
            c2.write(f"{j.libelle}{' (calculée)' if j.calculee else ''} — {j.contrat}")
            if c3.button("Traité", key=f"traite_{k}_{j.cle}_{j.type}"):
                db.marquer_traite(conn, *j.identifiant)
                st.rerun()


# --------------------------------------------------------------------------- ajout

def reinitialiser() -> None:
    for cle in ("lot", "lot_i", "fichier_lot"):
        st.session_state.pop(cle, None)
    st.session_state["n"] = st.session_state.get("n", 0) + 1


def onglet_ajout(conn, racine: Path, cfg: dict, sits: list[dict], aujourdhui: date) -> None:
    for message in st.session_state.pop("messages_ok", []):
        st.success(message)
    n = st.session_state.setdefault("n", 0)
    lot = st.session_state.get("lot")
    if lot is None:
        ecran_collage(n)
    else:
        ecran_validation(conn, racine, cfg, sits, aujourdhui, lot, n)


def ecran_collage(n: int) -> None:
    st.subheader("1. Coller le résultat de l'analyse")
    texte = st.text_area("Coller ici", height=240, key=f"texte_{n}",
                         placeholder="Collez la réponse de l'analyse (le bloc JSON suffit, le texte autour est ignoré). "
                                     "Plusieurs blocs collés d'un coup sont traités comme un lot.")
    fichier = st.file_uploader("Fichier du contrat (facultatif) — PDF ou Word",
                               type=["pdf", "doc", "docx"], key=f"fichier_{n}")
    if st.button("Analyser", type="primary"):
        resultats = extraction.analyser_lot(texte)
        problemes = [(k, r) for k, r in enumerate(resultats, start=1) if r.erreurs or r.donnees is None]
        if problemes:
            for k, r in problemes:
                prefixe = f"Bloc {k} : " if len(resultats) > 1 else ""
                st.error("**Analyse impossible.**\n\n" + "\n".join(f"- {prefixe}{e}" for e in r.erreurs))
            return
        st.session_state["lot"] = resultats
        st.session_state["lot_i"] = 0
        st.session_state["fichier_lot"] = (fichier.name, fichier.getvalue()) if fichier and len(resultats) == 1 else None
        st.session_state["fichier_lot_ignore"] = bool(fichier and len(resultats) > 1)
        st.rerun()


def ecran_validation(conn, racine, cfg, sits, aujourdhui, lot, n) -> None:
    i = st.session_state.get("lot_i", 0)
    res = lot[i]
    entete = f"2. Vérifier et valider" + (f" — contrat {i + 1} sur {len(lot)}" if len(lot) > 1 else "")
    st.subheader(entete)
    c1, c2, _ = st.columns([1, 1, 5])
    if c1.button("↩ Recommencer"):
        reinitialiser()
        st.rerun()
    if len(lot) > 1 and c2.button("Ignorer ce bloc"):
        passer_au_suivant(i, lot, [])
        st.rerun()

    fichier = st.session_state.get("fichier_lot")
    if len(lot) > 1:
        if i == 0 and st.session_state.get("fichier_lot_ignore"):
            st.info("Un seul fichier a été déposé pour plusieurs contrats : joignez le bon fichier à chaque bloc ci-dessous.")
        up = st.file_uploader("Fichier de ce contrat (facultatif)", type=["pdf", "doc", "docx"], key=f"fichier_{n}_{i}")
        fichier = (up.name, up.getvalue()) if up else None
    elif fichier:
        st.caption(f"📎 Fichier joint : {fichier[0]}")

    if res.donnees.multi_site:
        ecran_scission(conn, racine, cfg, aujourdhui, res, fichier, lot, i, n)
    else:
        formulaire_simple(conn, racine, cfg, sits, aujourdhui, res, fichier, lot, i, n)


def passer_au_suivant(i: int, lot: list, messages: list[str]) -> None:
    st.session_state.setdefault("messages_ok", []).extend(messages)
    if i + 1 < len(lot):
        st.session_state["lot_i"] = i + 1
    else:
        reinitialiser()


def afficher_points(points: list[str]) -> None:
    if points:
        st.warning("**⚠️ Points à vérifier avant d'enregistrer**\n\n" + "\n".join(f"- {p}" for p in points))


def ligne_champ(label: str, preuves: dict, champ_preuve: str, creer, messages: list[str] | None = None):
    """Un champ éditable (à gauche) et sa citation (à droite) ; surligné si la date pose question."""
    gauche, droite = st.columns([3, 2])
    with gauche:
        if messages:
            st.markdown(f'<div style="{JAUNE}">⚠️ <b>{label}</b> : {" ; ".join(messages)}</div>',
                        unsafe_allow_html=True)
        valeur = creer()
    with droite:
        preuve = chercher_preuve(preuves, champ_preuve)
        if preuve:
            st.markdown(f"<div style='font-size:0.85rem;opacity:.85;border-left:3px solid #adb5bd;"
                        f"padding-left:8px;margin-top:1.7rem'>📎 « {preuve} »</div>", unsafe_allow_html=True)
        else:
            st.caption(" ")
    return valeur


def option(options, valeur):
    return list(options).index(valeur) if valeur in options else None


def messages_resultat(resultats: list[service.ResultatEnregistrement]) -> list[str]:
    r0 = resultats[0]
    b = r0.sync.bilan
    lignes = []
    for r in resultats:
        lignes.append(f"✅ Enregistré (version {r.version}"
                      + (f", avenant {r.numero_avenant}" if r.numero_avenant else "") + ") — "
                      + (f"fichier rangé : `{r.chemin_fichier}`" if r.chemin_fichier else "sans fichier"))
        lignes += [f"⚠️ {a}" for a in r.avertissements]
    lignes.append(f"🔔 Alertes : {b.nouvelles} créée(s), {b.modifiees} mise(s) à jour. " + " ".join(r0.sync.messages))
    return ["\n\n".join(lignes)]


def formulaire_simple(conn, racine, cfg, sits, aujourdhui, res, fichier, lot, i, n) -> None:
    d = res.donnees.model_dump(mode="json")
    idx, preuves, points = d["indexation"], d["preuves"], d["points_a_verifier"]
    afficher_points(points)
    diag = diagnostiquer_dates(
        {"date_effet": d["date_effet"], "date_echeance": d["date_echeance"],
         "date_limite_denonciation": d["date_limite_denonciation"], "date_revision": idx["date_revision"],
         "preavis_denonciation_jours": d["preavis_denonciation_jours"],
         "indexation_presente": bool(idx["indice"] or idx["formule"] or idx["date_revision"])},
        points, preuves)
    if d["client"] and d["site"] and d["activite"]:
        existant = next((s for s in sits if s["cle"] == cle_contrat(d["client"], d["site"], d["activite"])), None)
        if existant:
            st.info(f"Un contrat existe déjà pour {d['client']} – {d['site']} – {d['activite']} : "
                    "l'enregistrement ajoutera une nouvelle version, l'ancienne reste dans l'historique.")

    k = lambda nom: f"v{n}_{i}_{nom}"
    with st.form(f"form_{n}_{i}"):
        st.markdown("##### Qui et quoi")
        client = ligne_champ("Client", preuves, "client", lambda: st.text_input("Client", d["client"] or "", key=k("client")))
        site = ligne_champ("Site", preuves, "site", lambda: st.text_input("Site", d["site"] or "", key=k("site")))
        activite = ligne_champ("Activité", preuves, "activite", lambda: st.selectbox(
            "Activité", ACTIVITES, index=option(ACTIVITES, d["activite"]), placeholder="À choisir", key=k("activite")),
            ["à choisir : non déterminée par l'analyse"] if not d["activite"] else None)
        c1, c2, c3 = st.columns(3)
        type_doc = c1.selectbox("Type de document", TYPES_DOCUMENT,
                                index=option(TYPES_DOCUMENT, d["type_document"]) or 0, key=k("type"))
        numero = c2.number_input("Numéro d'avenant", min_value=1, step=1, value=d["numero_avenant"], key=k("num"))
        parent = c3.text_input("Contrat parent", d["contrat_parent"] or "", key=k("parent"))

        st.markdown("##### Argent")
        montant = ligne_champ("Montant HT", preuves, "montant_ht", lambda: st.number_input(
            "Montant HT", min_value=0.0, step=50.0, format="%.2f", value=d["montant_ht"], key=k("montant")))
        c1, c2 = st.columns(2)
        periodicite = c1.selectbox("Périodicité", PERIODICITES, index=option(PERIODICITES, d["periodicite"]),
                                   placeholder="À choisir", key=k("period"))
        devise = c2.text_input("Devise", d["devise"] or "EUR", key=k("devise"))

        st.markdown("##### Dates et durée")
        date_effet = ligne_champ("Date d'effet", preuves, "date_effet", lambda: st.text_input(
            "Date d'effet (AAAA-MM-JJ)", d["date_effet"] or "", key=k("effet")), diag.get("date_effet"))
        date_echeance = ligne_champ("Date d'échéance", preuves, "date_echeance", lambda: st.text_input(
            "Date d'échéance (AAAA-MM-JJ)", d["date_echeance"] or "", key=k("echeance")), diag.get("date_echeance"))
        c1, c2 = st.columns(2)
        duree = c1.number_input("Durée (mois)", min_value=0, step=1, value=d["duree_mois"], key=k("duree"))
        tacite = c2.selectbox("Reconduction tacite", ["oui", "non"], key=k("tacite"),
                              index=None if d["reconduction_tacite"] is None else (0 if d["reconduction_tacite"] else 1),
                              placeholder="Non précisé")
        c1, c2 = st.columns(2)
        duree_reco = c1.number_input("Durée de reconduction (mois)", min_value=0, step=1,
                                     value=d["duree_reconduction_mois"], key=k("reco"))
        preavis = ligne_champ("Préavis de dénonciation (jours)", preuves, "preavis_denonciation_jours",
                              lambda: st.number_input("Préavis de dénonciation (jours)", min_value=0, step=1,
                                                      value=d["preavis_denonciation_jours"], key=k("preavis")))
        limite = ligne_champ("Date limite de dénonciation", preuves, "date_limite_denonciation", lambda: st.text_input(
            "Date limite de dénonciation (AAAA-MM-JJ)", d["date_limite_denonciation"] or "", key=k("limite"),
            help="Laissée vide, elle est calculée : échéance − préavis."), diag.get("date_limite_denonciation"))

        st.markdown("##### Indexation (révision des prix)")
        indice = ligne_champ("Indice", preuves, "indice", lambda: st.text_input("Indice", idx["indice"] or "", key=k("indice")))
        formule = st.text_input("Formule", idx["formule"] or "", key=k("formule"))
        date_rev = ligne_champ("Date de révision", preuves, "date_revision", lambda: st.text_input(
            "Prochaine date de révision (AAAA-MM-JJ)", idx["date_revision"] or "", key=k("rev")),
            diag.get("date_revision"))
        indice_ref = st.text_input("Indice de référence", idx["indice_reference"] or "", key=k("iref"))
        valider_ = st.form_submit_button("Valider et enregistrer", type="primary")

    if not valider_:
        return
    brut = {
        "version_schema": 1, "client": client, "site": site, "activite": activite, "type_document": type_doc,
        "numero_avenant": int(numero) if (type_doc == "avenant" and numero) else None,
        "contrat_parent": parent, "montant_ht": montant, "periodicite": periodicite, "devise": devise,
        "date_effet": date_effet, "date_echeance": date_echeance, "duree_mois": int(duree) if duree else None,
        "reconduction_tacite": tacite, "duree_reconduction_mois": int(duree_reco) if duree_reco else None,
        "preavis_denonciation_jours": int(preavis) if preavis else None, "date_limite_denonciation": limite,
        "indexation": {"indice": indice, "formule": formule, "date_revision": date_rev, "indice_reference": indice_ref},
        "preuves": preuves, "points_a_verifier": points,
    }
    contrat, erreurs = valider(brut)
    if not erreurs:
        manquants = [nom for nom, v in (("le client", contrat.client), ("le site", contrat.site),
                                        ("l'activité", contrat.activite)) if not v]
        if manquants:
            erreurs = ["Renseignez " + ", ".join(manquants) + "."]
    if erreurs:
        st.error("**Enregistrement impossible.**\n\n" + "\n".join(f"- {e}" for e in erreurs))
        return
    try:
        resultats = service.enregistrer_contrat(conn, racine, contrat, fichier, res.json_texte,
                                                bool(cfg.get("outlook_actif")), aujourdhui)
    except Exception as exc:
        st.error(f"L'enregistrement a échoué : {exc}")
        return
    passer_au_suivant(i, lot, messages_resultat([resultats]))
    st.rerun()


# --------------------------------------------------------------------------- multi-site

def ecran_scission(conn, racine, cfg, aujourdhui, res, fichier, lot, i, n) -> None:
    c = res.donnees
    sites = {s.site for s in c.sites_detectes if s.site}
    activites = {s.activite for s in c.sites_detectes if s.activite}
    st.error(f"⚠️ **MULTI-SITE : {len(sites)} site(s) / {len(activites)} activité(s) détecté(s), "
             "à scinder avant enregistrement.** Le bouton « Valider » reste bloqué tant que le contrat "
             "n'est pas scindé en lignes valides (au moins 2).")
    d = c.model_dump(mode="json")
    idx, preuves, points = d["indexation"], d["preuves"], d["points_a_verifier"]
    afficher_points(points)
    k = lambda nom: f"s{n}_{i}_{nom}"

    st.markdown("##### Partie commune à tous les sites")
    a, b, e = st.columns(3)
    client = a.text_input("Client", d["client"] or "", key=k("client"))
    type_doc = b.selectbox("Type de document", TYPES_DOCUMENT, index=option(TYPES_DOCUMENT, d["type_document"]) or 0, key=k("type"))
    parent = e.text_input("Contrat parent", d["contrat_parent"] or "", key=k("parent"))
    a, b, e, f = st.columns(4)
    date_effet = a.text_input("Date d'effet par défaut", d["date_effet"] or "", key=k("effet"))
    date_echeance = b.text_input("Échéance par défaut", d["date_echeance"] or "", key=k("ech"))
    preavis = e.number_input("Préavis (jours)", min_value=0, step=1, value=d["preavis_denonciation_jours"], key=k("preavis"))
    tacite = f.selectbox("Reconduction tacite", ["oui", "non"], key=k("tacite"), placeholder="Non précisé",
                         index=None if d["reconduction_tacite"] is None else (0 if d["reconduction_tacite"] else 1))
    a, b, e, f = st.columns(4)
    duree = a.number_input("Durée (mois)", min_value=0, step=1, value=d["duree_mois"], key=k("duree"))
    duree_reco = b.number_input("Reconduction (mois)", min_value=0, step=1, value=d["duree_reconduction_mois"], key=k("reco"))
    devise = e.text_input("Devise", d["devise"] or "EUR", key=k("devise"))
    indice = f.text_input("Indice", idx["indice"] or "", key=k("indice"))
    formule = st.text_input("Formule d'indexation", idx["formule"] or "", key=k("formule"))
    indice_ref = st.text_input("Indice de référence", idx["indice_reference"] or "", key=k("iref"))

    st.markdown("##### Une ligne par site + activité")
    st.caption("Chaque ligne a son montant, ses dates et ses alertes. Ajoutez ou supprimez des lignes si besoin. "
               "Les montants ne sont jamais répartis automatiquement.")
    cle_df = f"df0_{n}_{i}"
    if cle_df not in st.session_state:
        initiales = multisite.lignes_initiales(c) or [{}, {}]
        colonnes = ["site", "activite", "montant_ht", "periodicite", "date_effet", "date_echeance",
                    "date_limite_denonciation", "date_revision", "preuve"]
        st.session_state[cle_df] = pd.DataFrame(initiales, columns=colonnes).astype(object)
    edite = st.data_editor(
        st.session_state[cle_df], key=k("editeur"), num_rows="dynamic", hide_index=True, width="stretch",
        column_config={
            "site": st.column_config.TextColumn("Site", required=True),
            "activite": st.column_config.SelectboxColumn("Activité", options=list(ACTIVITES), required=True),
            "montant_ht": st.column_config.NumberColumn("Montant HT", min_value=0.0, format="%.2f"),
            "periodicite": st.column_config.SelectboxColumn("Périodicité", options=list(PERIODICITES)),
            "date_effet": st.column_config.TextColumn("Date d'effet", help="AAAA-MM-JJ"),
            "date_echeance": st.column_config.TextColumn("Échéance", help="AAAA-MM-JJ"),
            "date_limite_denonciation": st.column_config.TextColumn("Limite de dénonciation", help="Vide = échéance − préavis"),
            "date_revision": st.column_config.TextColumn("Prochaine révision", help="AAAA-MM-JJ"),
            "preuve": st.column_config.TextColumn("Citation du bordereau", disabled=True),
        })
    lignes = edite.astype(object).where(edite.notna(), None).to_dict("records")

    commun = {
        "version_schema": 1, "client": client, "type_document": type_doc, "contrat_parent": parent,
        "numero_avenant": d["numero_avenant"], "periodicite": d["periodicite"], "devise": devise,
        "date_effet": date_effet, "date_echeance": date_echeance, "duree_mois": int(duree) if duree else None,
        "reconduction_tacite": tacite, "duree_reconduction_mois": int(duree_reco) if duree_reco else None,
        "preavis_denonciation_jours": int(preavis) if preavis else None,
        "date_limite_denonciation": d["date_limite_denonciation"],
        "indexation": {"indice": indice, "formule": formule, "date_revision": idx["date_revision"],
                       "indice_reference": indice_ref},
        "preuves": preuves, "points_a_verifier": points,
    }
    contrats, erreurs = multisite.scinder(commun, lignes)
    for e in erreurs:
        st.error(e)
    for k_, ct in enumerate(contrats, start=1):
        remarques = []
        if ct.montant_ht is None:
            remarques.append("montant absent (la répartition n'est pas écrite dans le document ?)")
        if ct.periodicite is None:
            remarques.append("périodicité non précisée")
        dg = diagnostiquer_dates(
            {"date_effet": ct.date_effet, "date_echeance": ct.date_echeance,
             "date_limite_denonciation": ct.date_limite_denonciation, "date_revision": ct.indexation.date_revision,
             "preavis_denonciation_jours": ct.preavis_denonciation_jours,
             "indexation_presente": bool(ct.indexation.indice or ct.indexation.formule)},
            [], {})
        remarques += [f"{CHAMPS_DATES[ch].lower()} : {' ; '.join(m)}" for ch, m in dg.items()]
        if remarques:
            st.warning(f"**{ct.site} – {ct.activite}** : " + " | ".join(remarques))

    bloque = bool(erreurs) or len(contrats) < 2
    if st.button(f"Valider et enregistrer les {len(contrats)} lignes", type="primary", disabled=bloque):
        try:
            resultats = service.enregistrer_multisite(conn, racine, contrats, fichier, res.json_texte,
                                                      bool(cfg.get("outlook_actif")), aujourdhui)
        except Exception as exc:
            st.error(f"L'enregistrement a échoué (rien n'a été enregistré) : {exc}")
            return
        passer_au_suivant(i, lot, messages_resultat(resultats))
        st.rerun()


# --------------------------------------------------------------------------- suivi

def ouvrir_dossier(chemin: str) -> None:
    if sys.platform == "win32":
        os.startfile(str(Path(chemin).parent))  # type: ignore[attr-defined]


def onglet_suivi(conn, sits: list[dict], aujourdhui: date) -> None:
    if not sits:
        st.info("Aucun contrat enregistré pour le moment. Commencez par l'onglet « Ajouter un contrat ».")
        return
    sites_par_origine: dict[str, int] = {}
    for s in sits:
        if s.get("groupe_origine"):
            sites_par_origine[s["groupe_origine"]] = sites_par_origine.get(s["groupe_origine"], 0) + 1

    st.subheader("Chiffre d'affaires annuel récurrent (HT)")
    par_devise = suivi.par_devise(sits)
    colonnes = st.columns(max(len(par_devise), 1))
    for col, (devise, liste) in zip(colonnes, par_devise.items()):
        col.metric(f"Total ({devise})", formater_montant(suivi.ca_total(liste, aujourdhui), devise),
                   help="Mensuel ×12, trimestriel ×4, annuel ×1. Contrats en cours ou reconduits tacitement. Ponctuel exclu.")

    for devise, liste in par_devise.items():
        gauche, droite = st.columns(2)
        with gauche:
            st.markdown(f"**Par client ({devise})**")
            par_client = suivi.ca_par_client(liste, aujourdhui)
            if par_client:
                st.dataframe(pd.DataFrame({"Client": list(par_client), "CA annuel": [formater_montant(v, devise) for v in par_client.values()]}),
                             hide_index=True, width="stretch")
        with droite:
            st.markdown(f"**12 prochains mois ({devise}, CA lissé)**")
            mensuel = suivi.ca_mensuel(liste, aujourdhui)
            st.bar_chart(pd.DataFrame({"CA": [v for _, v in mensuel]}, index=[m.strftime("%Y-%m") for m, _ in mensuel]))

    st.subheader("Tous les contrats")
    lignes = []
    for s in sorted(sits, key=lambda x: (x["client"].lower(), x["site"].lower(), x["activite"])):
        limite, calculee = suivi.date_limite_denonciation(s)
        valeur = suivi.valeur_sur_duree(s)
        lignes.append({
            "Client": s["client"], "Site": s["site"], "Activité": s["activite"],
            "Document": ("Contrat" if s["a_contrat"] else "Avenant seul") + (f" + {s['nb_avenants']} avenant(s)" if s["nb_avenants"] else ""),
            "Multi-site": f"{sites_par_origine[s['groupe_origine']]} lignes" if s.get("groupe_origine") else "",
            "Montant HT": formater_montant(s["montant_ht"], s["devise"]), "Périodicité": s["periodicite"] or "—",
            "CA annuel": formater_montant(suivi.ca_annuel(s), s["devise"]) if suivi.ca_annuel(s) else "—",
            "Sur la durée": formater_montant(valeur, s["devise"]) if valeur is not None else "—",
            "Échéance": formater_date(s["date_echeance"]),
            "Dénonciation avant": formater_date(limite) + (" (calc.)" if calculee and limite else ""),
            "Révision": formater_date(s["date_revision"]),
        })
    st.dataframe(pd.DataFrame(lignes), hide_index=True, width="stretch")

    st.subheader("Échéances à venir")
    mois = st.radio("Horizon", [3, 6, 12], format_func=lambda m: f"{m} mois", horizontal=True)
    jalons = suivi.timeline(sits, aujourdhui, mois)
    if jalons:
        st.dataframe(pd.DataFrame([{"Date": formater_date(j.date), "Dans": f"{(j.date - aujourdhui).days} j",
                                    "Quoi": j.libelle + (" (calculée)" if j.calculee else ""), "Contrat": j.contrat}
                                   for j in jalons]), hide_index=True, width="stretch")
    else:
        st.write(f"Rien dans les {mois} prochains mois.")

    st.subheader("Historique et fichiers")
    choix = {f"{s['client']} – {s['site']} – {s['activite']}": s["cle"] for s in sits}
    nom = st.selectbox("Contrat", list(choix), index=None, placeholder="Choisir un contrat")
    if nom:
        histo = db.historique(conn, choix[nom])
        st.dataframe(pd.DataFrame([{
            "Document": "Contrat" if h["type_document"] == "contrat" else f"Avenant {h['numero_avenant']}",
            "Version": h["version"], "En vigueur": "oui" if h["courant"] else "remplacée",
            "Enregistré le": h["cree_le"].replace("T", " "), "Montant HT": formater_montant(h["montant_ht"], h["devise"]),
            "Échéance": formater_date(h["date_echeance"]), "Fichier": h["chemin_fichier"] or "—",
            "Document d'origine": (h["groupe_origine"] or "")[:8],
        } for h in histo]), hide_index=True, width="stretch")
        dernier = next((h["chemin_fichier"] for h in reversed(histo) if h["chemin_fichier"]), None)
        if dernier and sys.platform == "win32" and st.button("Ouvrir le dossier du contrat"):
            ouvrir_dossier(dernier)


def onglet_revision(sits: list[dict]) -> None:
    st.subheader("Révision de prix (suggestion)")
    st.caption("Saisissez vous-même l'indice publié : l'application n'invente aucune valeur d'indice.")
    candidats = [s for s in sits if s.get("indice") or s.get("formule") or s.get("date_revision")]
    if not candidats:
        st.info("Aucun contrat avec une clause d'indexation.")
        return
    libelles = {f"{s['client']} – {s['site']} – {s['activite']}": s for s in candidats}
    s = libelles[st.selectbox("Contrat", list(libelles))]
    st.markdown(f"**Clause** : indice « {s.get('indice') or '—'} » · révision le {formater_date(s.get('date_revision'))} · "
                f"référence : {s.get('indice_reference') or '—'}")
    if s.get("formule"):
        st.markdown(f"**Formule du contrat** : {s['formule']}")
    if s.get("montant_ht") is None:
        st.warning("Ce contrat n'a pas de montant HT enregistré.")
        return
    c1, c2, c3 = st.columns(3)
    ref = c1.number_input("Indice de référence", min_value=0.0, format="%.2f",
                          value=revision.extraire_nombre(s.get("indice_reference")), key=f"ref_{s['cle']}")
    nouveau = c2.number_input("Nouvel indice (à saisir)", min_value=0.0, format="%.2f", value=None, key=f"new_{s['cle']}")
    fixe = c3.number_input("Part fixe de la formule (%)", min_value=0.0, max_value=100.0, value=0.0, key=f"fixe_{s['cle']}",
                           help="0 si la formule est simplement montant × nouvel indice / indice de référence.")
    if not ref or not nouveau:
        return
    ancien = s["montant_ht"]
    revise = revision.montant_revise(ancien, ref, nouveau, fixe)
    st.metric("Montant révisé suggéré", formater_montant(revise, s["devise"]),
              f"{revision.variation_pct(ancien, revise):+.2f} % vs {formater_montant(ancien, s['devise'])}")
    st.caption("Calcul indicatif : vérifiez-le avec la formule exacte du contrat avant envoi.")
    courrier = revision.modele_courrier(
        client=s["client"], site=s["site"], activite=s["activite"], date_revision=s.get("date_revision"),
        indice=s.get("indice"), indice_reference=ref, indice_nouveau=nouveau, ancien_montant=ancien,
        nouveau_montant=revise, periodicite=s.get("periodicite"), devise=s["devise"],
        formule=s.get("formule"), part_fixe_pct=fixe)
    st.markdown("**Modèle de courrier** (bouton de copie en haut à droite)")
    st.code(courrier, language=None)


# --------------------------------------------------------------------------- page

cfg = config.charger()
if not cfg.get("racine_onedrive"):
    premier_lancement()
    st.stop()

racine = Path(cfg["racine_onedrive"])
demarrer()
conn = db.connecter(config.DB)
db.initialiser(conn)
aujourdhui = date.today()
sits = suivi.situations(conn)

barre_laterale(conn, racine, cfg, aujourdhui)
st.title("📑 Contrathèque")
bandeau_a_traiter(conn, sits, aujourdhui)
tab_ajout, tab_suivi, tab_revision = st.tabs(["➕ Ajouter un contrat", "📊 Suivi", "💶 Révision de prix"])
with tab_ajout:
    onglet_ajout(conn, racine, cfg, sits, aujourdhui)
with tab_suivi:
    onglet_suivi(conn, sits, aujourdhui)
with tab_revision:
    onglet_revision(sits)
