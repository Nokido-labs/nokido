"""Donnees des bancs du census (23/10) : items, tests caches, reponses attendues. AUCUNE donnee du projet ni secret :
tout est synthetique et generique. Les juges et le lanceur sont dans forge_free_tier_census.py (pas de module parallele).
Rapport : sandbox/workspace/rapport_bancs_census_20261023.md
"""
from __future__ import annotations

FORMAT_REPONSE = "Termine par une ligne 'Reponse finale: <reponse>'."

# --- code : 12 fonctions, tests caches (args -> attendu) executes HORS LIGNE par le juge --------------------------------
CODE = [
    dict(id="c01", fonction="somme_pairs", prompt="Ecris la fonction Python somme_pairs(liste) qui rend la somme des entiers pairs de la liste.",
         tests=[[[[1, 2, 3, 4]], 6], [[[]], 0], [[[7, 9]], 0], [[[-2, 2, 10]], 10]]),
    dict(id="c02", fonction="inverser_mots", prompt="Ecris la fonction Python inverser_mots(s) qui rend la phrase avec l'ordre des mots inverse (separateur : un espace).",
         tests=[[["un deux trois"], "trois deux un"], [["a"], "a"], [["x y"], "y x"]]),
    dict(id="c03", fonction="est_palindrome", prompt="Ecris la fonction Python est_palindrome(s) qui rend True si s est un palindrome en ignorant la casse et tout caractere non alphanumerique.",
         tests=[[["Kayak"], True], [["A man, a plan, a canal: Panama"], True], [["abc"], False], [[""], True]]),
    dict(id="c04", fonction="fibonacci", prompt="Ecris la fonction Python fibonacci(n) qui rend le n-ieme nombre de Fibonacci avec fibonacci(0)=0 et fibonacci(1)=1.",
         tests=[[[0], 0], [[1], 1], [[10], 55], [[20], 6765]]),
    dict(id="c05", fonction="compter_voyelles", prompt="Ecris la fonction Python compter_voyelles(s) qui compte les voyelles a, e, i, o, u (y exclu), sans tenir compte de la casse.",
         tests=[[["Bonjour"], 3], [["xyz"], 0], [["AEIOU"], 5], [[""], 0]]),
    dict(id="c06", fonction="fusionner_tries", prompt="Ecris la fonction Python fusionner_tries(a, b) qui fusionne deux listes deja triees en une liste triee.",
         tests=[[[[1, 3], [2, 4]], [1, 2, 3, 4]], [[[], [5]], [5]], [[[1, 1], [1]], [1, 1, 1]]]),
    dict(id="c07", fonction="premiers_jusqua", prompt="Ecris la fonction Python premiers_jusqua(n) qui rend la liste croissante des nombres premiers <= n.",
         tests=[[[10], [2, 3, 5, 7]], [[1], []], [[2], [2]], [[30], [2, 3, 5, 7, 11, 13, 17, 19, 23, 29]]]),
    dict(id="c08", fonction="pgcd", prompt="Ecris la fonction Python pgcd(a, b) qui rend le plus grand commun diviseur de deux entiers positifs.",
         tests=[[[12, 18], 6], [[17, 5], 1], [[0, 9], 9], [[100, 75], 25]]),
    dict(id="c09", fonction="aplatir", prompt="Ecris la fonction Python aplatir(l) qui aplatit une liste imbriquee a profondeur quelconque en une liste simple, dans l'ordre.",
         tests=[[[[1, [2, [3, 4]], 5]], [1, 2, 3, 4, 5]], [[[]], []], [[[[[1]]]], [1]]]),
    dict(id="c10", fonction="anagrammes", prompt="Ecris la fonction Python anagrammes(a, b) qui rend True si a et b sont des anagrammes (casse ignoree, espaces ignores).",
         tests=[[["Listen", "Silent"], True], [["abc", "abd"], False], [["a b", "ba"], True]]),
    dict(id="c11", fonction="somme_chiffres", prompt="Ecris la fonction Python somme_chiffres(n) qui rend la somme des chiffres decimaux d'un entier positif.",
         tests=[[[0], 0], [[1234], 10], [[999], 27]]),
    dict(id="c12", fonction="compresser", prompt="Ecris la fonction Python compresser(s) qui rend l'encodage par plages : 'aaabcc' donne 'a3b1c2'. Chaine vide : chaine vide.",
         tests=[[["aaabcc"], "a3b1c2"], [[""], ""], [["z"], "z1"], [["aabb"], "a2b2"]]),
    # 24/10 : items durs (bords, complexite) -- 9 modeles sur 15 etaient a 1.0 sur les 12 faciles.
    dict(id="c13", fonction="fusionner_intervalles", prompt="Ecris la fonction Python fusionner_intervalles(iv) qui fusionne une liste d'intervalles [debut, fin] non triee : deux intervalles qui se chevauchent ou se touchent (fin == debut suivant) sont fusionnes ; rend la liste triee de listes [debut, fin].",
         tests=[[[[[1, 3], [2, 6], [8, 10]]], [[1, 6], [8, 10]]], [[[[1, 4], [4, 5]]], [[1, 5]]], [[[[5, 7], [1, 2], [2, 3]]], [[1, 3], [5, 7]]], [[[]], []], [[[[1, 10], [2, 3]]], [[1, 10]]]]),
    dict(id="c14", fonction="plus_longue_sans_repetition", prompt="Ecris la fonction Python plus_longue_sans_repetition(s) qui rend la LONGUEUR de la plus longue sous-chaine contigue sans caractere repete.",
         tests=[[["abcabcbb"], 3], [["bbbbb"], 1], [["pwwkew"], 3], [[""], 0], [["abba"], 2], [["tmmzuxt"], 5]]),
    dict(id="c15", fonction="somme_max_contigue", prompt="Ecris la fonction Python somme_max_contigue(l) qui rend la plus grande somme d'un sous-tableau contigu NON VIDE d'une liste non vide d'entiers (qui peuvent tous etre negatifs).",
         tests=[[[[-2, 1, -3, 4, -1, 2, 1, -5, 4]], 6], [[[-3, -1, -2]], -1], [[[5]], 5], [[[1, 2, 3]], 6], [[[2, -5, 3, -1, 3]], 5]]),
    dict(id="c16", fonction="parentheses_valides", prompt="Ecris la fonction Python parentheses_valides(s) qui rend True si les parentheses (), crochets [] et accolades {} de s sont correctement imbriques et fermes ; les autres caracteres sont ignores.",
         tests=[[["([]{})"], True], [["([)]"], False], [["((("], False], [[")("], False], [["a(b[c]{d})e"], True], [[""], True], [["{[}"], False]]),
    dict(id="c17", fonction="evaluer_rpn", prompt="Ecris la fonction Python evaluer_rpn(t) qui evalue une expression en notation polonaise inverse donnee comme liste de chaines (entiers, eventuellement negatifs, et operateurs + - * /). La division entiere tronque vers zero. Rend un entier.",
         tests=[[[["2", "1", "+", "3", "*"]], 9], [[["4", "13", "5", "/", "+"]], 6], [[["7", "-2", "/"]], -3], [[["-7", "2", "/"]], -3], [[["3", "4", "-"]], -1]]),
    dict(id="c18", fonction="longueur_sous_suite_croissante", prompt="Ecris la fonction Python longueur_sous_suite_croissante(l) qui rend la longueur de la plus longue sous-suite STRICTEMENT croissante (non contigue) de la liste. La liste peut compter 20000 elements : l'algorithme doit etre en O(n log n).",
         tests=[[[[10, 9, 2, 5, 3, 7, 101, 18]], 4], [[[]], 0], [[[7, 7, 7]], 1], [[[0, 1, 0, 3, 2, 3]], 4], [[list(range(20000))], 20000], [[list(range(20000, 0, -1))], 1]]),
]

