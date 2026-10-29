"""Recognize incomplete interview questions using distinctive keywords and phrases."""
import re
import time
from collections import Counter
from typing import Optional
try:
    from rapidfuzz import fuzz
except ImportError:
    from difflib import SequenceMatcher
    class _Fuzz:
        @staticmethod
        def token_set_ratio(a, b):
            left, right = set(a.split()), set(b.split())
            if not left or not right:
                return 0
            if left <= right or right <= left:
                return 100
            return SequenceMatcher(None, ' '.join(sorted(left)), ' '.join(sorted(right))).ratio() * 100
        @staticmethod
        def partial_ratio(a, b):
            if not a or not b:
                return 0
            if a in b or b in a:
                return 100
            return SequenceMatcher(None, a, b).ratio() * 100
    fuzz = _Fuzz()

MATCH_THRESHOLD = 62
MIN_SCORE_MARGIN = 5
MATCH_COOLDOWN_SECONDS = 3
SWITCH_SCORE_BONUS = 8
INTERVIEW_SOURCE_WEIGHT = 1.0
MICROPHONE_SOURCE_WEIGHT = 0.60

STOP_WORDS = set('what why how when where who which do does did have has are is can could would will tell me describe give example explain walk through you your yours we us our a an the of to in on at for and or with about from that this it be been being were was as than one time kind mean several same comfortable support technical experience work working position role job issue issues problem handle used'.split())

STOP_WORDS.update('que qué como cómo cuando cuándo donde dónde quien quién cual cuál por para el la los las un una de del al en y o es son se te tu tus usted ustedes nos nosotros mi mis con sin lo su sus hay puede puedes podría contar cuéntame explicá explica describí describe'.split())


def normalize_text(text):
    text = text.lower().replace('’', "'")
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', text)).strip()


def extract_question_keywords(question):
    norm = normalize_text(question)
    # Keywords are derived only from the active document.
    keywords = [w for w in norm.split() if len(w) >= 3 and w not in STOP_WORDS]
    keywords.append(norm)
    return list(dict.fromkeys(normalize_text(k) for k in keywords if k))


def _contains(text, phrase):
    return bool(phrase) and f' {phrase} ' in f' {text} '


def score_question(transcript, question_item, source='interview', keyword_counts=None):
    text = normalize_text(transcript)
    if not text:
        return 0.0
    keywords = set(normalize_text(k) for k in question_item.get('keywords', []))
    hits = [k for k in keywords if _contains(text, k)]
    strong = []
    # Rare content words from newly added questions can act as anchors. Exclude
    # generic interview language even if it happens to occur in only one entry.
    generic = STOP_WORDS | set('want choose interested interested improving currently previous available start tasks tickets customer user good main part made learn doing since last should attention range opportunity looking systems following documented yourself years five'.split())
    automatic = [k for k in hits if len(k.split()) == 1 and len(k) >= 5 and k not in generic
                 and keyword_counts is not None and keyword_counts[k] == 1]
    strong.extend(automatic)
    best = 0.0
    for question in [question_item['question']] + question_item.get('aliases', []):
        norm = normalize_text(question)
        content = set(w for w in norm.split() if w not in STOP_WORDS)
        overlap = content & set(text.split())
        if not hits and not overlap:
            continue
        fuzzy = .60 * fuzz.token_set_ratio(text, norm) + .40 * fuzz.partial_ratio(text, norm)
        score = .65 * fuzzy + min(25, len(overlap) * 8)
        if strong:
            anchor_score = 88 if all(len(k.split()) == 1 for k in strong) else 92
            score = max(score, min(98, anchor_score + min(6, len(overlap) * 2)))
        elif len(overlap) < 2 and not any(len(k.split()) > 1 for k in hits):
            # One generic word is insufficient, even if partial_ratio says 100.
            score = min(score, 55)
        best = max(best, min(100, score))
    weight = INTERVIEW_SOURCE_WEIGHT if source == 'interview' else MICROPHONE_SOURCE_WEIGHT
    return best * weight


class QuestionMatcher:
    def __init__(self, questions):
        self.questions = questions
        for item in questions:
            keys = list(item.get('keywords', []))
            for q in [item['question']] + item.get('aliases', []):
                keys.extend(extract_question_keywords(q))
            item['keywords'] = list(dict.fromkeys(keys))
        self.keyword_counts = Counter(k for item in questions for k in set(normalize_text(k) for k in item['keywords']))
        self.current_match = None
        self.last_match_time = 0.0
        self.last_score = 0.0

    def match(self, transcript, source='interview'):
        if not transcript.strip() or not self.questions:
            return None
        # Prefer the newest fragment. Only use the wider context if it is inconclusive.
        parts = [p.strip() for p in transcript.split('\n') if p.strip()]
        newest = parts[-1] if parts else transcript
        result = self._rank(newest, source)
        if result is None and newest != transcript:
            result = self._rank(transcript, source)
        if result is None:
            return None
        item, score = result
        now = time.monotonic()
        if self.current_match and item is not self.current_match:
            if now - self.last_match_time < MATCH_COOLDOWN_SECONDS:
                current_evidence = score_question(newest, self.current_match, source, self.keyword_counts)
                decisive_new_question = score >= 90 and score - current_evidence >= 15
                if not decisive_new_question and score < self.last_score + SWITCH_SCORE_BONUS:
                    return None
        if item is not self.current_match:
            self.last_match_time = now
        self.current_match, self.last_score = item, score
        return item, score

    def _rank(self, text, source):
        normalized = normalize_text(text)
        exact = [q for q in self.questions if any(normalized == normalize_text(candidate)
                 for candidate in [q['question']] + q.get('aliases', []))]
        if len(exact) == 1:
            weight = INTERVIEW_SOURCE_WEIGHT if source == 'interview' else MICROPHONE_SOURCE_WEIGHT
            if 100 * weight >= MATCH_THRESHOLD:
                return exact[0], 100 * weight
            return None
        if len(exact) > 1:
            return None
        ranked = sorted(((q, score_question(text, q, source, self.keyword_counts)) for q in self.questions),
                        key=lambda pair: pair[1], reverse=True)
        item, score = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0
        if score < MATCH_THRESHOLD or score - runner_up < MIN_SCORE_MARGIN:
            return None
        return item, score


def search_questions(query, questions, limit=8):
    """Manual search is independent from audio thresholds, cooldown and weights."""
    import unicodedata
    def clean(text):
        return normalize_text(''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c)))
    query = clean(query)
    if not query:
        return []
    ranked = []
    tokens = set(query.split())
    for index, item in enumerate(questions):
        tags = [clean(t) for t in item.get('tags', [])]
        titles = [clean(t) for t in [item['question']] + item.get('aliases', [])]
        keys = [clean(k) for k in item.get('keywords', [])]
        if query in tags:
            score = 120
        elif query in titles:
            score = 115
        elif len(query) >= 2 and any(t.startswith(query) for t in tags):
            score = 110
        elif any(query in t for t in tags):
            score = 105
        elif any(query in t for t in titles):
            score = 100
        elif any(query in t for t in keys):
            score = 90
        elif tokens <= set(' '.join(tags + titles + keys).split()):
            score = 80
        else:
            continue
        ranked.append((score, index, item))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return [row[2] for row in ranked[:limit]]
