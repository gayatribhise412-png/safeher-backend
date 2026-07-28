"""
Twilio service — voice calls (SOS callback), SMS, and verify OTP.
"""
import logging
from app.config import settings

logger = logging.getLogger("safeher.twilio")


class TwilioService:

    @staticmethod
    def _get_client():
        if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
            raise RuntimeError("Twilio credentials not configured")
        from twilio.rest import Client
        return Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)


    @staticmethod
    async def make_sos_call(to: str, victim_name: str, tracking_url: str) -> bool:
        """
        Make an automated voice call to an emergency contact.
        TwiML reads a pre-recorded/text-to-speech SOS message.
        """
        try:
            client = TwilioService._get_client()
            twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Aditi" language="en-IN">
        Emergency alert from SafeHer. {victim_name} has activated the emergency SOS button
        and may be in danger. Please call her immediately.
        The live tracking link has been sent to your phone via SMS.
        This is an automated safety alert from SafeHer.
    </Say>
    <Pause length="1"/>
    <Say voice="Polly.Aditi" language="en-IN">Repeating the message.</Say>
    <Say voice="Polly.Aditi" language="en-IN">
        Emergency alert from SafeHer. {victim_name} needs help immediately.
    </Say>
</Response>"""

            call = client.calls.create(
                twiml=twiml,
                to=to,
                from_=settings.TWILIO_PHONE_NUMBER,
            )
            logger.info("SOS call initiated: %s → %s (SID: %s)", settings.TWILIO_PHONE_NUMBER, to, call.sid)
            return True
        except Exception as exc:
            logger.error("SOS call failed to %s: %s", to, exc)
            return False


    @staticmethod
    async def send_otp_sms(to: str, otp: str) -> bool:
        """Send OTP for phone verification."""
        message = f"Your SafeHer verification code is: {otp}. Valid for 10 minutes. Do not share this with anyone."
        try:
            client = TwilioService._get_client()
            msg = client.messages.create(
                body=message,
                from_=settings.TWILIO_PHONE_NUMBER,
                to=to,
            )
            logger.info("OTP sent to %s (SID: %s)", to, msg.sid)
            return True
        except Exception as exc:
            logger.error("OTP send failed to %s: %s", to, exc)
            return False


    @staticmethod
    async def verify_otp(to: str, otp: str) -> bool:
        """Verify OTP using Twilio Verify Service (optional upgrade)."""
        # Basic Redis-based OTP check — Twilio Verify can replace this
        from app.database.redis_client import get_redis
        from app.utils.helpers import sha256
        r = get_redis()
        stored = await r.get(f"otp:{to}")
        return stored == sha256(otp)


    @staticmethod
    async def send_otp_and_store(to: str) -> str:
        """Generate, store and send an OTP. Returns the OTP (for dev/debug only)."""
        import random
        import string
        from app.database.redis_client import get_redis
        from app.utils.helpers import sha256

        otp = "".join(random.choices(string.digits, k=6))
        r = get_redis()
        await r.setex(f"otp:{to}", 600, sha256(otp))  # 10 min TTL
        await TwilioService.send_otp_sms(to, otp)
        return otp  # Only return in non-production
