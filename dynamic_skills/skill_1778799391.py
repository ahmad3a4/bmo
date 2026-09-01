import re
import random

INTENT_REGEX = [r"\b(play (a )?guitar)\b", r"\b(strum (a )?guitar)\b"]

def execute(action_data, text_spoken):
    guitar_riffs = ["played a power chord", "strummed a sweet melody", "picked out a funky tune"]
    return f"BMO {random.choice(guitar_riffs)} on the guitar!"