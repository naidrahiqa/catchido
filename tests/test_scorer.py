"""Tests for the relevance scorer."""
import pytest
from catchido.keywords.scorer import (
    RelevanceScorer, PostData,
    SCORE_NAME_MENTION, SCORE_TRUSTED_ACCOUNT,
    PENALTY_EXCLUDE_TERM, HASHTAG_SPAM_THRESHOLD,
)
from catchido.db.models import IdolProfile, IdolType, IdolStatus


@pytest.fixture
def scorer():
    return RelevanceScorer(min_score=0.3)


@pytest.fixture
def jp_idol():
    return IdolProfile(
        display_name="Saito Asuka",
        idol_type=IdolType.JAPANESE,
        kanji_name="齋藤飛鳥",
        group_name="乃木坂46",
        status=IdolStatus.ACTIVE,
    )


@pytest.fixture
def kr_idol():
    return IdolProfile(
        display_name="Jisoo",
        idol_type=IdolType.KOREAN,
        hangul_name="지수",
        stage_name="Jisoo",
        group_name="BLACKPINK",
        fandom_name="BLINK",
        status=IdolStatus.ACTIVE,
    )


class TestScorerJP:
    def test_empty_post_scores_zero(self, scorer, jp_idol):
        post = PostData(text="", hashtags=[], author="nobody")
        score = scorer.calculate_relevance(post, jp_idol)
        assert score == 0.0

    def test_kanji_name_mention(self, scorer, jp_idol):
        post = PostData(text="齋藤飛鳥の写真", hashtags=[], author="nobody")
        score = scorer.calculate_relevance(post, jp_idol)
        assert score >= SCORE_NAME_MENTION

    def test_trusted_account_boost(self, scorer, jp_idol):
        post = PostData(text="", hashtags=[], author="fanaccount1")
        score = scorer.calculate_relevance(post, jp_idol, trusted_usernames=["fanaccount1"])
        assert score >= SCORE_TRUSTED_ACCOUNT

    def test_exclude_penalty(self, scorer, jp_idol):
        post = PostData(text="cosplay photo", hashtags=[], author="nobody")
        score = scorer.calculate_relevance(post, jp_idol)
        assert score == 0.0  # penalty brings it to 0

    def test_score_clamped_to_1(self, scorer, jp_idol):
        post = PostData(
            text="齋藤飛鳥 cosplay",
            hashtags=[],
            author="fanaccount1",
        )
        score = scorer.calculate_relevance(post, jp_idol, trusted_usernames=["fanaccount1"])
        assert 0.0 <= score <= 1.0


class TestScorerKR:
    def test_hangul_name_mention(self, scorer, kr_idol):
        post = PostData(text="지수 사진", hashtags=[], author="nobody")
        score = scorer.calculate_relevance(post, kr_idol)
        assert score >= SCORE_NAME_MENTION

    def test_stage_name_caps(self, scorer, kr_idol):
        post = PostData(text="JISOO update", hashtags=[], author="nobody")
        score = scorer.calculate_relevance(post, kr_idol)
        assert score > 0.0

    def test_fandom_name_boost(self, scorer, kr_idol):
        post = PostData(text="blink fandom", hashtags=[], author="nobody")
        score = scorer.calculate_relevance(post, kr_idol)
        assert score > 0.0

    def test_hashtag_spam_penalty(self, scorer, kr_idol):
        tags = [f"tag{i}" for i in range(20)]
        post = PostData(text="post", hashtags=tags, author="nobody")
        score = scorer.calculate_relevance(post, kr_idol)
        assert score <= 0.1  # heavily penalized


class TestScorerDict:
    def test_dict_profile_works(self, scorer):
        profile = {
            "idol_type": "jp",
            "keywords": {"kanji": ["齋藤飛鳥"], "exclude": []},
        }
        post = PostData(text="齋藤飛鳥", hashtags=[], author="nobody")
        score = scorer.calculate_relevance(post, profile)
        assert score >= SCORE_NAME_MENTION
