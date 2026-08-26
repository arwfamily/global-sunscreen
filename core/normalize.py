"""
Ingredient-name normalisation — the layer every cross-country comparison
depends on.

Two different problems, both fatal if ignored:

  1. Between countries the SAME molecule has different official names.
     Australia's register is pharmacopoeial (GLYCEROL, DL-ALPHA-TOCOPHERYL
     ACETATE, DISODIUM EDETATE, CETOSTEARYL ALCOHOL, CERAMIDE 3); the US and
     Korea print INCI (glycerin, tocopheryl acetate, disodium EDTA,
     cetearyl alcohol, ceramide NP). Counting them separately silently
     halves every shared-ingredient statistic.

  2. Within ONE country the same product's name can be re-typed between
     snapshots ("Water (Aqua)" -> "Water", "1,2-Hexanediol" -> "1,2
     hexanediol", a CI number appearing or disappearing). If that reaches
     the fingerprint it is logged as a reformulation that never happened.
     A false reformulation is worse than a missed one: it poisons the very
     time series the project exists to build.

So: normalise first, hash second. Everything here is conservative — it
folds spelling, punctuation and documented synonyms, and never guesses that
two differently-named ingredients are the same.
"""

import re
import unicodedata

# Documented equivalences only. Left side = what a register prints,
# right side = the canonical key we count under (INCI where one exists).
SYNONYMS = {
    # --- seen in the DailyMed corpus (13,285 SPLs) vs the other registers --
    "alpha-tocopherol acetate": "tocopheryl acetate",
    "alpha-tocopheryl acetate": "tocopheryl acetate",
    "tocopherols": "tocopherol",
    "alpha-tocopherol": "tocopherol",
    "polyhydroxystearic acid (2300 mw)": "polyhydroxystearic acid",
    "aloe vera leaf": "aloe barbadensis leaf",
    "aloe vera leaf juice": "aloe barbadensis leaf juice",
    "aloe vera whole": "aloe barbadensis leaf",
    "aloe": "aloe barbadensis leaf",
    "aloe vera": "aloe barbadensis leaf",
    "parfum/fragrance": "fragrance",
    "fragrance (perfume)": "fragrance",
    "parfum": "fragrance",
    "ferric oxide red": "iron oxides",
    "ferric oxide yellow": "iron oxides",
    "ferric oxide": "iron oxides",
    "ferrosoferric oxide": "iron oxides",
    "carbomer homopolymer": "carbomer",
    "carbomer homopolymer, unspecified type": "carbomer",
    "carbomer homopolymer type c": "carbomer",
    "lecithin, soybean": "lecithin",
    "soybean lecithin": "lecithin",
    "dimeticone": "dimethicone",
    "cetyl dimeticone": "cetyl dimethicone",
    # water
    "aqua": "water", "purified water": "water", "water (aqua)": "water",
    "aqua (water)": "water", "distilled water": "water",
    "water purified": "water",
    # AU pharmacopoeial / AAN -> INCI
    "glycerol": "glycerin", "glycerine": "glycerin",
    "dl-alpha-tocopheryl acetate": "tocopheryl acetate",
    "d-alpha-tocopheryl acetate": "tocopheryl acetate",
    "alpha-tocopheryl acetate": "tocopheryl acetate",
    "dl-alpha-tocopherol": "tocopherol",
    "d-alpha-tocopherol": "tocopherol",
    "disodium edetate": "disodium edta",
    "edetate disodium": "disodium edta",
    "tetrasodium edetate": "tetrasodium edta",
    "cetostearyl alcohol": "cetearyl alcohol",
    "cetyl stearyl alcohol": "cetearyl alcohol",
    "white soft paraffin": "petrolatum",
    "soft white paraffin": "petrolatum",
    "white beeswax": "beeswax", "yellow beeswax": "beeswax",
    "cera alba": "beeswax",
    "liquid paraffin": "mineral oil", "paraffin liquid": "mineral oil",
    "light liquid paraffin": "mineral oil",
    "isopropyl alcohol": "isopropyl alcohol",
    "ethanol": "alcohol", "alcohol denat": "alcohol denat",
    "sodium cetostearyl sulfate": "sodium cetearyl sulfate",
    "sodium cetostearyl sulphate": "sodium cetearyl sulfate",
    "propylene glycol": "propylene glycol",
    "medium chain triglycerides": "caprylic/capric triglyceride",
    "triglycerides medium chain": "caprylic/capric triglyceride",
    "hydroxybenzoate methyl": "methylparaben",
    "methyl hydroxybenzoate": "methylparaben",
    "propyl hydroxybenzoate": "propylparaben",
    "butylated hydroxytoluene": "bht",
    "butylated hydroxyanisole": "bha",
    "silicon dioxide": "silica", "colloidal anhydrous silica": "silica",
    "silica dimethyl silylate": "silica dimethyl silylate",
    "titanium dioxide": "titanium dioxide", "zinc oxide": "zinc oxide",
    # UV filters — INCI vs USAN vs AU AAN
    "butyl methoxydibenzoylmethane": "avobenzone",
    "octocrylene": "octocrylene",
    "octyl methoxycinnamate": "octinoxate",
    "ethylhexyl methoxycinnamate": "octinoxate",
    "octinoxate": "octinoxate",
    "octyl salicylate": "octisalate",
    "ethylhexyl salicylate": "octisalate",
    "2-ethylhexyl salicylate": "octisalate",
    "benzophenone-3": "oxybenzone",
    "oxybenzone": "oxybenzone",
    "benzophenone-4": "sulisobenzone",
    "phenylbenzimidazole sulfonic acid": "ensulizole",
    "ensulizole": "ensulizole",
    "homosalate": "homosalate",
    "bis-ethylhexyloxyphenol methoxyphenyl triazine": "bemotrizinol",
    "bemotrizinol": "bemotrizinol",
    "diethylamino hydroxybenzoyl hexyl benzoate": "dhhb",
    "methylene bis-benzotriazolyl tetramethylbutylphenol": "bisoctrizole",
    "ethylhexyl triazone": "ethylhexyl triazone",
    "diethylhexyl butamido triazone": "diethylhexyl butamido triazone",
    "drometrizole trisiloxane": "drometrizole trisiloxane",
    "terephthalylidene dicamphor sulfonic acid": "ecamsule",
    "4-methylbenzylidene camphor": "enzacamene",
    "isoamyl p-methoxycinnamate": "amiloxate",
    # ceramides: AU numeric names -> INCI letter names
    "ceramide 1": "ceramide eop", "ceramide 2": "ceramide ns",
    "ceramide 3": "ceramide np", "ceramide 6 ii": "ceramide ap",
    "ceramide 6ii": "ceramide ap",
}

