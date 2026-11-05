"""Turning a topic into queries a keyword search can answer (T-1.5.14.2)."""
from __future__ import annotations

import pytest

from app.sources._topic_terms import MAX_QUERIES, term_keys, topic_keys, topic_queries, topic_terms

SENTENCE = "Why did the Roman Empire fall and what can we learn from it today?"


def test_a_sentence_comes_down_to_the_words_that_carry_it():
    assert topic_terms(SENTENCE) == ["Roman", "Empire", "fall"]


def test_the_topic_as_written_goes_first():
    """So a topic that works today costs one request and answers the same."""
    assert topic_queries(SENTENCE)[0] == SENTENCE


def test_a_topic_of_two_words_is_one_query():
    assert topic_queries("nuclear power") == ["nuclear power"]


def test_a_long_topic_shortens_to_two_words_and_no_further():
    assert topic_queries("How do rare earth magnets shape electric motors") == [
        "How do rare earth magnets shape electric motors",
        "rare earth magnets shape electric motors",
        "rare earth magnets",
        "rare earth",
    ]


def test_the_number_of_queries_is_bounded():
    assert len(topic_queries(" ".join(f"word{i}" for i in range(40)))) <= MAX_QUERIES


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_a_blank_topic_is_no_query(blank):
    assert topic_queries(blank) == []


def test_a_topic_made_only_of_stopwords_keeps_them():
    assert topic_terms("The Who") == ["The", "Who"]


def test_punctuation_goes_and_a_possessive_with_it():
    assert topic_terms("Rome's collapse: causes (and consequences)!") == [
        "Rome",
        "collapse",
        "causes",
        "consequences",
    ]


def test_contractions_are_stopwords_with_either_apostrophe():
    assert topic_terms("don't panic") == topic_terms("don’t panic") == ["panic"]


def test_repeats_collapse_ignoring_case():
    assert topic_terms("Nuclear nuclear NUCLEAR waste") == ["Nuclear", "waste"]


def test_devanagari_words_stay_whole():
    """``str.isalnum`` rejects vowel signs, and would cut this word in three."""
    assert topic_terms("भगवद गीता") == ["भगवद", "गीता"]


def test_a_plural_compares_equal_to_its_singular():
    assert topic_keys("nuclear plant") <= term_keys("Nuclear Plants")


@pytest.mark.parametrize("word", ["gas", "news", "loss"])
def test_a_word_that_only_looks_plural_is_left_alone(word):
    assert term_keys(word) == {word}
