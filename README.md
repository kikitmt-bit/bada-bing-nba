# Bada Bing NBA : notes pour Claude

Site Streamlit (`app.py`, un seul fichier) en français : les matchs NBA **sans spoil**. Réponses à l'utilisateur en français.
Projet à part du site NFL (`nfl_pronos`) ; utilisé par Kiki (Paris) et un ami à Montréal.

## Ce que fait le site

- Matchs groupés par « jour du match » d'ESPN (heure de New York), titre selon le fuseau : « Nuit du mercredi 21 au jeudi 22 octobre » (Paris)
  ou « Mercredi 21 octobre » (Montréal). Fuseau deviné du navigateur (`st.context.timezone`), modifiable dans ⚙️ (gardé dans l'adresse : `?tz=`).
  Jour affiché par défaut : la nuit qui vient de se jouer (`default_day`).
- **Interface (v002)** : chaque carte de match est du HTML pur (`game_card`) ; « 👁 Score » et « 📊 Forme & duels » sont des cases à cocher
  cachées (`.tg-s`, `.tg-f`) qui ouvrent les panneaux en CSS, sans recharger la page. Visiteurs à gauche, domicile à droite, enjeux toujours visibles.
  En-tête de la nuit (`night_html`) : NBA Extra du lendemain (12h45, replay vers 15h-17h) et résumé de la nuit NBA, puis « À voir en priorité ».
  Indice « à voir » sans dire qui gagne (`watch_score` : écart final, fin serrée, remontée, prolongation, grosse perf) qui range les matchs terminés ;
  « L'affiche de la nuit » pour les matchs à venir (`hype`). Équipes favorites (cookie `nba_fav`) en tête. Durées des vidéos via l'API YouTube.
- **No spoil** : score caché par défaut (rien n'est retenu d'une visite à l'autre), ou ⚙️ « Toujours montrer les scores » (`?scores=1`). Tant que c'est caché : pas de score, pas de « prolongation », bilans et séries calculés
  AVANT le match (`team_form`, `head_to_head` sur `team_index`), jamais ceux d'ESPN (qui incluent le résultat).
- Vidéos : résumé officiel NBA (« KINGS at CLIPPERS | FULL GAME HIGHLIGHTS | October 21, 2026 », `nba_video`), résumé de NBA Extra
  (beIN SPORTS, « Résumé : WARRIORS @ LAKERS, … », `extra_video`), journal NBA Extra (« REPLAY - NBA Extra (21/10) », `journals`, 12h45 à Paris),
  résumé de la nuit NBA (`nightly_recap`). Boutons sans le titre des vidéos (les titres de NBA Extra peuvent spoiler).
  Sans clé YouTube : seulement les 15 dernières vidéos de chaque chaîne (flux public) ; avec `[youtube] api_key` : tout l'historique utile.
- Avant-match écrit (`preview_points`) : contexte, forme, face-à-face, absents (ESPN), favori (cote figée). Blessés et cotes d'avant-match gardés
  dans `.cache/pre_<id>.json` (perdus à un redémarrage de Streamlit Cloud : pas grave, la preview d'un match passé s'en passe).
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

`python -m streamlit run app.py --server.port 8531`, puis vérifier à l'écran (PC et téléphone). Incrémenter `APP_VERSION` à chaque changement.
