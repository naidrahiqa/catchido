from dataclasses import dataclass, field
from typing import List, Dict, Set
from ..db.models import IdolType

FAN_CONTENT_INDICATORS = {
    "twitter": {
        "jp_hashtags": [
            "#推しカメラ", "#ファンカム", "#ファンサイト", 
            "#撮影会", "#生写真", "#握手会", "#サイン会", 
            "#お渡し会", "#現場"
        ],
        "kr_hashtags": [
            "#직찍", "#팬싸", "#팬사인회", "#마스터님", "#홈마", 
            "#고화질", "#원본", "#음방", "#공항패션", "#출근길", 
            "#퇴근길", "#팬캠", "#직캠", "#fancam", "#fansite", 
            "#masternim", "#preview", "#HQ"
        ],
        "jp_bio_keywords": [
            "ファンサイト", "fansite", "fan account", "推し", "担当"
        ],
        "kr_bio_keywords": [
            "마스터", "홈마", "fansite", "fan account", "최애", 
            "본진", "masternim", "fanbase", "data", "backup"
        ]
    },
    "weibo": {
        "hashtags": [
            "#饭拍#", "#站姐#", "#前线#", "#高清#", "#原图#", 
            "#路透#", "#生图#", "#精修#", "#机场#"
        ]
    }
}

KPOP_EVENT_TYPES = [
    "음악방송", "팬사인회", "영상통화", "콘서트", "공항", 
    "출근길", "시상식", "브이앱", "위버스라이브"
]

@dataclass
class ExpandedKeywordSet:
    idol_name: str
    idol_type: IdolType
    search_keywords: List[str] = field(default_factory=list)
    hashtags: List[str] = field(default_factory=list)
    exclude_keywords: List[str] = field(default_factory=list)
    twitter_query: str = ""
    weibo_queries: List[str] = field(default_factory=list)
    threads_queries: List[str] = field(default_factory=list)

