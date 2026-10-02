"""Porter token contract shared with the static reader's stemmer 2.x."""
import re
import unicodedata
from collections import Counter
from functools import lru_cache

CONSONANTS = r"([^aeiou][^aeiouy]*)"
VOWELS = r"([aeiouy][aeiou]*)"
GT0 = re.compile("^" + CONSONANTS + "?" + VOWELS + CONSONANTS)
EQ1 = re.compile("^" + CONSONANTS + "?" + VOWELS + CONSONANTS + VOWELS + "?$")
GT1 = re.compile("^" + CONSONANTS + "?(" + VOWELS + CONSONANTS + "){2,}")
VOWEL_IN_STEM = re.compile("^" + CONSONANTS + "?[aeiouy]")
CVC = re.compile("^" + CONSONANTS + "[aeiouy][^aeiouwxy]$")
STEP2 = dict(zip(
    "ational tional enci anci izer bli alli entli eli ousli ization ation ator alism iveness fulness ousness aliti iviti biliti logi".split(),
    "ate tion ence ance ize ble al ent e ous ize ate ate al ive ful ous al ive ble log".split(), strict=True))
STEP3 = {"icate": "ic", "ative": "", "alize": "al", "iciti": "ic", "ical": "ic", "ful": "", "ness": ""}


@lru_cache(maxsize=100000)
def stemmer(value):
    result = value.lower()
    if len(result) < 3:
        return result
    initial_y = result.startswith("y")
    if initial_y:
        result = "Y" + result[1:]
    if re.search(r"^.+?(ss|i)es$", result):
        result = result[:-2]
    elif re.search(r"^.+?[^s]s$", result):
        result = result[:-1]
    match = re.search(r"^(.+?)eed$", result)
    if match:
        if GT0.search(match[1]):
            result = result[:-1]
    else:
        match = re.search(r"^(.+?)(ed|ing)$", result)
        if match and VOWEL_IN_STEM.search(match[1]):
            result = match[1]
            if re.search(r"(at|bl|iz)$", result):
                result += "e"
            elif re.search(r"([^aeiouylsz])\1$", result):
                result = result[:-1]
            elif CVC.search(result):
                result += "e"
    match = re.search(r"^(.+?)y$", result)
    if match and VOWEL_IN_STEM.search(match[1]):
        result = match[1] + "i"
    for replacements in (STEP2, STEP3):
        match = re.search(r"^(.+?)(" + "|".join(replacements) + r")$", result)
        if match and GT0.search(match[1]):
            result = match[1] + replacements[match[2]]
    match = re.search(r"^(.+?)(al|ance|ence|er|ic|able|ible|ant|ement|ment|ent|ou|ism|ate|iti|ous|ive|ize)$", result)
    if not match:
        match = re.search(r"^(.+?(s|t))(ion)$", result)
    if match and GT1.search(match[1]):
        result = match[1]
    match = re.search(r"^(.+?)e$", result)
    if match and (GT1.search(match[1]) or (EQ1.search(match[1]) and not CVC.search(match[1]))):
        result = match[1]
    if result.endswith("ll") and GT1.search(result):
        result = result[:-1]
    return "y" + result[1:] if initial_y else result


def normalized_title(value):
    text = "".join(char for char in unicodedata.normalize("NFKD", value) if not unicodedata.category(char).startswith("M"))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def search_terms(paper):
    text = unicodedata.normalize("NFD", paper["title"] + " " + (paper.get("abstract") or ""))
    text = "".join(char for char in text if not unicodedata.category(char).startswith("M")).lower()
    text = "".join(char if unicodedata.category(char)[0] in "LN" else " " for char in text)
    terms = text.split()
    frequency = Counter(stemmer(term) if re.fullmatch(r"[a-z0-9]+", term) else term for term in terms)
    for token in re.findall(r"[a-z0-9]+", normalized_title(paper["title"])):
        frequency[stemmer(token)] += 7
    return frequency, len(terms)
