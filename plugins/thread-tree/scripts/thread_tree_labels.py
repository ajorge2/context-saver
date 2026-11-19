"""Small, deterministic topic labels extracted from the complete cluster.

The fit's background is counted once. Each cluster then discounts phrases that
occur throughout that background, without embedding or language-model calls.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


# Discourse, function words, generated-summary scaffolding and language syntax
# are boundaries rather than candidate title words. Domain terms stay extractive.
_STOP = frozenset("""
a about above after again against all also am an and any are arent as at be because
been before being below between both but by can cant cannot could couldnt did
didnt do does doesnt doing dont down during each few for from further had hadnt
has hasnt have havent having he her here hers herself him himself his how i if
im in into is isnt it its itself ive just lets me more most my myself neither no
nor not of off on once only or other our ours ourselves out over own same she
should shouldnt so some such than that thats the their theirs them themselves
then there these they this those through to too under until up us very was wasnt
we were werent what whats when where which while who whom why will with wont
would wouldnt you your yours yourself yourselves
please thanks thank sure okay yes hello hi need needs needed want wants wanted
help tell explain show give get got make made use uses used using add added
change changes changed update updated fix fixed implement implemented let now
improve improves improved improving implementation details
reduce reduces reduced prevent prevents support supports provide provides
ensure ensures handle handles allow allows enable enables keep keeps
next done work works working project projects message messages conversation
conversations example examples thing things really well good better best
actually basically simply already also still much many new current following
topic topics include includes including covers cover discussion discussions
user assistant system developer tool
const var function def return self import class true false null none await async
print console log string int bool elif else try except finally pass lambda
""".split())
# These words describe the exchange, the speaker's instructions or a vague
# judgment. Repetition alone does not turn them into a useful subject name.
_DISCOURSE = frozenset("""
alright certainly understood agreed roger carry proceed continue continued
continuing begin started start stop stopped finish finished leave put set take
took bring send sent ask asked asking say said says mean means meant think
thought know knew known feel feels felt seem seems seemed appear appears
appeared look looks looked looking see seen saw watch watched find found check
checked checking confirm confirmed mention mentioned mentioning describe
described discuss discussed searched happen happens happened happening
awaits waiting waits goes went coming comes came exists exist contain contains
defined define defines stated states remain remains remained reading read
explicitly precisely clearly obviously probably possibly perhaps mostly
approximately entirely completely immediately eventually currently previously
otherwise therefore however indeed instead either anyway somehow somewhere
fine available obvious reasonable correct incorrect ready certain apparent
explicit relevant particular respective remaining previous subsequent last
different another earlier later nice great excellent perfect interesting useful
necessary unnecessary helpful appropriate suitable possible impossible sufficient
insufficient accurate inaccurate right wrong faster slower sooner later briefly
arrive arrives arrived arriving coming going proceed proceeding permits performs
returns accepts produces shows lists indicates suggests establishes raises matches
creates explains identifies follows belongs depends occurs
determine determines determined determining
makes takes seems similar plausible implausible clear whatever whichever whenever
wherever whether unless rather quite somewhat
decide decides decided deciding
""".split())
_VAGUE = frozenset("""
attention overview hindsight bit bits part parts case cases step steps item items
point points aspect aspects matter matters situation situations someone somebody
anything something everything nothing stuff fact facts way ways lot lots kind
kinds sort sorts extent instance instances possibility possibilities rest
""".split())
_GENERIC_SINGLETON = frozenset("""
request requests response responses code review query queries data result results
process processes task tasks context contexts plan plans file files mode modes
value values word words name names title titles branch branches list lists count
counts line lines page pages number numbers status version versions output outputs
input inputs question questions answer answers option options draft drafts
approval approvals pr wip todo tbd fyi eta information note notes text texts
approach approaches strategy strategies service services
outcome outcomes section sections sense enough
technical
""".split()) | _VAGUE
_PAST_MODIFIERS = frozenset("""
distributed shared managed nested scheduled cached signed encrypted grounded
structured automated bounded balanced normalized connected clustered weighted
ranked typed compiled isolated serialized authenticated authorized embedded
red
""".split())
_NOUN_ENDINGS = frozenset("family supply reply assembly ally anomaly bed seed feed speed".split())
_ADVERB_HEADS = frozenset("soon enough again away back forward backward ahead aside together apart nearby".split())
_VERB_HEADS = frozenset("write writes wrote execute executes instruct instructs describe describes mention mentions".split())
_ROLE = re.compile(r"(?im)^\s*(?:user|assistant|system|developer|tool)\s*:\s*")
_REQUEST = re.compile(
    r"(?im)^\s*(?:please\s+)?(?:review|show me|tell me about|help me with|inspect"
    r"|investigate|analyze|evaluate|verify|validate|compare|consider|identify"
    r"|summarize|describe|explain|list|show|check|confirm|mention|run|running"
    r"|write|read|build|pick|search for|look at|look into|take a look at)\s+"
)
_FENCE = re.compile(r"```[^\n]*\n.*?(?:```|\Z)", re.S)
_URL_PATH = re.compile(r"https?://\S+|(?:[\w.-]+/){2,}[\w./-]*|\b[0-9a-f]{16,}\b", re.I)
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_IDENTIFIER = re.compile(r"\b[a-z][a-zA-Z]*[A-Z][a-zA-Z]*\b")
_TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)
_BOUNDARY = re.compile(r"[\n.!?;:,|·&=+{}()\[\]<>/\\]+")
_CODE_LINE = re.compile(
    r"^\s*(?:(?:const|let|var)\s+\w+\s*[:=]|(?:async\s+)?def\s+\w+\s*\("
    r"|class\s+\w+\s*[:(]|(?:from\s+\S+\s+)?import\s+\S"
    r"|(?:return|await)\s+[^#\n]*[();=]|[{};]\s*$)"
)
_ACKNOWLEDGMENT = re.compile(
    r"\b(?:thanks|thank you|understood|certainly|sounds good|all right|alright"
    r"|agreed|got it|roger|okay|ok|great|perfect|acknowledgments?)\b", re.I,
)
_NEGATION = re.compile(
    r"\b(?:never|no|without|avoid|cannot|refrain\s+from)\b"
    r"|\bnot\b(?!\s+only\b)|\b\w+n['’]t\b", re.I,
)
_CONSTRAINT_SUMMARY = "Contains negative requirements or caveats; consult the source messages for the exact wording."
_CLAUSE = re.compile(r"[\n.!?;:]+|\b(?:but|however)\b", re.I)
_FALLBACK_SUMMARY = re.compile(
    r"(?im)^\s*(?:No readable topic terms were found\.|No sufficiently specific topic phrase was found\."
    r"|Brief acknowledgments and conversational confirmations\."
    r"|Contains negative requirements or caveats; consult the source messages for the exact wording\.)\s*$"
)


@dataclass(frozen=True)
class LabelBackground:
    """Document frequencies shared by all labels within one fit layer."""

    document_count: int
    term_documents: Mapping[str, int]


def _document(text: str) -> tuple[Counter[tuple[str, ...]], dict[str, Counter[str]], bool]:
    # Upper layers consume child titles and summaries. A fallback's explanation
    # must not become fabricated topic evidence at the next layer.
    text = _FALLBACK_SUMMARY.sub("", str(text))
    text = _ROLE.sub("", _FENCE.sub(" ", str(text)))
    text = "\n".join(line for line in text.splitlines() if not _CODE_LINE.match(line))
    text = _URL_PATH.sub(" ", text)
    # A constraint must not erase the independent subjects in the rest of a
    # message, nor lose its negation and become an affirmative action label.
    clauses = [clause.strip() for clause in _CLAUSE.split(text) if clause.strip()]
    constraints = any(_NEGATION.search(clause) for clause in clauses)
    text = "\n".join(clause for clause in clauses if not _NEGATION.search(clause))
    text = _REQUEST.sub("", text)
    # Identifiers can contain useful words; punctuation and camel casing must
    # not become single opaque title tokens. Fenced code itself is omitted.
    text = text.replace("_", " ").replace("-", " ")
    text = _IDENTIFIER.sub(lambda match: " ".join(
        part if part.isupper() else part.casefold() for part in _CAMEL.split(match.group())
    ), text)
    phrases: Counter[tuple[str, ...]] = Counter()
    forms: dict[str, Counter[str]] = {}
    for segment in _BOUNDARY.split(text):
        segment = _REQUEST.sub("", segment)
        run: list[str] = []

        def emit() -> None:
            for start in range(len(run)):
                for length in range(1, min(3, len(run) - start) + 1):
                    phrase = tuple(run[start:start + length])
                    if len(set(phrase)) == len(phrase):
                        phrases[phrase] += 1
            run.clear()

        for match in _TOKEN.finditer(segment):
            original = match.group()
            word = original.casefold()
            if word in _STOP or word in _DISCOURSE or len(word) > 24 or (len(word) < 3 and not original.isupper()):
                emit()
                continue
            run.append(word)
            # Preserve acronyms and mixed-case proper names when actually
            # present in evidence. Ordinary sentence capitalization is ignored.
            acronym = original.isupper() and len(original) <= 8
            proper = not original.isupper() and (any(c.isupper() for c in original[1:])
                                                or original[0].isupper() and match.start() > 0)
            display = original if acronym or proper else word
            forms.setdefault(word, Counter())[display] += 1
        emit()
    return phrases, forms, constraints


def build_background(rows: Sequence[Mapping[str, Any]]) -> LabelBackground:
    documents: Counter[str] = Counter()
    for row in rows:
        _, forms, _ = _document(str(row.get("text") or ""))
        documents.update(forms.keys())
    return LabelBackground(len(rows), documents)


def representation(
    rows: Sequence[Mapping[str, Any]], background: LabelBackground | None = None,
    *, inherited_label: tuple[str, str] | None = None,
) -> tuple[str, str, list[str]]:
    """Return a short title, thematic summary and up to eight evidence phrases."""

    if inherited_label:
        original, summary = inherited_label
        parts = []
        for part in original.split(" · "):
            words = tuple(word.casefold() for word in _TOKEN.findall(part))
            if (not 1 <= len(words) <= 3 or len(part) > 42 or _NEGATION.search(part)
                    or any(word in _DISCOURSE for word in words)
                    or words[-1] in _VERB_HEADS
                    or all(word in _STOP or word in _GENERIC_SINGLETON for word in words)):
                continue
            parts.append(part)
        if len(parts) > 1:
            parts = [part for part in parts if part.casefold() != "constraints"]
        title = " · ".join(parts)
        if title and len(title) <= 64:
            # These are existing semantic child labels, not raw message lines.
            # A structural singleton should retain its useful child's name.
            if title != original or not summary.strip():
                summary = f"Topics include {title}."
            return title, summary[:720], [part.casefold() for part in parts]

    documents: Counter[tuple[str, ...]] = Counter()
    frequencies: Counter[tuple[str, ...]] = Counter()
    forms: dict[str, Counter[str]] = {}
    acknowledgments = 0
    constraints = 0
    for row in rows:
        text = str(row.get("text") or "")
        acknowledgments += bool(_ACKNOWLEDGMENT.search(text))
        phrases, spellings, has_constraints = _document(text)
        constraints += has_constraints
        documents.update(phrases.keys())
        # One very long or repetitive first message cannot outweigh the rest
        # of the cluster just by repeating the same phrase.
        frequencies.update({phrase: min(count, 3) for phrase, count in phrases.items()})
        for word, variants in spellings.items():
            forms.setdefault(word, Counter()).update({form: min(count, 3) for form, count in variants.items()})

    def fallback() -> tuple[str, str, list[str]]:
        if constraints:
            return "Constraints and caveats", _CONSTRAINT_SUMMARY, []
        if acknowledgments >= max(1, len(rows) // 2 + 1):
            return "Acknowledgments", "Brief acknowledgments and conversational confirmations.", []
        if documents:
            return "Conversation notes", "No sufficiently specific topic phrase was found.", []
        return "Conversation topic", "No readable topic terms were found.", []

    if not documents:
        return fallback()
    context = background or LabelBackground(len(rows), {
        phrase[0]: count for phrase, count in documents.items() if len(phrase) == 1
    })

    def salient(word: str) -> bool:
        return word not in _GENERIC_SINGLETON and any(
            form.isupper() and len(form) <= 8
            or not form.isupper() and any(character.isupper() for character in form[1:])
            or form[0].isupper() and form.casefold() == word and documents[(word,)] >= 2
            for form in forms[word]
        )

    def quality(phrase: tuple[str, ...]) -> float:
        # A phrase ending in a finite verb, adverb or vague placeholder is
        # usually a sentence fragment rather than a topic. Past participles
        # can still modify a real head: "encrypted storage", for example.
        if phrase[-1] in _VAGUE or phrase[-1] in _ADVERB_HEADS or phrase[-1] in _VERB_HEADS:
            return 0.0
        if (phrase[-1].endswith(("ly", "ed")) and phrase[-1] not in _NOUN_ENDINGS
                and not salient(phrase[-1])):
            return 0.0
        if any((word.endswith("ly") or word.endswith("ed") and word not in _PAST_MODIFIERS)
               and word not in _NOUN_ENDINGS and not salient(word)
               for word in phrase[:-1]):
            return 0.0
        if len(phrase) == 1:
            word = phrase[0]
            if word in _GENERIC_SINGLETON:
                return 0.0
            if salient(word):
                return 0.7
            supported = documents[phrase] >= max(3, math.ceil(len(rows) * 0.2))
            nominal = word.endswith(("tion", "sion", "ment", "ness", "ity", "ance", "ence"))
            return 0.45 if supported or nominal else 0.0
        specific = [word for word in phrase if word not in _GENERIC_SINGLETON]
        if not specific:
            return 0.85 if all(word not in _VAGUE for word in phrase) else 0.0
        return 0.7 if phrase[-1] in _GENERIC_SINGLETON else 1.0

    qualities = {phrase: quality(phrase) for phrase in documents}
    candidates = [phrase for phrase in documents if qualities[phrase] > 0]
    if not candidates:
        return fallback()

    def score(phrase: tuple[str, ...]) -> float:
        coverage = documents[phrase]
        # Word document frequencies keep the shared background compact: it
        # does not retain every possible phrase from every other cluster.
        # Contrast with the other clusters, not with the cluster's own repeated
        # evidence: a rare aside must not outrank its well-supported subject.
        outside_documents = max(context.document_count - len(rows), 0)
        inverse_frequency = sum(0.15 + math.log(
            (1 + outside_documents) / (1 + min(outside_documents, max(
                context.term_documents.get(word, 0) - documents[(word,)], 0,
            )))
        ) for word in phrase) / len(phrase)
        return ((coverage ** 1.35 + math.log1p(frequencies[phrase])) * inverse_frequency
                * len(phrase) ** 0.6 * qualities[phrase])

    ranked = sorted(candidates, key=lambda phrase: (-score(phrase), -documents[phrase], phrase))
    chosen: list[tuple[str, ...]] = []
    for phrase in ranked:
        words = set(phrase)
        # Prefer one coherent phrase to several overlapping fragments of it.
        if any(len(words & set(other)) / min(len(words), len(other)) >= 0.75 for other in chosen):
            continue
        chosen.append(phrase)
        if len(chosen) == 8:
            break

    def display(phrase: tuple[str, ...], capitalize: bool = False) -> str:
        words = [sorted(forms[word], key=lambda form: (-forms[word][form], form))[0] for word in phrase]
        if capitalize:
            words[0] = words[0][0].upper() + words[0][1:]
        return " ".join(words)

    titles = []
    title_words: set[str] = set()
    for phrase in chosen:
        if (documents[phrase] < documents[chosen[0]] * 0.4
                or score(phrase) < score(chosen[0]) * 0.6 or title_words.intersection(phrase)):
            continue
        value = display(phrase, True)
        if len(value) <= 42 and len(" · ".join([*titles, value])) <= 64:
            titles.append(value)
            title_words.update(phrase)
        if len(titles) == 2:
            break
    title = " · ".join(titles) or display((chosen[0][0],), True)
    thematic = [phrase for phrase in chosen if documents[phrase] >= documents[chosen[0]] * 0.25
                and score(phrase) >= score(chosen[0]) * 0.6]
    themes = [display(phrase) for phrase in thematic[:4]]
    joined = themes[0] if len(themes) == 1 else ", ".join(themes[:-1]) + " and " + themes[-1]
    summary = f"Topics include {joined}."
    if constraints:
        summary += "\n" + _CONSTRAINT_SUMMARY
    return title, summary, [" ".join(phrase) for phrase in thematic]
