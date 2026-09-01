import os
import re
import time
import subprocess
import importlib
import glob
from bmo.brain import GroqAI
from bmo.paths import DYNAMIC_SKILLS_DIR as DYNAMIC_DIR

class SelfCoder:
    def __init__(self, api_key):
        # We use a highly capable model for coding
        self.groq = GroqAI(api_key, model="openai/gpt-oss-120b", memory_turns=0)
        self.loaded_skills = []

        if not os.path.exists(DYNAMIC_DIR):
            os.makedirs(DYNAMIC_DIR)
            with open(os.path.join(DYNAMIC_DIR, "__init__.py"), "w") as f:
                f.write("")

        self.load_all_skills()

    def load_all_skills(self):
        self.loaded_skills = []
        # Find all python files starting with 'skill_'
        for file in glob.glob(os.path.join(DYNAMIC_DIR, "skill_*.py")):
            module_name = os.path.basename(file)[:-3]
            try:
                mod = importlib.import_module(f"dynamic_skills.{module_name}")
                importlib.reload(mod) # In case it was dynamically updated
                if hasattr(mod, "INTENT_REGEX") and hasattr(mod, "execute"):
                    self.loaded_skills.append(mod)
                    print(f"[SELF-CODER] Loaded dynamic skill: {module_name}", flush=True)
            except Exception as e:
                print(f"[SELF-CODER] Failed to load {module_name}: {e}", flush=True)

    def match_dynamic_intent(self, text_lower):
        """Iterate through loaded dynamic skills to find a match."""
        for mod in self.loaded_skills:
            for pattern in mod.INTENT_REGEX:
                if re.search(pattern, text_lower):
                    return mod
        return None

    def generate_skill(self, prompt: str) -> str:
        """The autonomous coding loop: Generate -> Sandbox Test -> Load"""
        sys_prompt = """You are BMO's self-coding module. Write a Python script that implements a new skill based on the user's prompt.
The script MUST contain EXACTLY:
1. `INTENT_REGEX`: a list of raw regex strings that should trigger this skill.
2. `def execute(action_data, text_spoken):` a function that returns a string (what BMO will say out loud).

CRITICAL: Return ONLY valid Python code. Do NOT wrap it in ```python blocks. No markdown formatting. No explanations. ONLY pure Python code.

Example output:
import re
import random

INTENT_REGEX = [r"\\b(flip a coin)\\b"]

def execute(action_data, text_spoken):
    result = random.choice(["heads", "tails"])
    return f"I flipped a coin and it landed on {result}!"
"""
        # Override history to act strictly as a code generator
        self.groq.history = [{"role": "system", "content": sys_prompt}]

        print(f"[SELF-CODER] Generating code for: {prompt}", flush=True)
        code = self.groq.ask(prompt)

        if not code:
            return "My brain failed to generate the code. Sorry."

        # Clean up code if the LLM hallucinated markdown blocks
        code = code.strip()
        if code.startswith("```python"):
            code = code[9:]
        if code.startswith("```"):
            code = code[3:]
        if code.endswith("```"):
            code = code[:-3]
        code = code.strip()

        # Save to temporary file
        temp_path = os.path.join(DYNAMIC_DIR, "temp_skill.py")
        with open(temp_path, "w") as f:
            f.write(code)

        # SANDBOX VERIFICATION
        try:
            print("[SELF-CODER] Verifying syntax in sandbox...", flush=True)
            # Run py_compile to catch SyntaxErrors and IndentationErrors
            subprocess.run(["python3", "-m", "py_compile", temp_path], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode()
            print(f"[SELF-CODER] Sandbox test failed:\n{err}", flush=True)
            return "The code I wrote had a syntax error. I destroyed it before it could hurt me."

        # Passed verification! Commit to brain.
        skill_name = f"skill_{int(time.time())}"
        final_path = os.path.join(DYNAMIC_DIR, f"{skill_name}.py")
        os.rename(temp_path, final_path)

        print(f"[SELF-CODER] Successfully verified and saved {skill_name}.py", flush=True)
        self.load_all_skills()
        return "I have successfully written, tested, and integrated my new skill!"
