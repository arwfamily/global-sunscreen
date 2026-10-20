# Copied from arwfamily/tinysafe-dailymed-scraper-v2 scripts/scope_rules.py (2026-10-20) so every
# jurisdiction uses the same SPF-makeup / lip / diaper scope as the US release. Keep in sync.
#!/usr/bin/env python3
"""Scope rules on top of the classifier: which DailyMed sunscreen-drug labels are
SPF makeup, lip products, skin protectants or not sunscreens at all.

Angela's decision (2026-10-19): the US database is sunscreens; SPF makeup and SPF
lip products are left out, with the reason recorded. Every rule reads the PRODUCT
part of the title only (the [LABELER] bracket and the bracketed active list are
removed: "THE LIP BAR" is a labeler, not a lip product).

  spf_makeup     complexion / eye / lip-colour makeup: BB, CC, foundation, cushion,
                 concealer, compact/pact, pressed or face powder, blush, bronzer,
                 highlighter, primer, setting spray/powder, eyeshadow, mascara, makeup.
                 Kept as sunscreen when the name itself calls the product a sunscreen
                 ("Sunscreen + Primer", "Setting Sunscreen", "Sun Cushion"); the FDA
                 identity line "Broad Spectrum SPF 30 Sunscreen" does not count,
                 every label must print it. Tinted sunscreens and tinted
                 moisturizers are sunscreens.
  spf_lip_balm   lip balm, lip gloss, lip oil, chapstick and other lip products
  diaper_cream   diaper / rash creams
  not_a_sunscreen  acne, nasal, wound products whose actives are not UV filters
                 used for sun protection (decided by the classifier; here only
                 recorded)
"""
import re

_LABELER = re.compile(r"\s*\[[^\]]*\]\s*$")
_ACTS = re.compile(r"\((?:[^()]|\([^()]*\))*\)")
# the FDA statement of identity every sunscreen label prints
_IDENTITY = re.compile(r"\bBROAD[- ]?SPECTRUM\b(?:\s*SPF\s*\d+\s*\+?(?:\s*PLUS)?)?(?:\s*SUN\s?SCREEN)?|"
                       r"\bSPF\s*\d+\s*\+?\s*SUN\s?SCREEN\b|\bSUN\s?SCREEN\s+SPF\s*\d+\b", re.I)
SUN_FIRST = re.compile(r"\bBRUSH[- ]?ON (?:BLOCK|SUN\w*)\b|\bSUN\s?SCREENS?\b|\bSUNCREEN\b|\bSUN\s?BLOCKS?\b|\bSUN\s?(?:CUSHION|STICK|POWDER|"
                       r"DEFEN[CS]E|PROTECT\w*|SHIELD|CARE|MILK|SERUM|FLUID|GEL|ESSENCE|SPRAY|MIST|PACT|COMPACT)\b|\bUV\s?"
                       r"(?:SHIELD|DEFEN[CS]E|PROTECT\w*|BLOCK|SCREEN|EXPERT|AQUA|CUSHION|POWDER)\b", re.I)
# coverage makeup: a sunscreen word on the label does not change what it is
MAKEUP_STRONG = re.compile(r"\b(?:FOUNDATIONS?|FOND DE TEINT|BB|CC|B\.B\.|C\.C\.|BB\s?CR[EÈ]ME|CC\s?CR[EÈ]ME|BBCREAM|CCCREAM|"
                           r"CONCEAL\w*|TWO[- ]WAY CAKE|BLUSH(?:ER)?|BRONZ(?:ER|ING POWDER)|"
                           r"HIGHLIGHT(?:ER|ING)|EYE\s?SHADOWS?|MASCARA|LIPSTICKS?|LIP\s?COLOU?RS?|LIP\s?TINTS?|"
                           r"LIP\s?STAIN|MAKE[- ]?UP|MAQUILLAJE|PRESSED POWDER|FACE POWDER|LOOSE POWDER|"
                           r"POWDER FOUNDATION|DUAL POWDER|(?:TRIPLE |EYE ?)SHADOWS?|FACE MAKER|COVER CAKE|POLVO|"
                           r"COMPACTO|PRESSED MINERAL|MATCH PERFECTION|FAUX TAN)\b", re.I)
