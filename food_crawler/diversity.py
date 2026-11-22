"""Rozpoznávanie druhov jedál podľa názvu a obmedzenie ich počtu."""

import re
import unicodedata
from collections import Counter

from scrapy.exceptions import IgnoreRequest

FAMILY_RULES = [
    ("pancakes", r"\bpancakes?\b|\bpannekoeken\b|\bpfannkuchen\b"),
    ("crepes", r"\bcrepes?\b"),
    ("waffles", r"\bwaffles?\b"),
    ("cookies", r"\bcookies?\b|\bsnickerdoodles?\b|\bbiscotti\b"),
    (
        "macaroni_and_cheese",
        r"\b(?:macaroni|mac)\b.*\bchees(?:e|es|y)\b|\bchees(?:e|es|y)\b.*\bmacaroni\b",
    ),
    ("spaghetti", r"\bspaghetti\b"),
    ("lasagna", r"\blasagn[ae]\b"),
    ("pizza", r"\bpizzas?\b"),
    ("risotto", r"\brisotto\b"),
    ("gnocchi", r"\bgnocchi\b"),
    ("curry", r"\bcurr(?:y|ies)\b|\btikka\b.*\bmasala\b|\bkorma\b"),
    ("stir_fry", r"\bstir fry\b|\bstir fried\b"),
    ("pad_thai", r"\bpad thai\b"),
    ("sushi", r"\bsushi\b"),
    ("dumplings", r"\bdumplings?\b|\bgyoza\b|\bpot ?stickers?\b"),
    ("spring_rolls", r"\bspring rolls?\b|\begg rolls?\b"),
    ("tacos", r"\btacos?\b"),
    ("enchiladas", r"\benchiladas?\b"),
    ("burritos", r"\bburritos?\b|\bchimichangas?\b"),
    ("quesadillas", r"\bquesadillas?\b"),
    ("fajitas", r"\bfajitas?\b"),
    ("meatloaf", r"\bmeat ?loaf\b"),
    ("meatballs", r"\bmeatballs?\b"),
    ("burgers", r"\bburgers?\b|\bhamburgers?\b"),
    ("chili", r"\bchili\b|\bchilli\b"),
    ("soup", r"\bsoups?\b|\bchowder\b|\bbisque\b|\bpozole\b|\bramen\b"),
    ("stew", r"\bstew\b|\bgoulash\b|\bbourguignon\b"),
    ("ribs", r"\bribs?\b"),
    ("steak", r"\bsteaks?\b"),
    ("pot_roast", r"\bpot roast\b|\broast beef\b|\bbeef roast\b"),
    ("pulled_pork", r"\bpulled pork\b|\bcarnitas\b"),
    ("roast_chicken", r"\broast(?:ed)? chicken\b"),
    ("chicken_wings", r"\b(?:chicken|buffalo) wings?\b"),
    ("fried_chicken", r"\bfried chicken\b"),
    ("quiche", r"\bquiches?\b"),
    ("omelet", r"\bomelett?es?\b|\bfrittatas?\b"),
    ("hummus", r"\bhummus\b"),
    ("falafel", r"\bfalafel\b"),
    ("guacamole", r"\bguacamole\b"),
    ("salsa", r"\bsalsa\b|\bpico de gallo\b"),
    ("salad", r"\bsalads?\b|\bcoleslaw\b|\btabbouleh\b"),
    ("sandwich", r"\bsandwich(?:es)?\b|\bpanini\b|\bgrilled cheese\b"),
    ("casserole", r"\bcasseroles?\b|\bstrata\b"),
    ("mashed_potatoes", r"\bmashed potatoes\b"),
    ("potato_gratin", r"\bscalloped potatoes\b|\bpotato.*gratin\b"),
    ("fries", r"\bfries\b|\bpotato wedges\b"),
    ("baked_potato", r"\bbaked potato\b|\broasted potatoes\b"),
    ("rice_dishes", r"\brice\b|\bpaella\b|\bjambalaya\b|\bbiryani\b"),
    ("banana_bread", r"\bbanana.*\bbread\b|\bbanana.*\bloaf\b"),
    ("muffins", r"\bmuffins?\b"),
    ("scones", r"\bscones?\b"),
    ("bread_rolls", r"\bbuns?\b|\brolls?\b"),
    ("bread", r"\bbread\b|\bfocaccia\b|\bbaguette\b|\bnaan\b"),
    ("brownies", r"\bbrownies?\b|\bblondies?\b"),
    ("apple_pie", r"\bapple.*\bpies?\b"),
    ("cheesecake", r"\bcheesecakes?\b"),
    ("carrot_cake", r"\bcarrot cakes?\b"),
    ("chocolate_cake", r"\bchocolate cakes?\b"),
    ("cake", r"\bcakes?\b|\bcupcakes?\b"),
    ("pie", r"\bpies?\b|\btarts?\b"),
    ("pudding", r"\bpuddings?\b|\bcustard\b|\bcreme brulee\b"),
    ("ice_cream", r"\bice cream\b|\bsorbet\b|\bgelato\b"),
    ("smoothies", r"\bsmoothies?\b|\bmilkshakes?\b"),
    (
        "pasta",
        r"\bpasta\b|\bpenne\b|\bfettuccine\b|\bravioli\b|\btortellini\b|\bnoodles?\b",
    ),
]
# Pri viacerých zhodách rozhoduje poradie pravidiel.
FAMILY_RULES.extend(
    [
        ("french_toast", r"\bfrench toast\b"),
        ("overnight_oats", r"\bovernight oats\b"),
        ("oatmeal", r"\boatmeal\b"),
        ("granola", r"\bgranola\b"),
        ("biscuits", r"\bbiscuits?\b"),
        ("cornbread", r"\bcornbread\b"),
        ("challah", r"\bchallah\b"),
        ("brioche", r"\bbrioche\b"),
        ("pretzels", r"\bpretzels?\b"),
        ("sourdough_starter", r"\bsourdough starter\b"),
        ("donuts", r"\bdo(?:ugh)?nuts?\b|\bsufganiy?ot\b|\brosquillas\b"),
        ("macarons", r"\bmacarons?\b"),
        ("macaroons", r"\bmacaroons?\b"),
        ("churros", r"\bchurros?\b"),
        ("tiramisu", r"\btiramisu\b"),
        ("baklava", r"\bbaklava\b"),
        ("flan", r"\bflan\b|\bcrema catalana\b"),
        ("panna_cotta", r"\bpanna cotta\b"),
        ("mousse", r"\bmousse\b"),
        ("trifle", r"\btrifle\b"),
        (
            "fruit_crisp",
            r"\bcrisp\b.*\b(?:apple|pear|rhubarb)\b|\b(?:apple|pear|rhubarb)\b.*\bcrisp\b",
        ),
        ("strudel", r"\bstrudels?\b"),
        ("eclairs", r"\beclairs?\b|\bcream puffs?\b"),
        ("madeleines", r"\bmadeleines?\b"),
        ("rugelach", r"\brugelach\b"),
        ("babka", r"\bbabka\b"),
        ("panettone", r"\bpanettone\b"),
        ("fudge", r"\bfudge\b|\bbarfi\b|\bburfi\b"),
        ("gulab_jamun", r"\bgulab jamun\b"),
        ("rasgulla", r"\brasgulla\b"),
        ("halwa", r"\bhal[wv]a\b"),
        ("ladoo", r"\bladd?oo\b"),
        ("jalebi", r"\bjalebis?\b"),
        ("latkes", r"\blatkes?\b"),
        ("onion_bhaji", r"\bonion\b.*\bbhaji\b|\bbhaji\b.*\bonion\b"),
        ("samosas", r"\bsamosas?\b"),
        ("pakoras", r"\bpakoras?\b"),
        ("idli", r"\bidli\b"),
        ("dosa", r"\bdosa\b"),
        ("appam", r"\bappams?\b"),
        ("pani_puri", r"\bpani puri\b"),
        ("puran_poli", r"\bpuran poli\b"),
        ("empanadas", r"\bempanadas?\b"),
        ("tamales", r"\btamales?\b"),
        ("chilaquiles", r"\bchilaquiles\b"),
        ("bruschetta", r"\bbruschetta\b"),
        ("caponata", r"\bcaponata\b"),
        ("ratatouille", r"\bratatouille\b"),
        ("panzanella", r"\bpanzanella\b"),
        ("caprese", r"\bcaprese\b"),
        ("gazpacho", r"\bgazpacho\b"),
        ("minestrone", r"\bminestrone\b"),
        ("bouillabaisse", r"\bbouillabaisse\b"),
        ("gumbo", r"\bgumbo\b"),
        ("grits", r"\bgrits\b"),
        ("polenta", r"\bpolenta\b"),
        ("couscous", r"\bcouscous\b"),
        ("quinoa", r"\bquinoa\b"),
        ("lo_mein", r"\blo mein\b|\bchow mein\b"),
        ("udon", r"\budon\b"),
        ("soba", r"\bsoba\b"),
        ("wontons", r"\bwontons?\b"),
        ("kimchi", r"\bkimch[ie]+\b"),
        ("bulgogi", r"\bbulgogi\b"),
        ("gyudon", r"\bgyudon\b"),
        ("onigiri", r"\bonigiri\b"),
        ("okonomiyaki", r"\bokonomiyaki\b"),
        ("tonkatsu", r"\btonkatsu\b"),
        ("yakitori", r"\byakitori\b"),
        ("satay", r"\bsatay\b"),
        ("tom_kha", r"\btom kha\b"),
        ("vindaloo", r"\bvindaloo\b"),
        ("butter_chicken", r"\bbutter chicken\b|\bchicken makhani\b"),
        ("tandoori_chicken", r"\btandoori\b.*\bchicken\b|\bchicken\b.*\btandoori\b"),
        ("paneer", r"\bpaneer\b"),
        ("aloo_gobi", r"\baloo gobi\b"),
        ("refried_beans", r"\brefried beans\b"),
        ("baked_beans", r"\bbaked beans\b"),
        ("deviled_eggs", r"\bdevil[le]*d eggs\b"),
        ("poached_eggs", r"\bpoached eggs\b"),
        ("shakshuka", r"\bshaksh?ou?ka\b|\bshakshuka\b"),
        ("stuffed_peppers", r"\bstuffed\b.*\bpeppers\b"),
        ("stuffed_zucchini", r"\bstuffed zucchini\b"),
        ("zucchini_fritters", r"\bzucchini fritters\b"),
        ("zucchini_gratin", r"\bzucchini\b.*\bgratin\b"),
        ("osso_buco", r"\bosso buco\b"),
        ("coq_au_vin", r"\bcoq au vin\b"),
        ("beef_stroganoff", r"\bstroganoff\b"),
        ("chicken_parmesan", r"\bchicken\b.*\b(?:parmesan|parmigiana)\b"),
        ("chicken_cordon_bleu", r"\bchicken cordon bleu\b"),
        ("sloppy_joes", r"\bsloppy joes?\b"),
        ("popcorn", r"\bpopcorn\b"),
        (
            "chutney",
            r"\b(?:tomato|mango|mint|coconut|cilantro|coriander|onion|tamarind|green|red|apple|peach|cranberry) chutney\b",
        ),
        ("raita", r"\braita\b"),
        ("pesto", r"\bpesto\b"),
        ("hot_sauce", r"\bhot sauce\b"),
        ("alfredo_sauce", r"\balfredo sauce\b"),
        ("latte", r"\blatte\b"),
        ("lassi", r"\blassi\b"),
        ("falooda", r"\bfalooda\b"),
        ("horchata", r"\bhorchata\b"),
        ("lemonade", r"\blemonade\b"),
        ("agua_fresca", r"\bagua fresca\b|\bagua de tamarindo\b"),
        ("margarita", r"\bmargaritas?\b"),
        ("hot_chocolate", r"\bhot chocolate\b"),
        ("masala_chai", r"\bmasala chai\b|\bchai tea\b"),
        ("pork_chops", r"\bpork chops?\b"),
        ("hot_dogs", r"\bhot dogs?\b"),
    ]
)
COMPILED_RULES = [(name, re.compile(pattern)) for name, pattern in FAMILY_RULES]
FLUFF = set(
    "best easy quick homemade classic traditional favorite favourite delicious ultimate perfect simple great amazing healthy low fat free recipe recipes the a an and or with for of in my our your worlds world grandma grandmas mom moms copycat style super very really ever optional".split()
)


