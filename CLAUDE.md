# Bada Bing NBA : notes pour Claude

Site Streamlit (`app.py`, plus `fantasy.py` pour le jeu) en français : les matchs NBA **sans spoil**. Réponses à l'utilisateur en français.
Projet à part du site NFL (`nfl_pronos`) ; utilisé par Kiki (Paris) et un ami à Montréal.

## ⚡ SITE v2 « NOCTURNE » EN CONSTRUCTION (`docs/`, 2026-11-13)

Grande refonte décidée avec Kiki : **le site quitte Streamlit** et s'appelle désormais **Nocturne** (nom validé par Kiki).
La v2 est un site statique dans `docs/` (`index.html`, `style.css`, `app.js`, `demo.js`), servi par **GitHub Pages**
(Pages suit la branche de travail `claude/...` + `/docs` : chaque push y est en ligne ~1 min après ; `main` porte les robots).
**DA « broadcast de minuit » (17/11, après le retour Kiki « encore trop Streamlit, pas d'effet waouh, boutons arrondis d'appli IA,
liseré de côté ») — à respecter dans toute nouvelle page** : l'habillage d'une retransmission NBA vue de nuit.
- Logo : croissant de lune-ballon (`<symbol id="moonball">` dans index.html, réutilisé par `<use>`), qui remplace le O du mot-symbole
  N☾CTURNE ; même dessin en favicon. Coutures redessinées le 20/11 (demande de Kiki : « on ne voyait pas que c'est un ballon ») :
  les 4 coutures d'un vrai ballon (une qui descend, une qui traverse, deux arcs en C), inclinées de -30°. Ciel étoilé en fond (`.stars`).
- Navigation : barre du haut (mot-symbole, LE BRIEF · PROGRAMME · CLASSEMENT soulignés ambre, roue) ; barre d'onglets en bas sur téléphone.
- Plaques biseautées (`clip-path` aux coins coupés), JAMAIS de coins arrondis ni de liseré latéral ; boutons `.btn` en parallélogramme
  (`.amber` = action principale, `.extra` = NBA Extra au liseré tricolore) ; étiquettes `.tag`.
- Scores dans des **afficheurs LED ambre** (`.led`, police Doto) : caché = « ?? » ambre éteint, un clic l'allume (`.led.hid` → révélé).
  Plus AUCUN retournement 3D (cause du « ? » fantôme sous Firefox).
- Tuiles = plaques de score TV (`cardHTML` → `.bug`) : une rangée par équipe (pastille biseautée à la couleur de l'équipe avec logo,
  nom en capitales, LED), en-tête horloge + **jauge de chaleur** 5 barres (`heatHTML`) + mot de rareté (`RARL`). Rareté = lumière
  de plaque (`.r0`…`.r5` : or animé, argent, cuivre…) et lueur au sol ; direct = rouge. 3 par ligne sur PC.
- **En-tête sur UNE ligne (20/11, carte blanche de Kiki)** : `skyHTML` (`.sky.one`) = [nuit d'avant · nuit affichée (en grand, avec
  le contexte « Retour sur la nuit »… en petite étiquette ambre au-dessus) · nuit d'après] [calendrier] … [Révéler la nuit, Résumé de
  la nuit, journal NBA Extra]. `renderChips` ne montre plus que ces 3 nuits (libellés « Nuit dernière », « Cette nuit », « Demain »
  si c'est le cas) ; plus de flèches ‹ › ni de grande date « 18 → 19 » à part. Compteurs supprimés. Match de la nuit EN GRAND dessous.
  Sur PC : calendrier et boutons CENTRÉS sur les chiffres de la nuit affichée (ligne calée en bas, marge 9 px), et les 3 boutons
  s'élargissent pour remplir la place (`flex:1`, plus de trou au milieu) ; resserré entre 900 et 1400 px de large (validé par Kiki).
  Le calendrier est la 1re case de la frise (`.calchip`, « Autre nuit » + icône sur la ligne des dates, trait de séparation) ;
  journal NBA Extra = bouton ▶ simple (plus de drapeau). Le contexte (« Retour sur la nuit »…) n'apparaît que si l'étiquette n'est
  pas déjà « Nuit dernière » / « Cette nuit » / « Demain ». **Afficheur de droite (`.board`, 21/11)** selon le moment : avant
  les matchs, compte à rebours LED « Coup d'envoi dans 03:55:58 » + « 9 matchs cette nuit · premier à 02h00 » (`cdText`,
  `startCountdown`, une seule horloge, « 1 j 03 h » au-delà d'un jour) ; pendant, « ● 3 en direct » rouge + terminés / à venir
  (+ les boutons) ; après, seulement les boutons. Centré sur la ligne des dates. « L'essentiel de la nuit » : « de la nuit » en ambre (`--amber`, plus le
  jaune pâle `--moon`), bouton juste à côté du titre ; plus d'étiquette « MVP de la nuit » au-dessus du nom (MVP déjà dit 2 fois). **Une seule ligne d'alignement pour la page** : le cadre de
  « L'essentiel » (`.stage`) déborde de 20 px (12 sur téléphone) et son contenu n'a plus de marge latérale ; cartes des faits
  à 14 px de marge intérieure comme les tuiles des matchs.
