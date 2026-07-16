from dataclasses import dataclass, field
from typing import List, Dict, Any, Union
from ..db.models import IdolProfile, IdolType
from .expander import FAN_CONTENT_INDICATORS

# --- Scoring constants ---
SCORE_NAME_MENTION = 0.4
SCORE_STAGE_NAME_CAPS = 0.2
SCORE_HASHTAG_MATCH_EACH = 0.15
SCORE_HASHTAG_MATCH_MAX = 0.3
SCORE_TRUSTED_ACCOUNT = 0.3
SCORE_FAN_INDICATOR_EACH = 0.05
SCORE_FANDOM_BOOST = 0.1
SCORE_FAN_QUALITY_BOOST = 0.1
PENALTY_EXCLUDE_TERM = -0.5
PENALTY_HASHTAG_SPAM = -0.2
HASHTAG_SPAM_THRESHOLD = 15

@dataclass
class PostData:
    text: str
    hashtags: List[str] = field(default_factory=list)
    author: str = ""
    platform: str = "twitter"

class RelevanceScorer:
    def __init__(self, min_score: float = 0.3):
        self.min_score = min_score

    def calculate_relevance(
        self,
        post: PostData,
        profile: Union[IdolProfile, Dict[str, Any]],
        trusted_usernames: List[str] = None
    ) -> float:
        """
        Calculate a relevance score between 0.0 and 1.0.
        Score above threshold means post contains relevant media of the target idol.
        """
        score = 0.0
        text = post.text
        text_lower = text.lower()
        trusted_usernames = trusted_usernames or []

        # Determine type
        if isinstance(profile, dict):
            idol_type_val = profile.get("idol_type", "jp")
            idol_type = IdolType(idol_type_val)
            kanji_names = profile.get("keywords", {}).get("kanji", [])
            hangul_names = profile.get("keywords", {}).get("hangul", [])
            stage_name = profile.get("keywords", {}).get("stage_name", "")
            fandom_name = profile.get("keywords", {}).get("fandom", "")
            exclude = profile.get("keywords", {}).get("exclude", [])
            all_hashtags = profile.get("keywords", {}).get("hashtags", [])
        else:
            idol_type = profile.idol_type
            kanji_names = [profile.kanji_name] if profile.kanji_name else []
            hangul_names = [profile.hangul_name] if profile.hangul_name else []
            stage_name = profile.stage_name or ""
            fandom_name = profile.fandom_name or ""
            exclude = ["cosplay", "fanart", "AI생성"]
            all_hashtags = []

        # === 1. Direct Name Mention (Highest Signal) ===
        if idol_type == IdolType.JAPANESE:
            for name in kanji_names:
                if name and name in text:
                    score += SCORE_NAME_MENTION
                    break
        elif idol_type == IdolType.KOREAN:
            for name in hangul_names:
                if name and name in text:
                    score += SCORE_NAME_MENTION
                    break
            if stage_name and stage_name.upper() in text:
                score += SCORE_STAGE_NAME_CAPS

        # === 2. Hashtag Match ===
        if post.hashtags and all_hashtags:
            matching_tags = set(post.hashtags) & set(all_hashtags)
            score += min(len(matching_tags) * SCORE_HASHTAG_MATCH_EACH, SCORE_HASHTAG_MATCH_MAX)

        # === 3. Trusted Account (High Trust) ===
        if post.author in trusted_usernames or f"@{post.author}" in trusted_usernames:
            score += SCORE_TRUSTED_ACCOUNT

        # === 4. Fan Content Indicators ===
        platform_indicators = FAN_CONTENT_INDICATORS.get(post.platform, {})
        indicator_key = "jp_hashtags" if idol_type == IdolType.JAPANESE else "kr_hashtags"
        for indicator in platform_indicators.get(indicator_key, []):
            if indicator in post.hashtags or indicator in text:
                score += SCORE_FAN_INDICATOR_EACH

        # === 5. K-pop Specific Boosts ===
        if idol_type == IdolType.KOREAN:
            if fandom_name and fandom_name.lower() in text_lower:
                score += SCORE_FANDOM_BOOST
            if any(kw in text_lower for kw in ["preview", "hq", "고화질", "원본", "직찍"]):
                score += SCORE_FAN_QUALITY_BOOST

        # === 6. Penalties (Noise Filter) ===
        for ex in exclude:
            if ex.lower() in text_lower:
                score += PENALTY_EXCLUDE_TERM
                break

        if len(post.hashtags) > HASHTAG_SPAM_THRESHOLD:
            score += PENALTY_HASHTAG_SPAM

        return max(0.0, min(1.0, score))
