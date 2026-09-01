import re
import random

INTENT_REGEX = [r"\b(flip a coin)\b"]

def execute(action_data, text_spoken):
    result = random.choice(["heads", "tails"])
    return f"I flipped a coin and it landed on {result}!"