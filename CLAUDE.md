# Bada Bing NBA : notes pour Claude

Site Streamlit (`app.py`, un seul fichier) en français : les matchs NBA **sans spoil**. Réponses à l'utilisateur en français.
Projet à part du site NFL (`nfl_pronos`) ; utilisé par Kiki (Paris) et un ami à Montréal.

## Ce que fait le site

- Matchs groupés par « jour du match » d'ESPN (heure de New York), titre selon le fuseau : « Nuit du mercredi 21 au jeudi 22 octobre » (Paris)
  ou « Mercredi 21 octobre » (Montréal). Fuseau deviné du navigateur (`st.context.timezone`), modifiable dans ⚙️ (gardé dans l'adresse : `?tz=`).
  Jour affiché par défaut : la nuit qui vient de se jouer (`default_day`). Nuit choisie gardée dans l'adresse (`?nuit=AAAA-MM-JJ`).
- **Mise à jour automatique** (`auto_refresh`) : Streamlit ne rafraîchit pas une page ouverte, donc la page se recharge quand on revient
  sur l'onglet après plus de 3 min, et toutes les 90 s pendant les matchs (sauf si un panneau est ouvert). Si ESPN ne répond pas,
  `day_games` reprend la dernière liste reçue (`.cache/sb_<jour>.json`) au lieu d'effacer les scores.
- **Tableau des scores (v013, choix de Kiki après comparaison des maquettes, alternative D)** : la nuit s'affiche en LIGNES de match
  (`game_card` → `.mrow`, 2 colonnes sur PC, 1 sur téléphone avec les équipes l'une sous l'autre et l'afficheur à droite) : bandeau
  vertical de rareté à gauche, logo dans une pastille à la couleur de l'équipe avec halo, ville en petit + nom en grand, afficheur
  « play clock » au centre (clic = score), avant-match sur une ligne, résumé vidéo, « Stats › » (ouvre la fiche avec le score).
  En tête : « La carte de la nuit » (`hero=True`) = le meilleur match (🔥🔥 ou plus) en grande carte façon carte à collectionner
  (style « Holo » ci-dessous) ; avant les matchs : « L'affiche de la nuit ». Ce match n'est pas répété dans les lignes.
- **Style « Holo » (v011, gardé pour la carte de la nuit et l'en-tête de la fiche)** : carte à collectionner (`face_head`).
  Face : grands logos en diagonale sur les couleurs des 2 équipes (le point fort, ne pas les recouvrir), noms en entier sur une ligne,
  afficheur façon « play clock » NBA entre les noms (`.clock`, police Orbitron ambre) : heure avant le match, « ? – ? » ensuite, un clic
  le révèle (`.tg-s`). Pas de bilans sur la face (jugé moche), pas de titre de conseil (doublon avec l'étiquette en haut). Bas : avant-match
  (3 lignes, sans spoil), bouton résumé vidéo, lien « Stats et détails › ». Heure en haut à droite (appréciée).
  Cadre de même largeur pour tous, rareté selon la note (`RARITY`, choix de Kiki v012) : ⛔ gris très foncé, 💤 gris moyen mat,
  😐 ardoise, 🔥 cuivre, 🔥🔥 argent à reflet animé, 🔥🔥🔥 or légendaire à reflet animé ; affiche = doré, direct = rouge.
  Deux équipes de couleurs proches (deux rouges…) : `card_colors` prend la 2e couleur d'une équipe, sinon assombrit les visiteurs.
  Noms longs en plus petit (`name_cls`) pour tenir en entier.
  Fiche (`.tg-o`) : pour un match joué, l'ouvrir = vouloir le score → score (afficheur « Final ») et stats directement ; avant un match :
  avant-match + forme. Polices Barlow / Barlow Condensed / Orbitron. Mise en page `wide`, 1240 px max.
- **En-tête (`main`)** : marque seule (pas de sous-titre), 📅 (dernière nuit / date) et ⚙️ en icônes (`key="hdr"`). Bandeau sur UNE ligne
  (`key="nav"`, défile au doigt) : ‹ | « Semaine N » (vue Semaine, `?vue=semaine`) | 7 nuits courtes « Jeu. 22 → 23 » (`night_label`,
  doivent tenir en entier) | ›. Semaines NBA lundi → dimanche (`season_opening`, `week_of`). État de la nuit en infobulle.
- **Barre de la nuit (`night_html`)** : fine, sur une ligne : « Nuit du dim. 25 au lun. 26 oct. » + état ; à droite NBA Extra, résumé de la
  nuit, « 👁 Infos de la nuit » (`.tg-n`, faits de `night_essentials` : perfs, surprise, serré/prolongations, remontée, correction, séries,
  résultats). Plus de comptage par niveau ni « À voir en priorité » (jugés inutiles : le tri par flammes suffit).
- **Nuits vues** : cookie `nba_vues` (AAMMJJ) ; une nuit commencée qu'on ouvre devient « vue ». Pastille dorée sur le bouton = nuit
  terminée pas encore ouverte ; rouge = en cours (CSS `.st-key-n_<date> button::after`). Pas de pastille = vue ou à venir.
- **Vue Semaine (`week_html`)** : meilleurs matchs de la semaine (sans spoil) ; bilan caché (`.tg-w`) : perfs, notre joueur de la semaine
  (calcul maison, moyenne du « game score » sur 2 matchs ou plus), équipe de la semaine, surprise, match le plus fou.
  Indice « à voir » sans dire qui gagne (`watch_score`, `interest_parts`) : 6 niveaux (🔥🔥🔥 Immanquable, 🔥🔥, 🔥, 😐 Sans plus, 💤, ⛔ À fuir),
  note globale mêlant beaucoup d'ingrédients qui se compensent (fin serrée, prolongation, retournements, leaders, équilibre, panier décisif,
  perf individuelle, spectacle, enjeu, pénalité « plié tôt ») : voulu FLOU, pour qu'une note ne trahisse pas le scénario (demande de Kiki).
  Avant le score : seulement icône + nom + conseil ; les raisons s'affichent dans le panneau du score. Range les matchs terminés ;
  « L'affiche de la nuit » pour les matchs à venir (`hype`). Équipes favorites (cookie `nba_fav`) en tête. Durées des vidéos via l'API YouTube.
- **No spoil** : score caché par défaut (rien n'est retenu d'une visite à l'autre), ou ⚙️ « Toujours montrer les scores » (`?scores=1`). Tant que c'est caché : pas de score, pas de « prolongation », bilans et séries calculés
  AVANT le match (`team_form`, `head_to_head` sur `team_index`), jamais ceux d'ESPN (qui incluent le résultat).
- Vidéos : résumé du match = **GAMETIME HIGHLIGHTS d'abord** (choix de Kiki v014, chaîne `GT_CHANNEL` UC0LrZO9wORIqn_aRJtKdgfA,
  « Utah Jazz vs New Orleans Pelicans Full Game Highlights - October 23, 2026 | NBA Season », marquées `gt`, recherche dédiée si absent),
  sinon résumé officiel NBA (« KINGS at CLIPPERS | FULL GAME HIGHLIGHTS | October 21, 2026 », `nba_video`), résumé de NBA Extra
  (beIN SPORTS, « Résumé : WARRIORS @ LAKERS, … », `extra_video`), journal NBA Extra (« REPLAY - NBA Extra (21/10) », `journals`, 12h45 à Paris),
  résumé de la nuit NBA (`nightly_recap`). Boutons sans le titre des vidéos (les titres de NBA Extra peuvent spoiler).
  Sources, dans l'ordre : veille (`video_watcher`, fil d'exécution qui relit les 3 chaînes toutes les 10 min même sans visiteur et garde
  10 jours de vidéos dans `.cache/seen.json`), flux public (15 dernières), API YouTube avec `[youtube] api_key` (seule source complète :
  la NBA publie plus de 15 vidéos par nuit), puis recherche YouTube sans clé (`yt_search`, peu fiable, filet de sécurité) ; vidéos trouvées
  gardées dans `.cache/videos.json`. État de la clé affiché dans ⚙️ Réglages (`API_STATUS`).
  **Vidéos bloquées** (v012) : les résumés NBA sont souvent bloqués en France (« bloquée dans votre pays »). `video_info` lit
  `regionRestriction` via l'API YouTube (clé nécessaire) ; pays = FR (Paris) ou CA (Montréal). Résumé NBA bloqué → `alt_video`
  cherche un autre résumé du même match sur une autre chaîne et ne garde que ceux qui passent dans le pays ; sinon bouton
  « 🔎 Chercher un résumé ». NBA Extra / résumé de la nuit bloqués : masqués. Sans clé YouTube : impossible de savoir.
- Avant-match écrit (`preview_points`) : contexte, forme, face-à-face, absents (ESPN), favori (cote figée). Blessés et cotes d'avant-match gardés
  dans `.cache/pre_<id>.json` (perdus à un redémarrage de Streamlit Cloud : pas grave, la preview d'un match passé s'en passe).
- « 📊 Forme & duels » (`form_html`, `tale`) : comparatif ligne à ligne avant le match (bilan, ext./dom., points pour/contre, série, repos,
  5 derniers en pastilles), puis face-à-face. Stats des joueurs : un clic sur un joueur ouvre sa carte de tirs (`shot_modal`, `court_svg` :
  tirs ESPN, panier en (25, 0) en pieds ; 14 zones comme les « hot zones » NBA : cercle, raquette en 3, mi-distance en 5, 3 pts en 5 ; rouge/jaune/bleu selon la moyenne NBA de la zone, « réussis/tentés » affiché). Pas de « tous les paniers » (inutile, retiré).
- Après le score : analyse (`recap_points` : vainqueur, remontée/prolongation, grosse perf au « game score », bilans, blessures citées par l'AP),
  feuille de match (quart-temps, box score, écart au fil du match, paniers par quart-temps).
- Facultatif : avec `[anthropic] api_key` (et `model`, par défaut `claude-opus-5-5`), Claude réécrit preview et analyse en français
  à partir de l'article AP (`ai_points`, gardé dans `.cache/ai_*.json`). Jamais de preview IA écrite après le coup d'envoi.

## Données

- ESPN (sans clé) : `scoreboard?dates=AAAAMMJJ`, `summary?event=`, `teams/<id>/schedule?season=&seasontype=` (la plage de dates
  ne marche pas sur le scoreboard NBA : saison lue équipe par équipe, `season_games`).
- `data/nba_history.json` : saisons 2016 → saison passée (~14 000 matchs), à régénérer une fois par an avant la saison :
  `python data/build_nba_history.py`.

## Tester en local

- `python tests/test_sans_spoil.py` : vérifie qu'une carte au score caché ne trahit rien (score, « prolongation », « remontée »…). À lancer avant chaque envoi.
- `python tests/scenarios.py` : note d'intérêt de matchs inventés, pour régler les seuils.
- `python tests/page_complete.py` : exécute toute la page (Nuit et Semaine) avec un faux Streamlit, pour attraper les erreurs.


`python -m streamlit run app.py --server.port 8531`, puis vérifier à l'écran (PC et téléphone). Incrémenter `APP_VERSION` à chaque changement.
