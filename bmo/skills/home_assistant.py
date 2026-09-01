import requests


# ─── Home Assistant ───────────────────────────────────────────────────────────
class HomeAssistantSkill:
    def __init__(self, cfg):
        self.url   = cfg.get("home_assistant_url", "").rstrip("/")
        self.token = cfg.get("home_assistant_token", "")
        self.enabled = bool(self.url and self.token)
        if self.enabled:
            print("[HA] Home Assistant configured.", flush=True)

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

    def _call(self, domain, service, entity_id):
        if not self.enabled:
            return "Home Assistant is not configured."
        try:
            url = f"{self.url}/api/services/{domain}/{service}"
            requests.post(url, headers=self._headers(),
                          json={"entity_id": entity_id}, timeout=5)
            action = service.replace("_", " ")
            entity = entity_id.split(".")[-1].replace("_", " ")
            return f"Turning {action.split('turn_')[-1]} {entity}."
        except Exception as e:
            return f"Home Assistant error: {e}"

    def light_on(self, entity):
        return self._call("light", "turn_on", entity)

    def light_off(self, entity):
        return self._call("light", "turn_off", entity)

    def toggle(self, entity):
        domain = entity.split(".")[0]
        return self._call(domain, "toggle", entity)

    def status(self, entity):
        if not self.enabled:
            return "Home Assistant is not configured."
        try:
            url = f"{self.url}/api/states/{entity}"
            r   = requests.get(url, headers=self._headers(), timeout=5).json()
            state = r.get("state", "unknown")
            name  = r.get("attributes", {}).get("friendly_name",
                           entity.split(".")[-1].replace("_", " "))
            attrs = r.get("attributes", {})
            unit  = attrs.get("unit_of_measurement", "")
            return f"{name} is {state}{' ' + unit if unit else ''}."
        except Exception as e:
            return f"Home Assistant error: {e}"

    def list_entities(self):
        if not self.enabled:
            return "Home Assistant is not configured."
        try:
            url = f"{self.url}/api/states"
            states = requests.get(url, headers=self._headers(), timeout=5).json()
            lights   = [s["entity_id"] for s in states if s["entity_id"].startswith("light.")][:5]
            switches = [s["entity_id"] for s in states if s["entity_id"].startswith("switch.")][:5]
            result   = []
            if lights:   result.append("Lights: " + ", ".join(lights))
            if switches: result.append("Switches: " + ", ".join(switches))
            return ". ".join(result) or "No entities found."
        except Exception as e:
            return f"Error: {e}"