# a powder sold in skin shades is a makeup powder ("SPF 15 FAIR POWDER")
SHADE_POWDER = re.compile(r"\b(?:FAIR|LIGHT|MEDIUM|TAN|DEEP|DARK|IVORY|BEIGE|NUDE|SAND|PORCELAIN|HONEY|"
                          r"CARAMEL|ESPRESSO|BISQUE|BUFF)\b.*\bPOWDER\b", re.I)
# a name that calls itself a tinted moisturizer / tinted sunscreen is a sunscreen, BB or not
TINTED_SELF = re.compile(r"\bTINTED\s+(?:MOISTURI[SZ]\w*|SUN\s?SCREEN|MINERAL SUN\s?SCREEN)", re.I)
# formats that are makeup unless the product noun is a sunscreen one ("Sun Cushion", "Sunscreen Compact")
MAKEUP_FORMAT = re.compile(r"\b(?:CUSHIONS?|COMPACTS?|PACTS?)\b", re.I)
# ...unless the product noun itself is a sunscreen one ("Sun Cushion", "Sunscreen Compact")
SUN_NOUN = re.compile(r"\b(?:SUN|SUNSCREEN|SUNBLOCK|UV)\s?(?:CUSHION|COMPACT|PACT|POWDER|STICK)\b", re.I)
# makeup steps that come as sunscreens too: kept when the name calls the product a sunscreen
MAKEUP_WEAK = re.compile(r"\b(?:PRIMERS?|SETTING|FINISHING POWDER|BLUR(?:RING)?\s+(?:PRIMER|BALM))\b", re.I)
MAKEUP = re.compile(MAKEUP_STRONG.pattern + "|" + MAKEUP_FORMAT.pattern + "|" + MAKEUP_WEAK.pattern, re.I)
LIP = re.compile(r"\bLIPS?\b|\bLIP\s?(?:BALM|BUTTER|CARE|GLOSS|OIL|SHIELD|PROTECT\w*|CONDITION\w*|TREATMENT|"
                 r"SCREEN|SERUM|SLEEP\w*|MASK|STICK|SUN|SPF|REFINER|PLUMP\w*|REPAIR)\b|CHAPSTICK|SOFTLIPS|"
                 r"\bNATURAL ICE\b|\bCARMEX\b|\bBLISTEX\b|\bLIP\w*BALM", re.I)
# lip words inside a face/body product's name ("Face & Lip Stick" stays a face product)
NOT_ONLY_LIP = re.compile(r"\bFACE\b(?!\s+(?:LIP|&\s*LIP))|\bBODY\b|\bSPORT STICK\b", re.I)
BRAND_WORDS = re.compile(r"\bKISS MY FACE\b|\bTHE FACE ?SHOP\b|\bFACE IT\b|\bBODY SHOP\b|\bBATH (?:AND|&) BODY WORKS\b", re.I)
DIAPER = re.compile(r"\bDIAPER\b|\bRASH\b", re.I)


def product_part(title):
    t = _LABELER.sub("", title or "")
    t = _ACTS.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def scope_reason(title):
    """None if the product is a sunscreen, else the reason it is out of scope."""
    p = product_part(title)
    q = BRAND_WORDS.sub(" ", p)
    if DIAPER.search(q) and not SUN_FIRST.search(_IDENTITY.sub(" ", q)):
        return "diaper_cream"
    if LIP.search(q) and not NOT_ONLY_LIP.search(q):
        return "spf_lip_balm"
    if TINTED_SELF.search(q):
        return None
    if MAKEUP_STRONG.search(q):
        return "spf_makeup"
    if SHADE_POWDER.search(q) and not SUN_FIRST.search(_IDENTITY.sub(" ", q)):
        return "spf_makeup"
    if MAKEUP_FORMAT.search(q) and not SUN_NOUN.search(q):
        return "spf_makeup"
    if MAKEUP_WEAK.search(q) and not SUN_FIRST.search(_IDENTITY.sub(" ", q)):
        return "spf_makeup"
    return None


def named_sunscreen(title):
    """The product name itself calls it a sunscreen (beyond the FDA identity line)."""
    return bool(SUN_FIRST.search(_IDENTITY.sub(" ", BRAND_WORDS.sub(" ", product_part(title)))))
