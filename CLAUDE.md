# Bada Bing NBA : notes pour Claude

Site Streamlit (`app.py`, plus `fantasy.py` pour le jeu) en français : les matchs NBA **sans spoil**. Réponses à l'utilisateur en français.
Projet à part du site NFL (`nfl_pronos`) ; utilisé par Kiki (Paris) et un ami à Montréal.

## Ce que fait le site

- Matchs groupés par « jour du match » d'ESPN (heure de New York), titre selon le fuseau : « Nuit du mercredi 21 au jeudi 22 octobre » (Paris)
  ou « Mercredi 21 octobre » (Montréal). Fuseau deviné du navigateur (`st.context.timezone`), sans réglage (v019 : retiré de ⚙️, `?tz=` des anciens liens ignoré).
  Site ouvert à tous, sans compte (choix de Kiki) : réglages gardés par appareil (cookies `nba_fav` équipes, `nba_opt` indice/scores).
  ⚙️ ne montre que les réglages utiles aux visiteurs (plus l'état de la clé YouTube : il est sur la page admin).
  Jour affiché par défaut : la nuit qui vient de se jouer (`default_day`). Nuit choisie gardée dans l'adresse (`?nuit=AAAA-MM-JJ`).
- **Mise à jour automatique** (`auto_refresh`) : Streamlit ne rafraîchit pas une page ouverte, donc la page se recharge quand on revient
  sur l'onglet après plus de 3 min, et toutes les 90 s pendant les matchs (sauf si un panneau est ouvert). Si ESPN ne répond pas,
  `day_games` reprend la dernière liste reçue (`.cache/sb_<jour>.json`) au lieu d'effacer les scores.
- **Tableau des scores (v013, choix de Kiki après comparaison des maquettes, alternative D)** : la nuit s'affiche en LIGNES de match
  (`game_card` → `.mrow`, 2 colonnes sur PC, 1 sur téléphone avec les équipes l'une sous l'autre et l'afficheur à droite) : bandeau
  vertical de rareté à gauche, logo dans une pastille à la couleur de l'équipe avec halo, ville en petit + nom en grand.
  v018 : fond aux couleurs des 2 équipes coupé en diagonale + rayures, assombri (comme le match de la nuit), pied plus sombre ;
  sur téléphone, coupure presque horizontale (visiteurs en haut, domicile en bas). Le centre du score s'appelle `.smid`
  (avant `.sm`, qui entrait en conflit avec la classe `sm` des noms moyens et les cachait sur téléphone).
  **Score (v016, demande de Kiki : « oublie l'afficheur, plus grand, plus intégré »)** : un grand chiffre (Barlow Condensed) à côté
  de chaque équipe (`.sn`), « Final » / « ● En direct » au centre (`.sm`) ; caché = deux cases hachurées « ? » + « 👁 voir le score »,
  un clic sur l'une révèle (`.tg-s`) ; le perdant est grisé (`.sc-real.l`). Avant le match : l'heure en grand au centre. Sur téléphone :
  chaque score à droite de son équipe. Carte de la nuit : score sous les noms (`.cscore`) ; fiche : `.fsc` (révélé d'office).
  Bilan d'avant-match entre parenthèses à côté du nom (`team_record`, « Grizzlies (2-0) »). Puis, sur une ligne, L'INFO CLÉ
  d'avant-match (v017, `key_fact`, une seule, la plus importante, choisie par priorité) : play-offs, star absente (meneur ESPN en
  points/rebonds/passes), retour de blessure (absent au match précédent, mémorisé dans `.cache/outs_<équipe>.json` par `remember_outs` :
  seulement si le site l'a vu absent), star incertaine, invaincus / sans succès, série de 3+, choc au sommet, revanche des play-offs,
  domination ou bilan des face-à-face, fatigue (2e soir), pile ou face / grand favori. Plus de phrase « Duel de l'Ouest… » (jugée inutile).
  Puis résumé vidéo, « Stats › » (ouvre la fiche avec le score).
  En tête : « Le match de la nuit » (v018, ex « carte de la nuit » ; `hero=True`) = le meilleur match (🔥🔥 ou plus) en grande carte façon carte à collectionner
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
- **Navigation (v023-v024, carte blanche de Kiki)** : en-tête = marque seule (v024 : plus de pastille « sans spoil ») + ⚙️ Réglages
  (`key="hdr"`, `settings_panel` : UNE équipe (v024, cookie `nba_fav`), pays 🇫🇷/🇨🇦 (`opts["pays"]`, cookie `nba_opt` « cFR/cCA »,
  par défaut d'après le fuseau), indice, scores). Puis 6 ONGLETS collants (`key="tabs"`, `TABS`, icônes Material ; sur téléphone
  icône au-dessus du mot) : Le brief (`?vue=brief`) · Matchs (`?vue` absent) · Programme · Classement · Équipes (`?vue=equipe&eq=LAL`,
  l'onglet prend le nom de mon équipe) · Joueurs (`?vue=joueurs&joueur=<id>` ou `&rub=meilleurs|nous|infirmerie`).
  Re-cliquer « Matchs » = dernière nuit. Semaine (`?vue=semaine`) : bouton 📈 au bout de la bande des nuits.
  Bande des nuits (`key="nav"`) : ‹ | 7 nuits | › | 📅 | 📈. Chaque nuit sur 2 lignes, jamais coupée (`chip_text`) : petit texte en CSS
  `::before` (« Sam. → Dim. », ou « Nuit dernière » / « Cette nuit ») + grand texte « 31 → 1 » (Paris) ou « 31 oct. » (Montréal) ;
  pastille `::after` (dorée = pas encore vue, rouge = en cours). Sur téléphone la bande défile et se centre sur la nuit affichée
  (`click_tracker`). Vue Semaine : bande `key="navw"` ‹ Semaine N · du … au … ›. Semaines NBA lundi → dimanche (`week_of`).
  Le bouton 🏆 du « 5 de la semaine » est retiré (prototype mis de côté) : le jeu reste joignable par `?vue=fantasy`.
  **Liens internes dans le HTML (v024, `link`, `team_link`, `player_link`)** : `<a href="#go?nuit=…&vue=…&open=<match>">`.
  `target="_top"` ne marchait PAS sur Streamlit Cloud (la page est dans un cadre) : le clic est intercepté par `click_tracker`,
  qui écrit la commande dans le champ caché `go_to` (`key="gobox"`, hors écran) → nouveau passage → `apply_go` (nuit, vue, équipe,
  joueur, rubrique, match à ouvrir : `open` coche `.tg-o`). Pas de rechargement de page. Bandeau de bienvenue à la 1re visite (`welcome`, cookie `nba_hello`). Pied de page (`page_footer`).
- **Pas de spoil dans les chiffres (`spoil_cut`)** : bilans, classement, séries comptent les matchs AVANT la dernière nuit jouée tant
  que l'appareil ne l'a pas ouverte (cookie `nba_vues`) ; interrupteur « Inclure la dernière nuit » ; tout est à jour si elle a été
  ouverte ou avec « Toujours montrer les scores ».
- **Où regarder : RETIRÉ de l'affichage en v027** (demande de Kiki : pas à jour, affichait presque toujours « NBA League Pass »).
  Le code reste (`watch_on`, `watch_badge`, `nba_schedule_tv`) mais n'est plus appelé. Le pays des réglages sert à « nos joueurs »
  et à NBA Extra. Ancienne description (v024) : selon le pays des réglages, beIN SPORTS (FR) ou TSN / Sportsnet / RDS / TVA Sports
  (CA) quand une source le dit (ESPN `broadcasts` + `geoBroadcasts` → `tv_all`, et calendrier officiel `cdn.nba.com` scheduleLeagueV2,
  `nba_schedule_tv`, sigles NBA via `NBA_TRI`), sinon « NBA League Pass ». En doré quand la chaîne est connue. Sources non vérifiées
  depuis l'environnement de test (bloquées) : à surveiller en ligne.
- **Programme (`programme_page`)** : 7 prochaines nuits (scoreboard ESPN), heure locale, bilans (sans spoil), où regarder, « ★ Mon équipe »,
  « 🔥 L'affiche » (`quick_hype` : deux équipes qui gagnent), filtre Tous / Mes équipes, lien « Voir la nuit ›», agenda .ics
  (`ics_calendar`, `agenda_button`, heures de `_team_schedule` → champ `utc`).
- **Classement (`standings_page`, `standings`)** : calculé par le site depuis `team_index` (pas ESPN, pour la coupure sans spoil) :
  V, D, %, écart, dom., ext., 10 derniers, série ; 1-6 vert (play-offs), 7-10 orange (play-in), équipes favorites surlignées.
- **Mon équipe (`team_page`)** : sans équipe = grille des 30 (`team_picker`). Bandeau aux couleurs, 7 tuiles (bilan + rang, série,
  10 derniers, dom., ext., attaque/défense + rang NBA), « Suivre » / autre équipe, prochain match (heure, dom./ext., 2e soir, TV),
  infirmerie et meneurs de la saison (résumé ESPN d'avant-match), 10 prochains matchs + agenda, 10 derniers matchs (résultats cachés,
  `.tg-r`), effectif (`team_roster`, photos ESPN, noms cliquables vers la fiche), actus ESPN repliées (`team_news`, en anglais, peuvent spoiler).
  Une autre équipe s'ouvre par la liste « Autre équipe » ou un clic sur son nom (programme, classement…) ; bouton « Revenir aux … ».
- **Le brief = PAGE D'ACCUEIL (v025, `brief_page`, `BRIEF_CSS`, « la page la plus importante » pour Kiki)** : adresse sans `vue`
  ni `nuit` = le brief (un ancien lien `?nuit=` seul ouvre la nuit). Tout dans UN seul bloc HTML (les cases à cocher CSS ne voient
  que leurs voisins) : titre de la nuit + pastille « 👁 Tout révéler » (`#b-all`, `.tg-all`, discrète), bandeau de mon équipe
  (prochain match + chaîne), TOUS les matchs de la nuit en tuiles de MÊME taille (`.bt-grid`, `grid-auto-rows:1fr`, une ligne par
  équipe avec bilan d'avant-match, cases « ? » cliquables par match `.tg-t`, indice « à voir », info clé `key_fact` sur une ligne,
  Résumé / NBA Extra / Stats ›), triées mon équipe puis indice. Rubriques cachées, chacune avec sa pastille « 👁 Voir » (`.tg-x`) :
  « 📝 La nuit en bref » (pleine largeur), grosses perfs, ce qui a bougé au classement, nos Français/Canadiens. En haut à droite :
  « ▶ Résumé de la nuit » et « NBA Extra » (ou « bientôt ») (`night_videos`). Puis grosses absences (avec la blessure et le
  retour prévu) et la nuit prochaine. TOUT est caché
  par défaut (sauf « Toujours montrer les scores », classe `.bf.all`).
  ⚠️ Ne jamais écrire `checked` dans le HTML d'une case à cocher : React la verrouille (impossible de la décocher : bug « Cacher »
  du brief v024). Pour un état ouvert par défaut, utiliser une classe CSS sur le bloc.
- **Réglages qui tiennent (v026)** : SUR STREAMLIT CLOUD, LE SERVEUR NE REÇOIT PAS LES COOKIES ÉCRITS PAR LA PAGE (d'où l'équipe
  favorite qui sautait et les « 5 visiteurs » qui étaient Kiki). Donc : `set_cookie` écrit le cookie + une copie `localStorage`
  (`KEEP` : équipe, réglages, bienvenue, n° d'appareil, nuits vues, admin) ; au chargement, `click_tracker` relit tout dans le
  navigateur et, si le serveur ne l'a pas, l'envoie par le champ caché (`restore=1&fav=…&opt=…&id=…&vues=…&ev=…&hb=…`) →
  `apply_restore` (une fois par visite, `ss.restored`). Le n° d'appareil n'est écrit que s'il n'existe pas (`only_if_missing`).
  Tester ce cas en local : `BB_SANS_COOKIES=1` (le serveur ignore les cookies, comme sur Streamlit Cloud).
- Bouton « Révéler le récap de la nuit » de la page Matchs : pastille sobre (v025, plus de grande barre dorée animée).
- **La nuit en bref (v026-v027, `night_story`, `story_html`)** : v027 = liste de faits avec icône (🎬 ⚖️ ⭐ 😮 🔄 💥 📈 📊, jusqu'à 5,
  dont le classement dans le brief via `moves`) ; à côté, « 🏆 Le MVP de la nuit » (meilleur `game_score` : photo, équipe,
  adversaire, 9 cases de stats), puis les grosses perfs (2e à 7e). Avant v027 : 2 à 4 phrases (match de la nuit selon l'indice, sinon le plus serré ;
  la perf ; la surprise (favori de 5 pts ou plus battu) ou la remontée de 15 pts ou plus ou la raclée ; une série de 5+), accordées
  (« le Magic bat », « les Celtics battent » : `SINGULIER`, `les`, `vb`). Réécrites en paragraphe par Claude si `[anthropic]`
  (`ai_night`, gardé dans `.cache/ai_night_<jour>.json`, une fois la nuit finie). Remplace les tuiles surprise / plus serré /
  correction / remontée / séries (jugées peu utiles par Kiki) dans le récap de la page Matchs ; restent la nuit en bref + les résultats.
- **Blessures détaillées (v026)** : `league_injuries` garde aussi détail, côté, date, `longComment` ; `injury_fr` (« Entorse · genou
  gauche », `DETAIL_FR`, `FEMININ`), `injury_box` sur la fiche joueur : blessure, signalée le, dernier match + matchs manqués
  (`missed_games`, journal des joueurs), retour prévu, « le point d'ESPN » traduit par Claude si `[anthropic]` (`ai_translate`), sinon en anglais.
- **Choix de l'équipe (v026, `team_picker`)** : 30 tuiles avec logo, ville et nom, aux couleurs de l'équipe (liens `link`).
- **Joueurs (v024, `players_page`, `PLAYERS_CSS`)** : rubriques Fiches · Les meilleurs · Les Français (ou Canadiens selon le pays) ·
  Infirmerie. Journal de toutes les feuilles de match de la saison (`players_db`, fil de fond « joueurs » toutes les 15 min,
  `_players_tick` lit le scoreboard jour par jour puis `summary_raw`, `_box_line`) gardé sur GitHub `joueurs/log.json` (branche data,
  secrets `[github]`), sinon disque. `season_table` (moyennes avant la coupure sans spoil, mémorisées par version), `player_games`.
  Fiche (`player_page`) : photo, équipe, bio (âge, taille, poids, lieu de naissance, saison, université : `team_roster`), blessure,
  8 tuiles + rang NBA, courbe des points match après match, prochain match, « En feu / En petite forme », 10 derniers matchs (▶ ouvre
  la feuille du match). Meilleurs (`leaders_html`). Nos joueurs : `league_players` (30 effectifs) par pays de naissance.
  Infirmerie (`injuries_section`, `league_injuries` : ESPN `/injuries`, sinon les effectifs) : grosses absences (≥ 16 pts), par équipe.
- **Semaine (v024)** : chaque match conseillé a « ▶ Résumé » et « Stats › » (`ctx["wv"]`) ; sans indice, la liste des matchs joués.
  Classes CSS des pages dans `PAGES_CSS` (attention aux noms déjà pris dans `CSS` : `.box` = box score, `.tm` = cartes).
- **Le récap de la nuit (`night_html`, `.nrec`, v018 : « plus d'impact », demande de Kiki)** : grand bloc en tête (lueur dorée, rayures
  comme les cartes) : « Le récap de la nuit », titre « Nuit du dim. 25 au lun. 26 oct. », pastille d'état neutre (✓ Terminée, ● En cours
  rouge, À venir doré ; plus de texte vert) + nombre de matchs ; boutons vidéo larges (résumé de la nuit doré, NBA Extra aux couleurs de la
  France). Grande barre dorée animée « 👁 Révéler le récap de la nuit » (`.nr-rev`, `.tg-n`) → tuiles (une par fait de `night_essentials` :
  perfs, surprise, serré/prolongations, remontée, correction, séries) + « Les résultats » en mini-tableaux de score avec logos.
- **Nuits vues** : cookie `nba_vues` (AAMMJJ) ; une nuit commencée qu'on ouvre devient « vue ». Pastille dorée sur le bouton = nuit
  terminée pas encore ouverte ; rouge = en cours (CSS `.st-key-n_<date> button::after`). Pas de pastille = vue ou à venir.
- **Vue Semaine (`week_html`)** : meilleurs matchs de la semaine (sans spoil) ; bilan caché (`.tg-w`) : perfs, notre joueur de la semaine
  (calcul maison, moyenne du « game score » sur 2 matchs ou plus), équipe de la semaine, surprise, match le plus fou.
  Indice « à voir » sans dire qui gagne (`watch_score`, `interest_parts`) : 6 niveaux (🔥🔥🔥 Immanquable, 🔥🔥, 🔥, 😐 Sans plus, 💤, ⛔ À fuir),
  note globale mêlant beaucoup d'ingrédients qui se compensent (fin serrée, prolongation, retournements, leaders, équilibre, panier décisif,
  perf individuelle, spectacle, enjeu, pénalité « plié tôt ») : voulu FLOU, pour qu'une note ne trahisse pas le scénario (demande de Kiki).
  Avant le score : seulement icône + nom + conseil ; les raisons s'affichent dans le panneau du score. Range les matchs terminés ;
  « L'affiche de la nuit » pour les matchs à venir (`hype`). Équipes favorites (cookie `nba_fav`) en tête. Durées des vidéos via l'API YouTube.
- **No spoil** : score caché par défaut (rien n'est retenu d'une visite à l'autre), ou ⚙️ « Toujours montrer les scores » (cookie `nba_opt`). Tant que c'est caché : pas de score, pas de « prolongation », bilans et séries calculés
  AVANT le match (`team_form`, `head_to_head` sur `team_index`), jamais ceux d'ESPN (qui incluent le résultat).
- Vidéos : résumé du match = **GAMETIME HIGHLIGHTS d'abord** (choix de Kiki v014, chaîne `GT_CHANNEL` UC0LrZO9wORIqn_aRJtKdgfA,
  « Utah Jazz vs New Orleans Pelicans Full Game Highlights - October 23, 2026 | NBA Season », marquées `gt`, recherche dédiée si absent),
  sinon résumé officiel NBA (« KINGS at CLIPPERS | FULL GAME HIGHLIGHTS | October 21, 2026 », `nba_video`), résumé de NBA Extra
  (beIN SPORTS, « Résumé : WARRIORS @ LAKERS, … », `extra_video`), journal NBA Extra (« REPLAY - NBA Extra (21/10) », `journals`, 12h45 à Paris),
  résumé de la nuit NBA (`nightly_recap`). Boutons sans le titre des vidéos (les titres de NBA Extra peuvent spoiler).
  Sources, dans l'ordre : veille (`video_watcher`, fil d'exécution qui relit les 3 chaînes toutes les 10 min même sans visiteur et garde
  10 jours de vidéos dans `.cache/seen.json`), flux public (15 dernières), API YouTube avec `[youtube] api_key` (seule source complète :
  la NBA publie plus de 15 vidéos par nuit), puis recherche YouTube sans clé (`yt_search`, peu fiable, filet de sécurité) ; vidéos trouvées
  gardées dans `.cache/videos.json`. État de la clé affiché sur la page admin (`API_STATUS`).
  **Vidéos bloquées** (v012) : les résumés NBA sont souvent bloqués en France (« bloquée dans votre pays »). `video_info` lit
  `regionRestriction` via l'API YouTube (clé nécessaire) ; pays = FR (Paris) ou CA (Montréal). Résumé NBA bloqué → `alt_video`
  cherche un autre résumé du même match sur une autre chaîne et ne garde que ceux qui passent dans le pays ; sinon bouton
  « 🔎 Chercher un résumé ». NBA Extra / résumé de la nuit bloqués : masqués. Sans clé YouTube : impossible de savoir.
- Avant-match écrit (`preview_points`) : contexte, forme, face-à-face, absents (ESPN), favori (cote figée). Blessés et cotes d'avant-match gardés
  dans `.cache/pre_<id>.json` (perdus à un redémarrage de Streamlit Cloud : pas grave, la preview d'un match passé s'en passe).
- « 📊 Forme & duels » (`form_html`, `tale`) : comparatif ligne à ligne avant le match (bilan, ext./dom., points pour/contre, série, repos,
  5 derniers en pastilles), puis face-à-face. Stats des joueurs : un clic sur un joueur ouvre sa carte de tirs (`shot_modal`, `court_svg` :
  tirs ESPN, panier en (25, 0) en pieds ; v018 : 10 zones calées sur les lignes du terrain (cercle 8 pieds, raquette, mi-distance gauche/
  centre/droite séparées par le prolongement des côtés de la raquette, 3 pts : 2 coins, 2 ailes, axe) ; seuls traits ajoutés : 2 pointillés).
  v016 : carte du joueur refaite (en-tête aux couleurs de l'équipe + photo, 4 grosses stats, terrain parquet clair, zones colorées
  seulement à partir de 3 tirs : rouge au-dessus / bleu en dessous / ocre dans la moyenne NBA, % + réussis/tentés, chaque tir ● / ✕
  pour voir de quel côté il tire, barres « près du cercle / raquette / mi-distance / 3 points » contre la moyenne NBA).
- Après le score : analyse (`recap_points` : vainqueur, remontée/prolongation, grosse perf au « game score », bilans, blessures citées par l'AP),
  feuille de match (quart-temps, box score, écart au fil du match, paniers par quart-temps).
- Facultatif : avec `[anthropic] api_key` (et `model`, par défaut `claude-opus-5-5`), Claude réécrit preview et analyse en français
  à partir de l'article AP (`ai_points`, gardé dans `.cache/ai_*.json`). Jamais de preview IA écrite après le coup d'envoi.

- **Le 5 de la semaine (v015, la fantasy, `fantasy.py` + `fantasy_page` dans app.py, PROTOTYPE MIS DE CÔTÉ en v023 : plus de bouton, seulement `?vue=fantasy`)** :
  règles décidées avec Kiki : une équipe par semaine NBA (lundi → dimanche), verrouillée au 1er match de la semaine ; 2 arrières,
  2 ailiers, 1 pivot + 6e homme (tout poste) ; budget 100 000 € ; chaque joueur rapporte sa MOYENNE de points fantasy par match joué
  (toute apparition compte) ; le 6e homme remplace un des 5 qui n'a joué aucun match ; « coup de cœur » 💘 = un des 5 à 10 000 € ou
  moins, points ×2 ; pas de capitaine. Points : 1/pt, 1,2/rebond, 1,5/passe, 3/interception, 3/contre, −1/balle perdue.
  Prix calculés par le site (`week_prices`) : forme = 70 % des 10 derniers matchs + 30 % de la saison, tirée vers 12 tant qu'il y a
  peu de matchs ; prix = 5 000 + 92,5 × forme^1,5 (≈ 48 000 € pour 60 pts/m), entre 4 000 et 50 000 €, ±20 % max par semaine ;
  figés pour la semaine (`ensure_week`). Équipe robot 🤖 (`robot_team`), équipe parfaite (`perfect_team`, % du maximum).
  Points et classements cachés derrière des interrupteurs (spoil). Journal des matchs (`log.json`) et équipes (`data.json`) enregistrés
  sur GitHub dans `fantasy/` (branche `data`, pour ne pas redémarrer le site) via `[github] token, repo, branch` ; sinon sur le disque
  (perdu au redémarrage). Connexion : pseudo + code (empreinte SHA-256 seulement), cookie `nba_fx`. Effectifs et postes : ESPN `teams/<id>/roster`.

- **Statistiques de visite et page admin (v020, `stats.py`, `admin_page`)** : page cachée, sans bouton, ouverte par le lien secret
  `?admin=<code>` (`[admin] code` dans les secrets ; sans code, pas de page admin). Anonyme : numéro d'appareil au hasard (cookie
  `nba_id`), pas d'IP. Côté serveur : arrivée (`open`, fuseau, appareil), changement de nuit/vue (`nav`), réglages (`set`), erreurs
  (`err` : ESPN/YouTube qui ne répondent pas, plantages). Clics dans la page notés par `click_tracker` dans le cookie `nba_ev`
  (résumé vidéo `v`, NBA Extra `x`/`X`, résumé de la nuit `R`, stats `s`, récap révélé `n`, score `r`, carte de tirs `p`…) et durée
  dans `nba_hb` : relus au chargement suivant (Streamlit ne lit les cookies qu'à l'ouverture). Tampon envoyé toutes les 5 min sur
  GitHub (`stats/AAAA-MM.json`, branche `data`, mêmes secrets `[github]` que le jeu), sinon disque. Les appareils qui ont ouvert la
  page admin sont marqués (cookie `nba_me` + liste `_moi` dans `stats/names.json`) et exclus des chiffres par défaut.
  v022 : `nba_id` écrit dès le début de la page et « arrivée » comptée seulement en fin de page (avant : chaque chargement
  interrompu créait un faux visiteur). Noms donnés aux visiteurs : `stats/names.json` ; même nom = une seule personne.

## Données

- ESPN (sans clé) : `scoreboard?dates=AAAAMMJJ`, `summary?event=`, `teams/<id>/schedule?season=&seasontype=` (la plage de dates
  ne marche pas sur le scoreboard NBA : saison lue équipe par équipe, `season_games`).
- `data/nba_history.json` : saisons 2016 → saison passée (~14 000 matchs), à régénérer une fois par an avant la saison :
  `python data/build_nba_history.py`.

## Tester en local

- `python tests/test_sans_spoil.py` : vérifie qu'une carte au score caché ne trahit rien (score, « prolongation », « remontée »…). À lancer avant chaque envoi.
- `python tests/scenarios.py` : note d'intérêt de matchs inventés, pour régler les seuils.
- `python tests/page_complete.py` : exécute toutes les vues (Nuit, Semaine, Programme, Classement, Mon équipe) avec un faux Streamlit.
- **Voir le site sans ESPN** : `BB_FAUX_ESPN=1 python -m streamlit run app.py --server.port 8531` (saison inventée, `tests/faux_espn.py`).
- `python tests/test_stats.py` : statistiques de visite (cookies, visites, activité par nuit).
- `python tests/test_fantasy.py` : règles du « 5 de la semaine » ; `python tests/page_fantasy.py` : la page du jeu avec une saison inventée.


`python -m streamlit run app.py --server.port 8531`, puis vérifier à l'écran (PC et téléphone). Incrémenter `APP_VERSION` à chaque changement.

Scripts invisibles (cookies, rechargement, clics) : `run_js` → `st.iframe` (Streamlit récent) sinon `components.html` (retiré bientôt).
Le code doit rester lisible par Python 3.11 (pas de f-strings imbriquées avec les mêmes guillemets) : `python3.11 -c "import ast; ast.parse(open('app.py').read())"`.

**Règle d'affichage (v027, demande de Kiki)** : une info courte = UNE ligne. Heures, noms de joueurs et d'équipes, dates, pastilles :
`white-space:nowrap` (+ `text-overflow:ellipsis` si la place manque), jamais coupés au milieu (« 21h3 / 0 », « Wembanyam / a »).
Dans les listes de joueurs, la ligne de stats va SOUS le nom (`.bs .sl`), pas à côté. Les enfants de grilles ont `min-width:0`.