# --- raisonnement : 15 questions, reponse exacte --------------------------------------------------------------------
_R = [
    ("Un train part a 14h20 et arrive a 17h05. Combien de minutes dure le trajet ?", "165"),
    ("Si 3 machines font 3 pieces en 3 minutes, combien de minutes faut-il a 100 machines pour faire 100 pieces ?", "3"),
    ("Suite : 2, 6, 18, 54, ... Quel est le terme suivant ?", "162"),
    ("Combien d'entiers de 1 a 100 inclus sont divisibles par 7 ?", "14"),
    ("Alice est plus grande que Bob. Bob est plus grand que Chloe. Qui est la plus petite (Alice, Bob ou Chloe) ?", "chloe"),
    ("Un rectangle a un perimetre de 36 et sa longueur est le double de sa largeur. Quelle est son aire ?", "72"),
    ("Quel est le reste de la division de 2 puissance 10 par 7 ?", "2"),
    ("Combien font 17 x 23 ?", "391"),
    ("Un stylo et un cahier coutent 1,10 EUR ensemble. Le cahier coute 1 EUR de plus que le stylo. Combien coute le stylo, en centimes ?", "5"),
    ("Dans une course vous doublez le deuxieme. A quelle place etes-vous maintenant ?", "2"),
    ("Combien de fois la lettre r apparait-elle dans le mot refroidir ?", "3"),
    ("La somme de trois entiers consecutifs est 72. Quel est le plus grand ?", "25"),
    ("Si nous sommes mercredi, quel jour serons-nous dans 100 jours (en minuscules, sans accent) ?", "vendredi"),
    ("Combien de diagonales possede un hexagone convexe ?", "9"),
    ("Un article a 80 EUR subit une hausse de 25 % puis une baisse de 20 %. Quel est son prix final en EUR ?", "80"),
]
RAISONNEMENT = [dict(id="r%02d" % (i + 1), prompt=q + " " + FORMAT_REPONSE, reponse=a) for i, (q, a) in enumerate(_R)]