class KeywordExpander:
    def __init__(self):
        from .resolver import NameResolver
        self.resolver = NameResolver()

    def generate_birthday_keywords(self, name: str, birthday: str, idol_type: IdolType) -> List[str]:
        """Generate birthday hashtags (e.g. #HappyJisooDay or #齋藤飛鳥生誕祭)."""
        tags = []
        if not birthday:
            return tags
            
        try:
            # Parse birthday (expected ISO YYYY-MM-DD or MM-DD)
            parts = birthday.split("-")
            month_day = ""
            if len(parts) == 3:
                month_day = f"{parts[1]}{parts[2]}" # e.g. 0810
            elif len(parts) == 2:
                month_day = f"{parts[0]}{parts[1]}"
        except:
            month_day = ""

        clean_name = name.replace(" ", "")
        
        if idol_type == IdolType.JAPANESE:
            tags.append(f"#{clean_name}生誕祭")
            tags.append(f"#{clean_name}誕生祭")
            if month_day:
                tags.append(f"#{clean_name}生誕祭{month_day}")
        else:
            tags.append(f"#Happy{clean_name}Day")
            tags.append(f"#Happy_{clean_name}_Day")
            if month_day:
                tags.append(f"#{clean_name}Day{month_day}")
                
        return tags

    def expand_profile(self, profile: Dict[str, Any] | Any) -> ExpandedKeywordSet:
        """
        Given configuration dict or dataclass, resolve names and build platform-specific queries.
        Supports both dict (from config.toml) and database models.
        """
        # Extract variables from dict or object
        if isinstance(profile, dict):
            name = profile.get("name", "")
            idol_type_val = profile.get("idol_type", "jp")
            idol_type = IdolType(idol_type_val)
            
            # JP Name resolution inputs
            kanji_name = profile.get("profile", {}).get("kanji_name")
            romaji_name = name
            hiragana = profile.get("keywords", {}).get("hiragana", [""])[0]
            katakana = profile.get("keywords", {}).get("katakana", [""])[0]
            nicknames = profile.get("keywords", {}).get("nicknames", [])
            group = profile.get("profile", {}).get("group", "")
            birthday = profile.get("profile", {}).get("birthday", "")
            
            # KR Specific inputs
            hangul_name = profile.get("profile", {}).get("hangul_name")
            stage_name = profile.get("profile", {}).get("stage_name")
            real_name = profile.get("profile", {}).get("real_name")
            chinese_name = profile.get("keywords", {}).get("chinese_name", [])
            
            exclude = profile.get("keywords", {}).get("exclude", [])
            custom_keywords = profile.get("keywords", {}).get("custom_keywords", [])
            hashtags_custom = profile.get("keywords", {}).get("hashtags", [])
        else:
            # Assume it's IdolProfile dataclass from db
            name = profile.display_name
            idol_type = profile.idol_type
            kanji_name = profile.kanji_name
            romaji_name = profile.real_name or profile.display_name
            hiragana = None
            katakana = None
            nicknames = getattr(profile, 'nicknames', [])
            group = profile.group_name
            birthday = profile.birthday
            hangul_name = profile.hangul_name
            stage_name = profile.stage_name
            real_name = profile.real_name
            chinese_name = [] # Default empty
            exclude = ["cosplay", "fanart", "AI생성"]
            custom_keywords = []
            hashtags_custom = []

        # Run through NameResolver
        resolver_inputs = {
            "kanji_name": kanji_name,
            "romaji_name": romaji_name,
            "hiragana": hiragana,
            "katakana": katakana,
            "nicknames": nicknames,
            "hangul_name": hangul_name,
            "stage_name": stage_name,
            "real_name": real_name,
            "chinese_name": chinese_name
        }
        
        resolved = self.resolver.resolve(idol_type, **resolver_inputs)

        # Collect all resolved terms as search keywords
        all_terms = set()
        for key, val_list in resolved.items():
            if key != "hashtags": # hashtags handled separately
                all_terms.update(val_list)
        
        if custom_keywords:
            all_terms.update(custom_keywords)

        # Generate hashtags
        generated_tags = set(hashtags_custom)
        generated_tags.update(self.resolver.generate_hashtag_variants(list(all_terms), "twitter"))
        
        # Birthday hashtags
        bday_tags = self.generate_birthday_keywords(name, birthday, idol_type)
        generated_tags.update(bday_tags)

        # Group name hashtags
        if group:
            generated_tags.add(f"#{group.replace(' ', '')}")

        # Platform specific queries
        twitter_query = self.build_twitter_query(list(all_terms), exclude)
        
        # Weibo queries
        weibo_queries = self.build_weibo_queries(
            kanji_name=kanji_name, 
            hangul_name=hangul_name,
            chinese_name=chinese_name, 
            stage_name=stage_name, 
            group=group, 
            hashtags=list(generated_tags)
        )

        # Threads queries
        threads_queries = self.build_threads_queries(name, list(generated_tags))

        return ExpandedKeywordSet(
            idol_name=name,
            idol_type=idol_type,
            search_keywords=sorted(list(all_terms)),
            hashtags=sorted(list(generated_tags)),
            exclude_keywords=exclude,
            twitter_query=twitter_query,
            weibo_queries=weibo_queries,
            threads_queries=threads_queries
        )

    def build_twitter_query(self, search_terms: List[str], exclude: List[str]) -> str:
        """
        Build an optimized Twitter OR query.
        Example: ("Saito Asuka" OR "齋藤飛鳥") has:media -is:retweet -cosplay -fanart
        """
        # Filter terms to avoid query length limit (Twitter API max query is 512 chars usually)
        # We take the most distinct terms
        distinct_terms = sorted(list(set(search_terms)), key=len, reverse=True)[:10]
        
        name_queries = []
        for term in distinct_terms:
            if " " in term:
                name_queries.append(f'"{term}"')
            else:
                name_queries.append(term)
                
        or_query = " OR ".join(name_queries)
        query = f"({or_query}) has:media -is:retweet"
        
        for ex in exclude[:5]: # limit exclusions to avoid hitting limit
            query += f" -{ex}"
            
        return query

    def build_weibo_queries(self, **inputs) -> List[str]:
        """Weibo search is simple term-based. Returns a list of separate queries."""
        queries = set()
        
        # Kanji is primary for JP idols on Weibo
        if inputs.get("kanji_name"):
            queries.add(inputs["kanji_name"])
            
        # Chinese translation name
        for cn in inputs.get("chinese_name", []):
            queries.add(cn)
            
        # Hangul or Stage name for KR idols
        if inputs.get("hangul_name"):
            queries.add(inputs["hangul_name"])
        if inputs.get("stage_name"):
            queries.add(inputs["stage_name"])
            
        # Group + Name combinations
        group = inputs.get("group")
        name = inputs.get("kanji_name") or inputs.get("stage_name") or inputs.get("hangul_name")
        if group and name:
            queries.add(f"{group} {name}")
            
        # Weibo double # hashtags
        for tag in inputs.get("hashtags", []):
            clean_tag = tag.lstrip("#")
            queries.add(f"#{clean_tag}#")
            
        # Limit to top 5 queries for efficiency
        return sorted(list(queries))[:5]

    def build_threads_queries(self, name: str, hashtags: List[str]) -> List[str]:
        """Build search terms for Threads."""
        queries = {name}
        for tag in hashtags[:3]:
            queries.add(tag.lstrip("#"))
        return sorted(list(queries))