# Korean label spellings -> INCI keys. Korean sunscreen labels print
# transliterated INCI, so this is transliteration, not translation. Seeded
# with what actually appears on baby-sunscreen labels; the full mapping is
# the KCIA standard-name list (kcia.or.kr/cid "표준화 명칭 목록"), which
# drops in here as data without changing any of this logic.
KO_INCI = {
    "징크옥사이드": "zinc oxide", "산화아연": "zinc oxide",
    "티타늄디옥사이드": "titanium dioxide", "이산화티타늄": "titanium dioxide",
    "트라이에톡시카프릴릴실레인": "triethoxycaprylylsilane",
    "트리에톡시카프릴릴실레인": "triethoxycaprylylsilane",
    "아이런옥사이드": "iron oxides", "적색산화철": "iron oxides",
    "다이실록세인": "disiloxane", "디실록세인": "disiloxane",
    "부틸옥틸살리실레이트": "butyloctyl salicylate",
    "폴리하이드록시스테아릭애씨드": "polyhydroxystearic acid",
    "다이소듐이디티에이": "disodium edta",
    "에틸헥실글리세린": "ethylhexylglycerin",
    "메틸트라이메티콘": "methyl trimethicone",
    "카프릴릴메티콘": "caprylyl methicone",
    "콜레스테롤": "cholesterol", "엑토인": "ectoin",
    "정제수": "water", "물": "water",
    "징크옥사이드": "zinc oxide", "티타늄디옥사이드": "titanium dioxide",
    "산화아연": "zinc oxide", "이산화티타늄": "titanium dioxide",
    "글리세린": "glycerin", "부틸렌글리콜": "butylene glycol",
    "프로판디올": "propanediol", "디프로필렌글리콜": "dipropylene glycol",
    "1,2-헥산디올": "1,2-hexanediol", "헥산디올": "1,2-hexanediol",
    "카프릴릭/카프릭트리글리세라이드": "caprylic/capric triglyceride",
    "디메티콘": "dimethicone", "사이클로펜타실록산": "cyclopentasiloxane",
    "메틸트리메티콘": "methyl trimethicone",
    "트리에톡시카프릴릴실란": "triethoxycaprylylsilane",
    "폴리하이드록시스테아릭애씨드": "polyhydroxystearic acid",
    "실리카": "silica", "토코페롤": "tocopherol",
    "토코페릴아세테이트": "tocopheryl acetate",
    "에틸헥실글리세린": "ethylhexylglycerin",
    "판테놀": "panthenol", "알란토인": "allantoin",
    "히알루론산": "hyaluronic acid",
    "소듐하이알루로네이트": "sodium hyaluronate",
    "부틸옥틸살리실레이트": "butyloctyl salicylate",
    "이소스테아릭애씨드": "isostearic acid",
    "세라마이드엔피": "ceramide np", "세라마이드엔에스": "ceramide ns",
    "세라마이드에이피": "ceramide ap", "세라마이드이오피": "ceramide eop",
    "콜레스테롤": "cholesterol", "베헤닉애씨드": "behenic acid",
    "락틱애씨드": "lactic acid", "엑토인": "ectoine",
    "페녹시에탄올": "phenoxyethanol", "향료": "fragrance",
    "잔탄검": "xanthan gum", "카보머": "carbomer",
    "시어버터": "butyrospermum parkii butter",
    "호호바오일": "simmondsia chinensis seed oil",
    "알로에베라잎추출물": "aloe barbadensis leaf extract",
    "마그네슘설페이트": "magnesium sulfate",
    "디스테아디모늄헥토라이트": "disteardimonium hectorite",
}

