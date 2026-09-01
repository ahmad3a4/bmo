import re

INTENT_REGEX = [r"\b(control my phone)\b", r"\b(use my phone)\b", r"\b(access my phone)\b"]

def execute(action_data, text_spoken):
    return "I'm not capable of directly controlling your phone, but I can guide you through various phone-related tasks or provide information on how to use your phone's features. What would you like to do?"