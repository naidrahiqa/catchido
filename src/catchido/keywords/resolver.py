import re
from typing import List, Dict, Any, Set
from ..db.models import IdolType

JP_ROMAJI_VARIANTS = {
    "ou": ["ō", "o", "ou"],
    "uu": ["ū", "u", "uu"],
    "ei": ["ē", "ei", "e"],
    "shi": ["si", "shi"],
    "chi": ["ti", "chi"],
    "tsu": ["tu", "tsu"],
    "fu": ["hu", "fu"],
    "ji": ["zi", "ji"],
    "sha": ["sya", "sha"],
}

KR_SURNAME_VARIANTS = {
    "김": ["Kim", "Gim"],
    "이": ["Lee", "Yi", "Rhee", "Li", "Ri"],
    "박": ["Park", "Pak", "Bak", "Bahk"],
    "정": ["Jung", "Jeong", "Chung", "Cheong"],
    "최": ["Choi", "Choe", "Chwe"],
    "조": ["Jo", "Cho"],
    "강": ["Kang", "Gang"],
    "윤": ["Yoon", "Yun"],
    "장": ["Jang", "Chang"],
    "임": ["Im", "Lim", "Yim"],
    "한": ["Han"],
    "오": ["Oh", "O"],
    "서": ["Seo", "Suh", "So"],
    "신": ["Shin", "Sin"],
    "권": ["Kwon", "Gwon"],
    "황": ["Hwang"],
    "안": ["Ahn", "An"],
    "송": ["Song"],
    "전": ["Jeon", "Jun", "Chun", "Chon"],
    "홍": ["Hong"],
    "문": ["Moon", "Mun"],
    "배": ["Bae", "Bai", "Pae"],
    "백": ["Baek", "Paek", "Back"],
    "남": ["Nam"],
    "류": ["Ryu", "Yoo", "Ryoo"],
    "유": ["Yoo", "Yu", "You"],
}

KR_GIVEN_NAME_VARIANTS = {
    "지수": ["Jisoo", "Ji-soo", "Ji Soo", "Jisu", "Ji-su"],
    "수지": ["Suzy", "Suji", "Su-ji", "Su Ji"],
    "지은": ["Ji-eun", "Jieun", "Ji Eun"],
    "예은": ["Ye-eun", "Yeeun", "Ye Eun"],
    "채원": ["Chaewon", "Chae-won", "Chae Won"],
    "민영": ["Minyoung", "Min-young", "Minnyoung", "Min Young"],
    "태형": ["Taehyung", "Tae-hyung", "Tae Hyung"],
    "정국": ["Jungkook", "Jeong-guk", "Jung Kook", "Jeongguk"],
}