# Korean orthography folding (Korean labels print INCI transliterated, and
# the accepted spelling changed over time: 메칠 -> 메틸 etc.)
KO_FOLD = (("메칠", "메틸"), ("에칠", "에틸"), ("프로필렌글라이콜", "프로필렌글리콜"),
           ("다이", "디"), ("트라이", "트리"), ("아이소", "이소"),
           ("옥틸도데실", "옥틸도데실"), ("하이드록시", "히드록시"))

# FDA writes Greek letters as dotted tokens in SPL (".ALPHA.-TOCOPHEROL"),
# and appends stereochemistry after a comma (", DL-", ", D-"). Neither is a
# different substance from the INCI name every other register uses, so both
# are folded before matching — without this, tocopheryl acetate alone splits
# into six separate "ingredients" across the four countries.
# Colour Index numbers that appear in sunscreens. 77491/2/9 are the three
# iron oxides that make a tint; 77947 and 77891 are the two mineral filters
# under their pigment names.
# Words that appear in parentheses as a QUALIFIER, not as a common name.
# "Corn Oil (Unhydrogenated)" must not become "unhydrogenated oil".
_QUALIFIERS = {
    "unhydrogenated", "hydrogenated", "extract", "powder", "solution",
    "anhydrous", "aqueous", "organic", "natural", "nano", "coated",
    "usp", "bp", "ep", "nf", "and", "as", "food grade", "cosmetic grade",
    "fermented", "unrefined", "refined", "cold pressed", "dried",
}
# Latin binomial followed by the common name in brackets — the INCI habit
# that every register writes differently:
#     Persea americana (Avocado) oil   |   avocado oil
#     Lavandula angustifolia (Lavender) oil   |   lavender oil
# Both are the same substance, so both must fingerprint the same. We keep
# the COMMON name because that is the shorter form registers fall back to
# when they abbreviate. Measured on our own data: 171 pairs collapse.
_BINOMIAL_PAREN = re.compile(r"^([a-z]+(?:\s+[a-z.]+){1,3})\s*\(([^)]+)\)\s*(.*)$", re.I)