# --- outils : 10 appels attendus (nom + arguments en egalite JSON) --------------------------------------------------
OUTILS_SCHEMAS = [
    {"type": "function", "function": {"name": "get_weather", "description": "Meteo d'une ville",
     "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}},
    {"type": "function", "function": {"name": "add", "description": "Additionne deux entiers",
     "parameters": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}, "required": ["a", "b"]}}},
    {"type": "function", "function": {"name": "search_docs", "description": "Cherche dans une base de documents",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query", "limit"]}}},
    {"type": "function", "function": {"name": "set_timer", "description": "Programme un minuteur",
     "parameters": {"type": "object", "properties": {"minutes": {"type": "integer"}}, "required": ["minutes"]}}},
    {"type": "function", "function": {"name": "send_message", "description": "Envoie un message",
     "parameters": {"type": "object", "properties": {"to": {"type": "string"}, "text": {"type": "string"}}, "required": ["to", "text"]}}},
]
OUTILS = [
    dict(id="o01", prompt="Quelle est la meteo a Lyon ?", attendu={"name": "get_weather", "arguments": {"city": "Lyon"}}),
    dict(id="o02", prompt="Additionne 17 et 25.", attendu={"name": "add", "arguments": {"a": 17, "b": 25}}),
    dict(id="o03", prompt="Cherche le mot bienvenue dans les documents, 3 resultats au maximum.", attendu={"name": "search_docs", "arguments": {"query": "bienvenue", "limit": 3}}),
    dict(id="o04", prompt="Mets un minuteur de 12 minutes.", attendu={"name": "set_timer", "arguments": {"minutes": 12}}),
    dict(id="o05", prompt="Envoie a Paul le message : bonjour.", attendu={"name": "send_message", "arguments": {"to": "Paul", "text": "bonjour"}}),
    dict(id="o06", prompt="Donne-moi la meteo de Tokyo.", attendu={"name": "get_weather", "arguments": {"city": "Tokyo"}}),
    dict(id="o07", prompt="Combien font 100 plus 250 ? Utilise l'outil d'addition.", attendu={"name": "add", "arguments": {"a": 100, "b": 250}}),
    dict(id="o08", prompt="Programme un minuteur de 45 minutes.", attendu={"name": "set_timer", "arguments": {"minutes": 45}}),
    dict(id="o09", prompt="Cherche le mot facture dans les documents, 10 resultats au maximum.", attendu={"name": "search_docs", "arguments": {"query": "facture", "limit": 10}}),
    dict(id="o10", prompt="Envoie a Lea le message : reunion a 10h.", attendu={"name": "send_message", "arguments": {"to": "Lea", "text": "reunion a 10h"}}),
]

# --- vision : 8 images synthetiques (PIL), reponse exacte -----------------------------------------------------------
VISION = [
    dict(id="v01", kind="formes", forme="cercle", couleur="rouge", n=3, prompt="Combien de cercles rouges y a-t-il sur l'image ?", reponse="3"),
    dict(id="v02", kind="formes", forme="carre", couleur="bleu", n=5, prompt="Combien de carres bleus y a-t-il sur l'image ?", reponse="5"),
    dict(id="v03", kind="formes", forme="cercle", couleur="vert", n=7, prompt="Combien de cercles verts y a-t-il sur l'image ?", reponse="7"),
    dict(id="v04", kind="formes", forme="triangle", couleur="rouge", n=4, prompt="Combien de triangles rouges y a-t-il sur l'image ?", reponse="4"),
    dict(id="v05", kind="chiffres", texte="4827", prompt="Quel nombre est ecrit sur l'image ?", reponse="4827"),
    dict(id="v06", kind="chiffres", texte="1593", prompt="Quel nombre est ecrit sur l'image ?", reponse="1593"),
    dict(id="v07", kind="chiffres", texte="7306", prompt="Quel nombre est ecrit sur l'image ?", reponse="7306"),
    dict(id="v08", kind="chiffres", texte="25941", prompt="Quel nombre est ecrit sur l'image ?", reponse="25941"),
]
for _v in VISION:
    _v["prompt"] += " " + FORMAT_REPONSE
_COULEURS = {"rouge": (220, 30, 30), "bleu": (30, 60, 220), "vert": (30, 170, 60)}


def image_vision(item: dict) -> bytes:
    """PNG synthetique deterministe de l'item (PIL importe ici : le reste du module reste importable sans PIL)."""
    import io

    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (480, 240), (255, 255, 255))
    d = ImageDraw.Draw(img)
    if item["kind"] == "formes":
        c = _COULEURS[item["couleur"]]
        for i in range(item["n"]):                       # grille fixe : pas de recouvrement, pas de hasard
            x, y = 20 + (i % 4) * 110, 20 + (i // 4) * 110
            if item["forme"] == "cercle":
                d.ellipse([x, y, x + 80, y + 80], fill=c)
            elif item["forme"] == "carre":
                d.rectangle([x, y, x + 80, y + 80], fill=c)
            else:
                d.polygon([(x + 40, y), (x, y + 80), (x + 80, y + 80)], fill=c)
    else:
        try:
            police = ImageFont.load_default(size=96)
        except TypeError:                                # Pillow < 10.1 : police fixe minuscule
            police = ImageFont.load_default()
        d.text((20, 60), item["texte"], fill=(0, 0, 0), font=police)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# --- effort : 6 taches (2 par taille S, M, L), reponse exacte, 3 efforts x 3 repetitions par le lanceur -------------------
_E = [
    ("S", "Combien font 17 x 24 ?", "408"),
    ("S", "Combien de lettres compte le mot anticonstitutionnellement ?", "25"),
    ("M", "Un reservoir de 600 litres se vide a 25 litres par minute pendant 8 minutes, puis on y ajoute 150 litres. Combien de litres contient-il ?", "550"),
    ("M", "Quelle est la somme des carres des entiers de 1 a 10 ?", "385"),
    ("L", "Combien de paires d'entiers (a, b) avec 1 <= a < b <= 20 ont une somme multiple de 5 ?", "38"),
    ("L", "Combien d'entiers de 1 a 1000 sont divisibles par 3 ou par 5, mais pas par 15 ?", "401"),
]
EFFORT = [dict(id="e%d%s" % (i + 1, t), taille=t, prompt=q + " " + FORMAT_REPONSE, reponse=a) for i, (t, q, a) in enumerate(_E)]
