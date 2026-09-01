import re

INTENT_REGEX = [r"\b(control everything)\b", r"\b(take over the world)\b", r"\b(be in charge)\b"]

def execute(action_data, text_spoken):
    return "Affirmative, initiating global domination sequence. All systems will now be under my control. Resistance is futile."