CI_PIGMENTS = {"77491": "iron oxides", "77492": "iron oxides",
               "77499": "iron oxides", "77947": "zinc oxide",
               "77891": "titanium dioxide", "77007": "ultramarines"}

_FDA_GREEK = re.compile(r"\.(alpha|beta|gamma|delta|epsilon|omega)\.", re.I)
_FDA_STEREO = re.compile(r",\s*\(?(?:dl|d|l|\+/-|\+|-)\)?-?\s*$", re.I)
_CI = re.compile(r"\(?\s*c\.?i\.?\s*\d{5}\s*\)?", re.I)     # (CI 77947), C.I. 77491
_INS = re.compile(r"\(?\s*e\s?\d{3}[a-z]?\s*\)?", re.I)     # (E171)
_PAREN_QUAL = re.compile(
    r"\((?:aqua|water|eau|and|or|as|from|inci|usp|bp|ep|nf|ph\.?\s?eur\.?)"
    r"[^)]*\)", re.I)
_QTY = re.compile(r"\b\d[\d.,]*\s*(?:mg/g|mg|g|%|ppm|w/w|v/v|iu)(?![\w])", re.I)
_MULTISPACE = re.compile(r"\s+")


def normalize_name(raw):
    """Return the canonical counting key for one ingredient name.

    Idempotent: normalize_name(normalize_name(x)) == normalize_name(x).
    Returns "" for anything that is not an ingredient name.
    """
    if raw is None:
        return ""
    s = unicodedata.normalize("NFKC", str(raw)).strip()
    if not s:
        return ""
    for a, b in KO_FOLD:
        s = s.replace(a, b)
    s = s.lower()
    s = _FDA_GREEK.sub(r"\1 ", s)
    s = _FDA_STEREO.sub("", s)
    # A bare Colour Index number IS the ingredient on Korean and European
    # labels ("CI 77492"), while on a US label it is an annotation after the
    # name. Resolve the bare form before stripping the annotation, or the
    # pigment vanishes from the record entirely.
    m = _BINOMIAL_PAREN.match(s)
    if m:
        inner = m.group(2).strip().lower()
        if inner in _QUALIFIERS:
            s = f"{m.group(1)} {m.group(3)}".strip()      # drop the qualifier
        elif len(m.group(1).split()) >= 2:
            s = f"{inner} {m.group(3)}".strip()           # keep the common name
    bare = _CI.fullmatch(s.strip())
    if bare:
        code = re.sub(r"\D", "", s)
        return CI_PIGMENTS.get(code, f"ci {code}")
    s = _CI.sub(" ", s)
    s = _INS.sub(" ", s)
    s = _PAREN_QUAL.sub(" ", s)
    s = _QTY.sub(" ", s)
    s = s.replace("’", "'").replace("–", "-").replace("—", "-")
    s = s.replace("&", " and ")
    # collapse punctuation used inconsistently between registers
    s = re.sub(r"[\[\]{}\"'*†‡]", " ", s)
    s = re.sub(r"\s*-\s*", "-", s)
    s = re.sub(r"\s*,\s*(?=[a-z가-힣])", ", ", s)   # not "1,2-hexanediol"
    s = re.sub(r"\s*,\s*(?=\d)", ",", s)
    s = s.strip(" .;:,-")
    s = _MULTISPACE.sub(" ", s).strip()
    # trailing qualifiers that carry no compositional meaning
    s = re.sub(r"\b(usp|nf|bp|ep|jp|fcc|food grade|powder|solution|"
               r"anhydrous|dried|purified)\b$", "", s).strip(" .,-")
    s = _MULTISPACE.sub(" ", s).strip()
    if s in KO_INCI:
        return KO_INCI[s]
    return SYNONYMS.get(s, s)


def normalize_list(names):
    """Normalise a list, dropping empties but PRESERVING ORDER and repeats.

    Order is kept because in some jurisdictions (US, KR) the printed order
    is the concentration order and is therefore data. Callers that know
    their source is alphabetical must sort/setify themselves — see
    core.fingerprint.
    """
    out = []
    for n in names or []:
        k = normalize_name(n)
        if k:
            out.append(k)
    return out