class NameResolver:
    @staticmethod
    def flip_name_order(name: str) -> str:
        """Flip 'First Last' to 'Last First' or vice-versa if it contains space."""
        parts = name.strip().split()
        if len(parts) == 2:
            return f"{parts[1]} {parts[0]}"
        return name

    @staticmethod
    def generate_no_space_variants(name: str) -> List[str]:
        return [name.replace(" ", "")]

    @staticmethod
    def generate_case_variants(name: str) -> List[str]:
        return list({name.lower(), name.upper(), name.title()})

    @staticmethod
    def generate_jp_romaji_permutations(romaji_name: str) -> List[str]:
        """Generate possible Japanese romaji variations."""
        variants = {romaji_name}
        name_lower = romaji_name.lower()
        
        # Simple replacements based on common romaji patterns
        current = name_lower
        for key, vals in JP_ROMAJI_VARIANTS.items():
            if key in current:
                for val in vals:
                    variants.add(current.replace(key, val))
        
        # Also flip order
        flipped = NameResolver.flip_name_order(romaji_name)
        variants.add(flipped)
        variants.add(flipped.lower())
        
        # Case variations
        final_variants = set()
        for v in variants:
            final_variants.update(NameResolver.generate_case_variants(v))
            final_variants.update(NameResolver.generate_no_space_variants(v))
            
        return list(final_variants)

    @staticmethod
    def generate_kr_romaji_permutations(hangul_name: str) -> List[str]:
        """Generate possible Korean romaji variations from a Hangul name."""
        if not hangul_name or len(hangul_name) < 2:
            return []
            
        surname_hangul = hangul_name[0]
        given_hangul = hangul_name[1:]
        
        surname_variants = KR_SURNAME_VARIANTS.get(surname_hangul, [surname_hangul])
        given_variants = KR_GIVEN_NAME_VARIANTS.get(given_hangul, [given_hangul])
        
        # If given name isn't in predefined map, try basic romanization guesses
        if given_variants == [given_hangul]:
            # Fallback simple transcription guess (e.g. just using stage names or standard rules)
            given_variants = [given_hangul] # Placeholder/no-op for unknown Hangul
            
        permutations = set()
        for sv in surname_variants:
            for gv in given_variants:
                permutations.add(f"{sv} {gv}")
                permutations.add(f"{gv} {sv}")
                permutations.add(f"{sv}{gv}")
                permutations.add(f"{gv}-{sv}")
                
        final_variants = set()
        for p in permutations:
            final_variants.update(NameResolver.generate_case_variants(p))
            final_variants.update(NameResolver.generate_no_space_variants(p))
            
        return list(final_variants)

    @staticmethod
    def generate_hashtag_variants(names: List[str], platform: str) -> List[str]:
        """Generate hashtags for Twitter/Weibo/Threads."""
        tags = set()
        for name in names:
            clean_name = name.replace(" ", "")
            if not clean_name:
                continue
            if platform == "weibo":
                tags.add(f"#{clean_name}#")
            else:
                tags.add(f"#{clean_name}")
        return list(tags)

    def resolve(self, idol_type: IdolType, **name_inputs) -> Dict[str, List[str]]:
        """
        Resolve name variants.
        name_inputs can contain:
          JP: kanji_name, romaji_name, hiragana, katakana, nicknames
          KR: hangul_name, stage_name, real_name, nicknames, chinese_name
        """
        results: Dict[str, Set[str]] = {
            "kanji": set(),
            "hiragana": set(),
            "katakana": set(),
            "hangul": set(),
            "romaji": set(),
            "nicknames": set(),
            "hashtags": set(),
            "chinese": set()
        }

        nicknames = name_inputs.get("nicknames", [])
        if isinstance(nicknames, str):
            nicknames = [n.strip() for n in nicknames.split(",") if n.strip()]
        for nick in nicknames:
            results["nicknames"].add(nick)
            results["nicknames"].add(nick.lower())

        if idol_type == IdolType.JAPANESE:
            kanji_name = name_inputs.get("kanji_name")
            if kanji_name:
                results["kanji"].add(kanji_name)
                # Old/New Kanji variant swaps (e.g. 齋藤 <-> 斉藤)
                if "齋" in kanji_name:
                    results["kanji"].add(kanji_name.replace("齋", "斉"))
                if "斉" in kanji_name:
                    results["kanji"].add(kanji_name.replace("斉", "齋"))
                if "櫻" in kanji_name:
                    results["kanji"].add(kanji_name.replace("櫻", "桜"))
                if "桜" in kanji_name:
                    results["kanji"].add(kanji_name.replace("桜", "櫻"))

            romaji_name = name_inputs.get("romaji_name")
            if romaji_name:
                romaji_perms = self.generate_jp_romaji_permutations(romaji_name)
                results["romaji"].update(romaji_perms)

            hiragana = name_inputs.get("hiragana")
            if hiragana:
                results["hiragana"].add(hiragana)
                results["hiragana"].add(hiragana.replace(" ", ""))

            katakana = name_inputs.get("katakana")
            if katakana:
                results["katakana"].add(katakana)
                results["katakana"].add(katakana.replace(" ", ""))

        elif idol_type == IdolType.KOREAN:
            hangul_name = name_inputs.get("hangul_name")
            if hangul_name:
                results["hangul"].add(hangul_name)
                if len(hangul_name) >= 3:
                    # Given name only (last 2 characters)
                    results["hangul"].add(hangul_name[1:])
                # Suffixes
                results["hangul"].add(f"{hangul_name}야")
                results["hangul"].add(f"{hangul_name}씨")

                # Generate Romaji from Hangul
                kr_romaji = self.generate_kr_romaji_permutations(hangul_name)
                results["romaji"].update(kr_romaji)

            stage_name = name_inputs.get("stage_name")
            if stage_name:
                results["romaji"].add(stage_name)
                results["romaji"].add(stage_name.lower())
                results["romaji"].add(stage_name.upper())

            real_name = name_inputs.get("real_name")
            if real_name:
                results["romaji"].add(real_name)
                results["romaji"].update(self.generate_jp_romaji_permutations(real_name)) # reuse JP logic for general spacing

            chinese_names = name_inputs.get("chinese_name", [])
            if isinstance(chinese_names, str):
                chinese_names = [c.strip() for c in chinese_names.split(",") if c.strip()]
            for cn in chinese_names:
                results["chinese"].add(cn)

        # Convert sets to sorted lists
        return {k: sorted(list(v)) for k, v in results.items()}