class DiversitySkip(IgnoreRequest):
    """Preskočenie receptu kvôli kvóte."""


def dish_family(title):
    """Prvé zhodné pravidlo určí druh jedla; inak vznikne kľúč z názvu."""
    normalized = re.sub(r"[-_/]+", " ", unicodedata.normalize("NFKC", title).casefold())
    for name, pattern in COMPILED_RULES:
        if pattern.search(normalized):
            return name, True
    meaningful_words = set()
    for word in re.findall(r"[a-z]+", normalized):
        if word not in FLUFF:
            meaningful_words.add(word)
    words = sorted(meaningful_words)
    return "unclassified:" + "_".join(words[:10] or ["unnamed"]), False


class FamilyQuota:
    """Počíta unikátne recepty v rodinách, nie iba recepty aktuálnej dávky."""

    def __init__(self, maximum=20, enabled=True):
        if maximum < 1:
            raise ValueError("Family quota must be positive")
        self.maximum, self.enabled = maximum, enabled
        self.counts, self.ids = Counter(), set()

    def register(self, recipe_id, title):
        family, known = dish_family(title)
        if str(recipe_id) not in self.ids:
            self.ids.add(str(recipe_id))
            self.counts[family] += 1
        return family, known

    def permits(self, title):
        family, _ = dish_family(title)
        return not self.enabled or self.counts[family] < self.maximum
