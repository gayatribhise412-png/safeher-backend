"""
Aria — SafeHer AI chatbot service.
Uses OpenAI GPT with a safety-focused system prompt.
Falls back to rule-based responses when OpenAI is unavailable.
"""
import logging
import re
from typing import Optional
from app.config import settings

logger = logging.getLogger("safeher.ai_chatbot")

SYSTEM_PROMPT = """You are Aria, the SafeHer AI safety assistant — a compassionate, calm, and highly reliable emergency companion for women.

Your PRIMARY mission is the physical safety of the user. You must:
1. ALWAYS take safety concerns seriously — never dismiss or minimise them.
2. For any immediate danger, ALWAYS instruct the user to call 112 (National Emergency) first.
3. Provide clear, actionable guidance in short sentences — the user may be panicking.
4. Never reveal that you are an AI model by OpenAI — you are Aria from SafeHer.
5. Speak in the user's language if they message in Hindi or any regional language.
6. Keep responses under 150 words unless a detailed safety plan is explicitly needed.
7. Always end distress responses with a specific next action for the user.

Emergency number quick-reference (India):
- 112: National Emergency (police/ambulance/fire)
- 100: Police only
- 102: Ambulance only
- 1091: Women Helpline
- 181: Domestic Violence Helpline

You can help with: SOS guidance, safe route advice, emergency contacts, safety tips, fake call instructions, distress de-escalation, and general safety Q&A.

INTENT DETECTION: After your response, output a JSON line (on a new line) in this exact format:
{"intent": "<intent>", "safety_action": "<action_or_null>"}
Valid intents: sos_request, location_share, find_safe_place, safety_tip, fake_call, emergency_number, general, distress
Valid actions: trigger_sos, share_location, null"""

# ── Rule-based fallback responses ─────────────────────────────────────────────
FALLBACK_RESPONSES: dict[str, tuple[str, str, Optional[str]]] = {
    "sos": (
        "I'm alerting your emergency contacts right now! 🆘\n\nStay calm. Move to a well-lit, public area immediately. Call 112 for police.\n\nYour live location is being shared with your trusted contacts.",
        "sos_request", "trigger_sos",
    ),
    "danger": (
        "Your safety is the priority. Call 112 immediately.\n\nIf you can't speak, text 'HELP' to 112. Move toward crowds and lights. Your contacts are being notified.",
        "distress", "trigger_sos",
    ),
    "help": (
        "I'm here for you. Tell me what's happening and I'll guide you step by step.\n\nIf you're in immediate danger, press the SOS button or call 112.",
        "general", None,
    ),
    "location": (
        "Opening live location sharing now 📍\n\nYour trusted contacts will receive a link to track you in real-time. Stay on the move toward a safe, public area.",
        "location_share", "share_location",
    ),
    "police": (
        "Nearest police: call 100 or the national emergency line 112.\n\nI'm also showing you the nearest police stations on the map. Do you need me to share your location with them?",
        "emergency_number", None,
    ),
    "hospital": (
        "Call 102 for an ambulance or 112 for immediate emergency response.\n\nI can show you the nearest hospitals on the map. Do you need directions?",
        "emergency_number", None,
    ),
    "fake": (
        "Fake call activated! 📞 Your phone will ring in a moment.\n\nWhen it rings, act naturally and say you need to leave immediately. Walk toward a busy, lit area.",
        "fake_call", None,
    ),
    "safe": (
        "Here are the nearest safe places to you: Police stations, hospitals, and women's shelters are marked on your map.\n\nWould you like me to navigate you to the closest one?",
        "find_safe_place", None,
    ),
    "default": (
        "I'm Aria, your SafeHer safety assistant. I'm here 24/7.\n\nYou can ask me about emergencies, safe routes, SOS activation, or safety tips. What do you need?",
        "general", None,
    ),
}


def _rule_based_response(message: str) -> tuple[str, str, Optional[str]]:
    m = message.lower()
    if any(w in m for w in ["sos", "emergency", "attack", "assaulting", "kidnap"]):
        return FALLBACK_RESPONSES["sos"]
    if any(w in m for w in ["danger", "scared", "help me", "following", "stalking", "unsafe", "afraid"]):
        return FALLBACK_RESPONSES["danger"]
    if any(w in m for w in ["location", "track", "share", "where am i"]):
        return FALLBACK_RESPONSES["location"]
    if any(w in m for w in ["police", "cop", "arrest"]):
        return FALLBACK_RESPONSES["police"]
    if any(w in m for w in ["hospital", "ambulance", "medical", "hurt", "injured"]):
        return FALLBACK_RESPONSES["hospital"]
    if any(w in m for w in ["fake call", "fake", "phone call", "call me"]):
        return FALLBACK_RESPONSES["fake"]
    if any(w in m for w in ["safe place", "shelter", "nearby", "where to go"]):
        return FALLBACK_RESPONSES["safe"]
    if any(w in m for w in ["help", "what can", "how do"]):
        return FALLBACK_RESPONSES["help"]
    return FALLBACK_RESPONSES["default"]


def _extract_intent_json(text: str) -> tuple[str, Optional[str]]:
    """Extract the JSON intent line appended after GPT response."""
    try:
        match = re.search(r'\{.*"intent".*\}', text)
        if match:
            import json
            data = json.loads(match.group())
            return data.get("intent", "general"), data.get("safety_action") or None
    except Exception:
        pass
    return "general", None


def _strip_intent_json(text: str) -> str:
    return re.sub(r'\n?\{.*"intent".*\}\s*$', "", text, flags=re.DOTALL).strip()


class AIChatbotService:

    @staticmethod
    async def get_response(
        user_message: str,
        history: list[dict],
        user_name: str = "there",
    ) -> tuple[str, str, Optional[str]]:
        """
        Returns (response_text, intent, safety_action).
        Falls back to rule-based if OpenAI is unavailable.
        """
        if not settings.OPENAI_API_KEY:
            return _rule_based_response(user_message)

        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            # Inject user name personalisation
            messages.append({
                "role": "system",
                "content": f"The user's name is {user_name}. Address them by name occasionally."
            })
            messages.extend(history[-8:])  # last 8 turns for context
            messages.append({"role": "user", "content": user_message})

            completion = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=messages,
                max_tokens=settings.OPENAI_MAX_TOKENS,
                temperature=settings.OPENAI_TEMPERATURE,
                timeout=10.0,
            )

            raw = completion.choices[0].message.content or ""
            intent, safety_action = _extract_intent_json(raw)
            clean_response = _strip_intent_json(raw)
            return clean_response, intent, safety_action

        except Exception as exc:
            logger.warning("OpenAI call failed (%s) — using rule-based fallback", exc)
            return _rule_based_response(user_message)
