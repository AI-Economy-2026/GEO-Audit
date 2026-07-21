import re

def strip_em_dashes(text):
    """Replace em/en dashes from LLM output with natural punctuation."""
    if not text:
        return text
    text = re.sub(r"\s*[—–]\s*", ", ", text)      # mid-sentence dashes -> comma
    text = re.sub(r",\s*,", ", ", text)            # collapse doubles
    text = re.sub(r",\s*([.!?;:])", r"\1", text)  # comma before punctuation
    return text
