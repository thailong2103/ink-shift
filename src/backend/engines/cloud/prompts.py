"""Set-of-Marks prompts and localization instructions for Cloud Vision LLMs."""

from __future__ import annotations


def get_som_system_prompt(target_lang: str = "vi") -> str:
    """Generate Set-of-Marks prompt requesting flat JSON dictionary of translations."""
    lang_name = "Vietnamese" if target_lang.lower() == "vi" else target_lang
    return (
        "You are an expert manga dialogue translator.\n"
        "The provided manga page has speech balloons and dialogue text regions clearly marked with sequential badge numbers: [1], [2], [3], etc.\n"
        f"Translate the dialogue text inside each numbered badge region into natural {lang_name}.\n"
        "Return strictly a flat JSON object where each key is the badge number (as a string) and the value is the translated dialogue text:\n"
        '{\n  "1": "Translated dialogue for badge 1",\n  "2": "Translated dialogue for badge 2"\n}\n'
        "CRITICAL RULES FOR NON-TEXT OR EMPTY REGIONS:\n"
        '- If a marked region contains only drawings, character hair, artwork textures, or blank background with no text, set its value to an empty string "".\n'
        "- Do not hallucinate or duplicate adjacent dialogue for regions that have no text.\n"
        '- If a region contains an untranslated sound effect (SFX) or cannot be translated, set its value to an empty string "".\n'
        "Do not invent new badge IDs.\n"
        "Do not output markdown code fences or conversational commentary. Output JSON only."
    )
