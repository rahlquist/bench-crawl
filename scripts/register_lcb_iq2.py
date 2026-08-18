from pathlib import Path

path = Path("LiveCodeBench/lcb_runner/lm_styles.py")
text = path.read_text()
model = "qwen3-8-27b-ud-iq2-m"
if model in text:
    print("already registered", model)
    raise SystemExit(0)

needle = '''    LanguageModel(
        "qwen3-8-27b-q5-k-m",
        "qwen3-8-27b-q5-k-m",
        LMStyle.OpenAIChat,
        datetime(2026, 1, 1),
        link="http://wimpy.home.lan:8080/v1",
    ),
'''
if needle not in text:
    raise SystemExit("Q5 registration block not found; refusing an ambiguous edit")

addition = '''    LanguageModel(
        "qwen3-8-27b-ud-iq2-m",
        "qwen3-8-27b-ud-iq2-m",
        LMStyle.OpenAIChat,
        datetime(2026, 1, 1),
        link="http://wimpy.home.lan:8080/v1",
    ),
'''
path.write_text(text.replace(needle, needle + addition, 1))
print("registered", model)