- Le brief (`skyHTML`) : salutation selon l'heure + contexte, grande date « 16 → 17 », compteurs LED animés (matchs, à voir, en direct),
  « 🎬 Révéler la nuit » = cérémonie qui défile et révèle du moins bon au meilleur (1,3 s d'écart, le match de la nuit en dernier),
  bande des nuits ; « Le match de la nuit » = **jumbotron** (`heroHTML`) coupé en diagonale aux 2 couleurs, grands logos, projecteurs
  animés, LED géantes ; MVP « sous les projecteurs » (`loadMVP`, carte photo + stats LED qui comptent) ; la nuit prochaine.
- Révéler = course des 2 LED quart-temps par quart-temps (`reveal`, « Fin Q1 »…), puis le vainqueur reste allumé, le perdant s'éteint,
  la rangée du vainqueur flashe à sa couleur, étincelles pour 🔥🔥 et plus.
- **Programme = grille télé (21/11, demande de Kiki)** : une colonne par nuit (titre « Nuit du jeudi 19 / au vendredi 20 / novembre », clic = ouvre la nuit), les matchs groupés sous leur heure de début (LED en **bandeau sur toute la largeur de la colonne**, fuseau de l'appareil, `tzName`) ; **un match = UNE ligne** (retour Kiki : logo + sigle 3 lettres « CHA @ ATL », nom complet et bilans au survol, ★ mon équipe / ◆ l'affiche = `afficheOf` (21/11, durcie à la demande de Kiki : rang en conférence via `loadRanks`/`RANKS`, choc au sommet, duel direct, superstars ≥ 27 pts/m, séries de 4+ victoires, rivalités `RIVAL`, bilans pondérés en début de saison) : note ≥ 3,5 et 2 par nuit au plus (`markAffiches`), raisons au survol, en coin + légende ; sigle JAMAIS coupé : la tuile `.tvg` est un conteneur, `@container` resserre logo et police sous 200 / 160 px, testé avec les 30 sigles de 320 à 1400 px) ; 7 colonnes, 6 sous 1240 px, 5 sous 1080 px ; téléphone : nuits l'une sous l'autre, bandeau de l'heure puis les matchs deux par ligne. Plus de gros titre « Programme » (déjà dans le menu). Deux-points des LED : `ledColon` (`.cl` remonté de 0,1 em : le « : » de Doto commence un pixel trop bas), texte toujours dans un `.v` (le `.led` est une grille).
- Ancien programme en face-à-face (heure en LED), classement en plaques (rang biseauté vert 1-6 / orange 7-10), fiche et carte de tirs en LED
  (onde sur chaque panier). Jeton `state.tok` : une page en chargement ne s'affiche que si c'est encore la dernière demandée.
**Classement** (`renderStandings`, ESPN `apis/v2/.../standings`) : par conférence, coupure sans spoil = résultats de la
dernière nuit soustraits tant que l'interrupteur « Inclure la dernière nuit » est éteint (défaut : coupé sauf « toujours montrer »).
- Le **navigateur appelle ESPN directement** (`site.api.espn.com`, scoreboard + summary) : scores en direct qui se mettent
  à jour seuls (60 s pendant les matchs, retour d'onglet après 3 min), plus de site endormi, plus de robot de réveil.
  Copie de secours des scores dans `localStorage` si ESPN ne répond pas. ⚠️ CORS à confirmer en ligne (ESPN est bloqué
  depuis l'environnement de test : jamais vérifié en vrai).
- **DA « Nuit Holo »** (validée par Kiki, SANS l'inclinaison 3D au survol, jugée gadget) : thème nuit unique, révélation du
  score = carte qui se retourne + particules or/argent selon la rareté, carte du match de la nuit à bord doré animé,
  « film du match » (courbe de l'écart, + = domicile devant, données `plays` du summary), verre dépoli, Barlow Condensed.
- **Sans spoil** : mêmes règles que la v1 (rien tant qu'on ne révèle pas ; bilans affichés seulement avant match ou après
  révélation, car les `records` ESPN incluent le résultat ; jamais « prolongation » ni quart-temps en cours sur un match caché).
- Réglages par appareil en `localStorage` (préfixe `bb2_`) : équipe favorite (`fav`), « toujours montrer » (`showall`),
  nuits vues (`vues`), bienvenue (`hello`). **Pas de compte** (décision Kiki). Public et gratuit, pas de monétisation (droits logos/ESPN).
- Vidéos : robot `.github/workflows/videos-v2.yml` + `scripts/v2_videos.py` (toutes les 20 min, **flux RSS publics**
  des 3 chaînes — GameTime, NBA, beIN — sans clé, cumulés 10 jours) → `v2/videos.json` sur la branche `data`, lu par le
  site via raw.githubusercontent.com. `findVideo` associe le match à son résumé (surnom d'équipe + date NY, GameTime
  d'abord, choix de Kiki) et l'ouvre dans un **lecteur intégré** (youtube.com/embed, PAS youtube-nocookie : sur la Xbox, ce dernier ignore la connexion Google et bloque sur « confirmez que vous n'êtes pas un robot ») ; sinon, recherche YouTube en filet.
  ⚠️ Le cron ne tourne que depuis la branche par défaut (main) : actif après la fusion.
- **Révéler = REVIVRE LE MATCH EN ACCÉLÉRÉ** (le moment signature, réponse au retour « pas assez d'ambition » du 13/11) :
  les deux scores s'affrontent quart-temps par quart-temps (`linescores` du scoreboard, ~0,5 s par quart), le leader
  s'illumine (`.lead`/`.trail`), étiquette Q1→Q4/Prolongation, verdict final + particules selon la rareté.
  « Tout révéler » = cérémonie du moins bon au meilleur, le match de la nuit en dernier (800 ms d'écart).
- **Boutons (20/11, demande de Kiki)** : « ▶ Replay » (le résumé vidéo du match) et « ▶ Replay + » quand la vidéo a sa table de
  stats (`hasPlus` → `Chrono.hasMap`, boutons mis à jour par `refreshReplays` quand l'index arrive) ; plus AUCUN bouton NBA Extra
  par match (« Replay FR » supprimé le 20/11, choix de Kiki : pas de stats possibles, beIN interdit la lecture intégrée) ; seul
  reste le journal du matin « NBA Extra · le journal » en tête de la nuit (`findExtra` n'est plus appelé par les tuiles). Drapeau : 3 bandes parallèles au bord incliné du bouton (SVG en fond). Le match de la
  nuit affiche la jauge 5 barres + le commentaire (plus « À voir · 02h00 »).
- **NBA Extra de retour** : bouton par match (titre beIN « Résumé : X @ Y », `findExtra`), journal du matin
  (« REPLAY - NBA Extra (13/11) » = nuit du 12 au 13, `findJournal`) et « Résumé de la nuit » NBA (`findNightRecap`,
  « nightly recap » + date) en tête de page ; lecteur intégré (`playVideo`), SAUF les vidéos beIN (`c: "bein"`) : beIN bloque
  leur lecture hors de YouTube (« Vidéo non disponible »), donc NBA Extra s'ouvre dans un nouvel onglet YouTube (app sur téléphone).
- **Stats synchronisées sur le résumé : MODE PRÉPARÉ (19/11, le principal)** : le **téléphone-serveur** de Kiki (Mi A2 Lite sous Termux,
  `ssh telephone`, voir `scripts/telephone/`) lit `v2/videos.json` toutes les 20 min (`boucle.py`, lancé au démarrage par
  `~/.termux/boot/demarrage.sh`), télécharge chaque nouveau résumé de match (GameTime puis NBA, 3 derniers jours, 720p sans son,
  connexion de particulier : pas de blocage YouTube), en lit le chrono 1 image / 2 s (`chrono_video.py` : même lecture en 2 temps
  que le site, puis plus longue suite chronologique) et publie `v2/chrono/<id>.json` (`pts` = [seconde vidéo, quart, secondes
  restantes]) + `v2/chrono/index.json` sur la branche data (clé de déploiement « Téléphone serveur Nocturne », écriture).
  **Tri (19/11, choix de Kiki)** : seuls les matchs à **3 barres ou plus** sont analysés (`note` = watchLevel du site porté en
  Python sur le scoreboard ESPN, `match_de` relie le résumé au match), un seul résumé par match (GameTime, sinon NBA), meilleurs
  d'abord : 1 à 4 matchs par nuit. **1 image par seconde** (`PAS = 1`).
  ~10-15 min par résumé à 2 s (environ le double à 1 s). Recherche du bandeau : chrono « mm:ss » seulement (un bilan « 4-9 » lu
  « 4.9 » passait pour un chrono en dixièmes) ; zone verrouillée : les 4 réglages tesseract essayés avant d'abandonner une image.
  Sur le site, avant le 1er point : stats à zéro et « En attente du chrono… ». Format : 720p OBLIGATOIRE (en 480p le bandeau est illisible), H.264 puis VP9 (l'AV1 fait planter le
  décodeur du téléphone). Bandeaux testés : NBC (chrono au-dessus de « 1ST ») et ESPN (tout sur une ligne, chrono sur fond blanc,
  « 2ND » illisible → quart-temps déduit de la chronologie dans `nettoyer`, le plus tôt en cas de doute). Garde-fou : publiée
  seulement si ≥ 40 points et jusqu'au 4e quart-temps. yt-dlp utilise Node.js
  (`~/.config/yt-dlp/config` = `--js-runtimes node`, sinon téléchargement bridé). Journal : `~/nocturne/boucle.log`, état : `etat.json`. Le site (`attach` → `prepLoop`) suit la position du lecteur YouTube (postMessage) et affiche le dernier point
  déjà passé (jamais en avance) : aucun partage d'écran, marche aussi sur téléphone. Le lecteur envoie sa position toutes les
  ~0,27 s ; `momentAt` fait couler le chrono entre deux points d'une même action (sinon reste sur le dernier point).
  Panneau = **stats seules** (choix de Kiki : le chrono et le score affichés rendaient visibles les petits décalages) ; les chiffres
  qui changent s'allument (`.up`) ; `?debug=1` réaffiche chrono + score pour contrôler. Boucle du téléphone **rallumée le 19/11 à
  15h08** (après un mode essai) : `depuis.txt` = cette date, donc seulement les nouvelles soirées, jamais l'historique.
  Tables d'essai publiées : Lakers-Hornets, Celtics-Nuggets, Suns-Kings (17-18/11).
  **Plein écran (19/11, demande de Kiki)** : avec stats possibles (`Chrono.wantsFull`), le lecteur s'ouvre en plein écran
  (`requestFullscreen` pendant le clic, classes `.full`), **sans défilement sur PC**, **sans bandes noires** (21/11, demande de Kiki : la vidéo remplit sa colonne ; la colonne des stats
  fait 340-440 px et absorbe le reste ; le film du match garde 26 % de la hauteur, 170-260 px ; terrain des tirs = hauteur restante) : stats à droite, joueurs en **tableau compact** (une ligne par joueur, Pts/Reb/Pd ; toujours 5 par équipe : ceux qui
  ont des stats, complétés par le 5 de départ ESPN `starter`) + **tendances** en 4 tuiles SOUS LA VIDÉO à droite du film (21/11, pour laisser au terrain toute la largeur de la colonne) (`trendsHTML` : écart, série en cours,
  plus gros run, plus grosse avance ; « temps en tête » et « changements de leader » sont dans l'en-tête du film, `.lv-fx`) puis **le mini-terrain des tirs** (`shotsHTML` : terrain entier, visiteurs à gauche, domicile à droite, ● réussi /
  ✕ raté à la couleur de l'équipe, anneau sur le dernier tir, tirs ESPN `coordinate` gardés dans `parsePlays` sx/sy, lancers exclus)
  + tableau Raquette / Mi-distance / 3 points. Écran < 900 px de haut : version resserrée ; < 740 px (Xbox, 1280×720) : terrain réduit à 15 % de la hauteur, jamais masqué. Pendant la vidéo, `body.vidon` cache la page derrière et arrête ses animations (vidéo saccadée sur la Xbox), fond du lecteur opaque sans flou ; sous la vidéo (`curveHTML`, `#lvbelow`) le film du match en ligne continue FUSIONNÉ avec les scores
  par quart-temps, alignés sous chaque quart (quarts TERMINÉS seulement, le quart en cours = « en cours » ; prolongation ajoutée
  à l'axe seulement une fois atteinte). Calculs communs : `flow(D, at)`. La courbe est le VRAI fil du match, **un point à chaque panier** (21/11, choix de Kiki : « plus palpitant », les allers-retours font des dents ; avant, un point par minute écrasait 4 minutes de paniers en un trait plat) : `flow().pts`, et la fiche prend exactement les mêmes points (`Chrono.film(j)` dans `normSummary` → `series` = [[secondes de jeu, écart]], `span` ; `chartHTML`/`hookChart` en secondes, l'ancien format par minute du mode démo est converti par `filmPts`). Elle se découvre par à-coups au fil des sauts du résumé et finit identique à celle de la fiche (vérifié point par point sur 5 matchs du 17/11).
  « Dernières actions » retirées (illisibles sur un résumé). Téléphone : vidéo, stats, puis le dessous, en une colonne. Sans table : mode direct ci-dessous (PC),
  sinon pas de panneau sur téléphone.
- **Stats en direct sur le résumé (19/11, `docs/chrono.js`) : RETIRÉ de l'interface le 21/11 (Kiki voyait encore le panneau « Activer » ; pas assez fiable)** : `Chrono.CAN` n'est vrai qu'avec `?live=1` ; sans table préparée, le Replay est la vidéo seule. Ancienne description : sur ordinateur, panneau à droite du lecteur (`playVideo(vid, label, gid)`).
  Partage de l'onglet (`getDisplayMedia`, seule façon de voir l'image d'un lecteur YouTube) **une fois par visite** : le flux est gardé
  d'un résumé à l'autre ; après la 1re activation (`bb2_liveused`), le partage est demandé dès le clic « Résumé » (`onResumeClick`,
  geste exigé par le navigateur ; case « Proposer le partage… » = `bb2_live`). Lecture en 2 temps (tesseract.js, jsdelivr) :
  recherche dans le bas 30 % de la vidéo (PSM 11, gris/inversé) du quart-temps « 1ST… » ou du chrono, puis **verrou** sur une petite
  zone chrono + quart-temps (PSM 6, inversé, ~0,1 s, fiable sur les vraies images). Anti-spoil (`accept`) : « 1:05 » peut être un
  « 11:05 » mal lu → on prend l'option cohérente avec la lecture d'avant, sinon celle qui colle à la place dans la vidéo (position et
  durée envoyées par le lecteur YouTube via `enablejsapi` + postMessage « listening »), sinon la plus tôt ; avancer loin dans le match
  demande 3 lectures concordantes (2 après un saut dans la vidéo). Pause YouTube = lecture en pause. 🔧 = diagnostic (zone lue + texte).
  Stats depuis `plays` ESPN jusqu'à ce moment (`statsAt` : identique à la feuille ESPN). Testé sur de vraies images du résumé GameTime
  (bandeau NBC) avec un faux partage (`canvas.captureStream`) : le navigateur intégré refuse le vrai partage. Vidéo < ~600 px de large :
  illisible. Le robot qui préparerait tout à l'avance est impossible (YouTube bloque GitHub Actions, on ne contourne pas).
  Démo : `?demo=1&live=1`. ESPN depuis le navigateur : CORS OK (19/11).
- **Cache** : GitHub Pages garde les fichiers 10 min ; `index.html` appelle `app.js?v=…` etc. : changer ce `v` à chaque modif.
- Fiche : feuille de match complète (Min/Tirs/3 pts/Reb/Pas/Pts) ; clic sur un joueur = **carte de tirs animée**
  (tirs ESPN `plays[].coordinate` : **ESPN mesure y depuis le PANIER** → `y + 5.25` pour le dessin (21/11 : sans ça, 162 tirs à 3 pts sur 291 tombaient devant la ligne), panier dessiné en (25, 5.25) pieds, moitiés de terrain repliées, lancers francs exclus),
  replay ~5 s avec compteur en direct (quart-temps, n° de tir, points cumulés) + bouton « ↻ Rejouer ».
- **« L'essentiel de la nuit » (20/11, remplace « Qui a tout cassé »)** : une seule rubrique, cachée derrière « Voir l'essentiel »
  (seule rubrique qui assume les résultats). `loadMVP` : **faits marquants** (`nightFacts`, 6 max, 2 par match/type : surprise =
  bilans d'avant-match (`moins`) écart ≥ 0,2 ; prolongation / thriller ≤ 3 pts ; remontée ≥ 15 pts (`series`) ; démonstration ≥ 25 ;
  40 pts, triple-double, 8 paniers à 3 ; cartes `factHTML` aux 2 couleurs + score LED + photo pour les perfs) ; **MVP + 6 perfs** ;
  **Les Français** (lieu de naissance / citoyenneté des effectifs ESPN `teams/<id>/roster`, `frenchIds`, gardé 7 jours en
  `bb2_fr`) ; **ça a bougé au classement** (dernière nuit seulement : classement ESPN actuel vs moins les résultats de la nuit,
  `standingMoves`, ≥ 2 places ou changement de zone) ; **sortis blessés** (blessés du matin absents de la photo d'avant-match).
  Articles accordés : `le`/`du`/`au` (le Jazz, le Magic, le Heat, le Thunder ; les autres au pluriel).
  Hiérarchie (demande de Kiki : « trop fouillis ») : le titre « L'essentiel de la nuit » reste une fois ouvert (`.ess-top`), puis
  une étiquette + un trait par partie (`.ess-h`) : Les faits marquants · Le MVP et les grosses perfs · Les Français de la nuit ·
  Et aussi (classement, blessés). Français = **tuiles** (`.frt` : photo cadrée dans un carré aux couleurs de l'équipe + logo,
  nom, équipe · minutes, stats dessous), `--n` colonnes : 1 à 5 sur une ligne, 6 = 2 × 3, puis 4 ; 370 px max par tuile ;
  2 par ligne sur téléphone (photo au-dessus).
- **Infos clés d'avant-match (20/11, `keyFacts`, TOUJOURS 3 par match si possible, place de 3 lignes réservée : tuiles de même
  hauteur)** : grosse absence / incertain (star ou meilleur marqueur dans ESPN `/injuries`), choc au sommet / grand favori / pile ou
  face, duel de stars (2 × ≥ 25 pts) ou homme en forme (≥ 26 pts), fatigue (2e soir, ou les deux équipes), forteresse / mal chez eux /
  en galère ou solides dehors ; infos de secours (une seule par thème, `kinds`) : infirmerie (≥ 3 absents), les meneurs, les bilans,
  dom./ext. Nuits passées sans photo : souvent 2 infos seulement (pas de leaders ni de blessés). Match de la nuit : pied compact
  (bug corrigé : chaque ligne héritait de 260 px de haut). MVP : carte + stats à gauche (prénom au-dessus du nom), les 6 grosses
  perfs à droite en 2 colonnes (`.mvpw`). Affichées AUSSI sur les
  matchs joués, sans spoil : `avantMatch` prend la **photo d'avant-match** publiée par le téléphone (`photo_avant` dans
  boucle.py → `v2/avant/<nuit NY>.json` : bilans, meilleur marqueur `pointsPerGame`, star `rating`, blessés, mise à jour tant
  que le match n'a pas commencé) ; sans photo, bilans recalculés en retirant le résultat (`moins`), sans leaders ni blessés
  (après le match ESPN remplace les leaders de la saison par ceux du match). Testé : des données d'après-match truquées ne
  changent rien. Afficheurs de score : largeur fixe de 3 chiffres (`min-width:calc(3ch …)`), « ?? » compris.
- **Couleurs proches (21/11, demande de Kiki : 76ers / Magic tous deux bleus)** : `ALT` = 2e couleur de chaque équipe ; `vsColor(visiteurs, domicile)` : si l'écart perçu (`colorGap`, « redmean ») est < 170, les VISITEURS prennent leur 2e couleur (sinon blanc cassé), le domicile garde la sienne. Appliqué à chaque match dans `normEvent`/`scoreboard` (`pairColors`, démo et copie de secours comprises), dans la fiche (`teamIn`, carte de tirs) et le Replay + (chrono.js). **Patrons du match** : plus de « TOP MATCH » (il passait sous les barres), logo + nom de l'équipe en tête de carte à sa couleur, barres REB / PD / CTR. **Contres** : colonne « Ctr » de la feuille de match (ESPN `BLK`), barre CTR des patrons, et dans le Replay + (ligne « Contres » + colonne « Ctr » des joueurs : `statsAt` compte les tirs ratés « X blocks Y's shot », contreur = 2e nommé `a1`, équipe adverse du tireur ; vérifié identique à la feuille ESPN sur 2 matchs).
- **Retouches du 21/11 (soir)** : MVP français = absent de « Les Français de la nuit » (devient « Les autres Français de la nuit ») ;
  « Et aussi » agrandi (logos 48 px, noms 21 px, places en LED, étiquette Forfait/Incertain) ; frise des nuits : seules « Cette nuit »
  (la dernière jouée) et « Demain » ont un nom, la veille affiche « Retour sur la nuit » (plus de « Nuit dernière ») ; calendrier
  « Autre nuit » = `div` qui appelle `showPicker()` (un `<input>` dans un `<button>` ne recevait pas le clic) ; classement sans
  grand titre, étiquette + coupure + légende sur une ligne (`.cutbar.onel`). **Replay +** : la colonne des stats est une pile de
  100 vh qui se remplit toujours (terrain des tirs EN HAUTEUR dès 860 px de haut, `.lv-court.cv` tourné d'un quart de tour,
  visiteurs en haut ; les lignes de stats s'aèrent s'il reste de la place ; textes plus grands dès 1100 px de haut) ; bouton ⛶
  `.fsb` à gauche de la croix, visible seulement hors plein écran (`fullscreenchange` → `.fs`) ; en-tête du panneau réservé
  (96 px) pour que la croix ne recouvre rien. **Firefox** : classe `ff` sur `<html>` (index.html) → pas de flou d'arrière-plan,
  ciel figé, pas d'entrées en scène, pas d'ombres floues (artefacts de calques composés, même remède que le site NFL).
- **Retouches du 22/11** : nuit par défaut = la DERNIÈRE NUIT JOUÉE (`defaultNight` recule de 18 h à NY : bascule à 18 h NY,
  minuit à Paris) ; frise : « Cette nuit » (dernière jouée), « La nuit à venir » (la suivante), le reste en dates ; programme à
  partir d'aujourd'hui (NY). Classement : « La hiérarchie » sur une ligne (`nowrap`). « Et aussi » SUPPRIMÉ : les sortis blessés
  (seulement titulaires / ≥ 18 min / ≥ 10 pts ; `starter` ajouté aux feuilles de match) et les mouvements au classement sont des
  **faits marquants** (`extra` passé à `nightFacts`, types `blesse` et `classement`). Contres : 4e afficheur du MVP, « · 3 CTR »
  dans les grosses perfs dès 3, « ctr » sur les tuiles des Français dès 1. **Révéler la nuit** : plus de défilement ni de course
  par quart-temps, tous les scores s'allument ensemble en < 1 s (`reveal(id, false, quick)`).
- **Résumé de la nuit + (22/11, carte blanche de Kiki)** : le « NBA's Nightly Recap » est chapitré (« Knicks at Timberwolves »…,
  « Player of the Night », « Top Plays of the Night »). Le téléphone (`scripts/telephone/nuit.py`, appelé par `boucle.py` →
  `nuits()` après les résumés de match, 2 derniers jours, un par passage) : chapitres via `yt-dlp -J` reliés aux matchs ESPN
  (surnoms), publiés tout de suite, puis vidéo 720p, chrono lu chapitre par chapitre (`Lecteur` neuf + `nettoyer` par match),
  et le nom du joueur de la nuit lu à l'écran (images toutes les 2 s du chapitre, comparées aux 14 meilleures perfs, ≥ 2 lectures)
  → `v2/nuit/<nuit NY>.json` (`ch` : `{s, e, t, k: match|potn|top, gid, pts, aid, n}`). Site : `loadNuit`, bouton « Résumé de la
  nuit + » (`openNightPlus` → `playVideo(..., {night})` → `Chrono.attachNight`) : plein écran, **liste des matchs à gauche**
  (`.np`, cases qui se partagent toute la hauteur) dans l'ordre du résumé : à venir = gris « ?? », en cours = aux couleurs, score
  qui suit le chrono (`momentAt` + `flow`), passé = score final SEULEMENT si on a regardé la fin du chapitre (`S.done`), sauté =
  « Pas encore vu » ; clic = saut dans la vidéo (`seekTo` par postMessage) ; dessous : film du match + tendances du match en
  cours, ou la carte du joueur de la nuit. **MVP = le Player of the Night de la NBA** quand il est lu (étiquette « Choisi par la
  NBA »), bouton « ▶ Son match en vidéo » = extrait du chapitre (`data-vs`/`data-ve` → `&start=&end=` de l'embed) ; « ▶ Les plus
  belles actions » en tête de l'essentiel. Attention : la classe `.x` est celle de la croix de fermeture (ne pas la réutiliser).
- **Score = celui LU À L'ÉCRAN (22/11, retour Kiki : « 14-5 jamais vu à l'écran »)** : le minutage ESPN des paniers ne colle
  pas toujours au bandeau et beaucoup d'images n'ont pas de chrono lisible. `chrono_video` lit aussi la ligne du bandeau
  (`Lecteur.ligne` : les mots à la hauteur du chrono, ou toute la bande pendant une recherche), garde les nombres (`nombres`),
  les recoupe avec la suite des scores ESPN (`deroule(gid)` → `etats`, `soutenus`) et `caler` choisit la plus longue suite
  chronologique (poids ×3 si le chrono lu colle) → points `[t, quart, secondes, score visiteurs, score domicile]`, moment
  borné à l'intérieur du score vu. `lire_plage` = lecture d'une plage d'images. Aussi pour les Replay + des matchs
  (`boucle.py` passe `v["gid"]`). Site : `momentAt` renvoie `sc`, `clampAt(D, at, sc)` empêche le chrono qui coule de passer
  un panier pas encore vu (Replay + et résumé de la nuit). Appels ESPN du téléphone : 5 tentatives (le wifi a des trous).
- **Joueur de la nuit et plus belles actions (22/11)** : le téléphone lit aussi le chrono/score du chapitre « Player of the
  Night » (calé sur son match) et repère chaque action du top (`actions` : sigles du bandeau → match, chrono + score → le
  panier ESPN → le joueur `a0`, nom via la feuille de match) → `top.plays = [{s, e, gid, aid, n, per, sec, tx}]`. Site :
  sous la vidéo, carte du joueur (stats du match, « points vus dans la vidéo » en LED) + **demi-terrain où ses tirs
  s'ajoutent au fil de la vidéo** (`potnCourt`) ; top = cartes de gauche à droite (n° 5 → n° 1) dévoilées quand l'action
  passe, 5 stats chacune (`topCards`). Depuis l'essentiel : « ▶ Ses meilleures actions » (à la place de l'étiquette
  « Choisi par la NBA », supprimée) et « ▶ Les 5 plus belles actions » ouvrent l'EXTRAIT SEUL (`openNightPlus(key, solo)`,
  `&start=&end=`, classe `.solo`) : vidéo + colonne de droite (`.nps` : carte + terrain, ou grande carte de l'action) +
  dessous (film de son match, ou les 5 cartes).
- **Réglages du calage (22/11 soir, mesurés sur la nuit du 19)** : les chiffres du bandeau se lisent MAL (tesseract rate
  souvent le « 7 »), le chrono bien ; le bandeau change de score ~3 s de chrono AVANT l'horaire ESPN → `RETARD = 3.5` ajouté
  au chrono lu ; le chrono prime, un score lu ne sert de borne que sur sa propre image (et sans chrono, il doit coller aux
  chronos voisins). Limite connue : ESPN corrige parfois des paniers (le bandeau a montré 37-30 puis 97-90, scores absents du
  fil ESPN) → écart d'un panier possible. Lectures brutes gardées par nuit.py (`brut_<vid>.json` à côté du script) pour
  recaler sans relire la vidéo. **Top 5** : les cartons bleus « 5 »… « 1 » découpent les actions (`carton` : couleur moyenne
  b > 70, r < 60, b > r + 40) ; dans chaque action, le bandeau (sigles, chrono « m:ss » uniquement — « 123 » = bilan 12-3 —,
  scores ≥ 10) donne le moment, l'action = le panier ESPN suivant ; non reconnue → carte du match (`gameCard`). Nuit du 19 :
  2 joueurs sur 5 reconnus.
- **Scores lus CASE PAR CASE (22/11, nuit)** : la vidéo est bien en 720p, c'est la lecture qui était mauvaise (toute la ligne
  d'un bloc, même traitement pour la case blanche aux chiffres noirs et la case sombre aux chiffres blancs). `Tableau(D)` :
  repère les sigles des deux équipes (le plus gros = celui du tableau, pas du petit bandeau « NYK 12-0 RUN… » ; plusieurs
  images au besoin, le sigle noir sur blanc se lit mal), en déduit les deux cases (collées au sigle côté centre, ±0,58 h en
  hauteur pour ne pas attraper la ligne « FOULS | 1 »), cherche le bord exact de chaque case (`affiner` : changement de
  couleur qui dure ≥ 12 px, à plus de 1,5 h du sigle), puis `chiffres` : fond décidé par les bords haut/bas, 3 seuils × 3
  réglages tesseract (chiffres seuls) qui VOTENT, traits fins et aplats collés aux côtés effacés ; une case inchangée n'est
  pas relue (`memo`), une case dont le fond a changé (gros plan) est sautée. `caler` : `etendre` (« 907 » → 90 + 07 à
  demi-voix), score exact ESPN (poids fort) ou à 3 points près (ESPN a corrigé un panier : on affiche QUAND MÊME le score
  de l'écran), le chrono seul garde le dernier score vu tant qu'il reste dans ce score (+20 s). Site : `sc` affiché tel quel.
  Résultat nuit du 19 : Knicks-Wolves 4/5 instants de contrôle exacts (2-5, 14-7, 37-30, 71-57 ; 97-91 au lieu de 97-90),
  points avec score lu : 52/58, 75/77, 58/80, 47/63. `test_cases.py` = test sur images de référence (lancer DÉTACHÉ sur le
  téléphone : les longues sessions SSH coupent). ~15 min par chapitre de 3 min.
- **Mode démo** : `?demo=1` = fausse saison stable (`demo.js`), l'équivalent de `BB_FAUX_ESPN=1`. Test local :
  `python3 -m http.server 8777` dans `docs/` puis `http://localhost:8777/?demo=1` (Playwright : PC 1400px + téléphone 393px,
  vérifier zéro erreur JS et zéro défilement horizontal).
- Reste à faire (plan dans `kiki-cerveau/projets/replay-nba/CONTEXTE.md`) : brief, classement, équipes, joueurs,
  cartes de tirs, robot data, PWA, domaine, redirection de l'ancien site. **Le Streamlit ci-dessous reste la prod** jusqu'à la bascule.

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
- **Navigation (v023-v029, carte blanche de Kiki)** : en-tête = marque seule (v024 : plus de pastille « sans spoil ») + v029 : petite roue crantée
  discrète collée au titre (popover sans texte ni flèche), plus de bouton « Réglages » à droite ; haut de page remonté (les blocs
  invisibles du haut : styles, scripts `run_js`, champ caché `gobox`, sont sortis du flux) ; ⚙️ Réglages
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
  dont le classement dans le brief via `moves` ; v028 : sans la ligne MVP dans le brief, `mvp=False`)
  **v030 : rubriques cachées du brief refaites (`card` dans `brief_page`)** : chaque rubrique cachée = carte « teaser » engageante
  (grande icône, titre, phrase qui donne envie sans spoiler, toute la carte se clique ; flèche › sur téléphone), puis le contenu avec
  « 🙈 Cacher ». Disposition SANS TROUS : grille 2 colonnes `align-items:stretch` : [La nuit en bref | Ce qui a bougé (6 équipes,
  une ligne chacune `.cls-l`)], puis en PLEINE LARGEUR (`.full`) « Le MVP et les grosses perfs » (MVP en grand : photo 120 px,
  pastille MVP, nom en entier sur une ou deux lignes jamais coupé au milieu, 9 cases de stats en une rangée ; autres perfs en
  3 colonnes `.op-g`), puis « Nos Français » (cartes `.op`). Grosses absences : 3 colonnes, textes coupés par « … » (plus de chevauchement). ; à côté, « 💥 Le MVP et les grosses perfs » : le MVP de la nuit (meilleur `game_score` : photo, équipe,
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
  page admin sont marqués (cookie `nba_me` + liste `_moi` dans `stats/names.json`). v028 : qui est qui (`person` dans `admin_page`) :
  nom donné (page admin ou lien personnel `?qui=tom|busta|kiki`, `WHO`, enregistré par `finish_run`), sinon Kiki = appareils de
  l'admin, Busta = fuseau d'Amérique (Montréal), « Tom ? » = appareil français revenu au moins 2 jours. Kiki est compté (interrupteur
  « Exclure mes visites »). Une arrivée notée avec un n° provisoire passe au vrai n° quand `restore` le donne (`apply_restore`).
  v022 : `nba_id` écrit dès le début de la page et « arrivée » comptée seulement en fin de page (avant : chaque chargement
  interrompu créait un faux visiteur). Noms donnés aux visiteurs : `stats/names.json` ; même nom = une seule personne.

- **Réveil du site (v032)** : Streamlit Cloud endort le site sans visite (30-40 s pour le réveiller). Robot GitHub
  `.github/workflows/reveil-site.yml` (même manip que le site NFL) : toutes les heures, Playwright ouvre
  `https://badabingnba.streamlit.app/?robot=1` et clique « Yes, get this app back up » si besoin. `?robot=1` (ou un navigateur
  « HeadlessChrome ») = `trk["bot"]` : pas compté dans les statistiques. Ne tourne que depuis la branche par défaut (main).

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
