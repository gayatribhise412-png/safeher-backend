"""
SMS sending service — abstracts Twilio SMS API.
"""
import logging
from app.config import settings

logger = logging.getLogger("safeher.sms")


class SMSService:

    @staticmethod
    async def send_sms(to: str, message: str) -> bool:
        """Send SMS via Twilio. Returns True on success."""
        if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
            logger.warning("Twilio credentials not configured — SMS not sent")
            return False

        try:
            from twilio.rest import Client
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            msg = client.messages.create(
                body=message,
                from_=settings.TWILIO_PHONE_NUMBER,
                to=to,
            )
            logger.info("SMS sent: %s → %s (SID: %s)", settings.TWILIO_PHONE_NUMBER, to, msg.sid)
            return True
        except Exception as exc:
            logger.error("SMS failed to %s: %s", to, exc)
            return False


    @staticmethod
    async def send_sos_sms(to: str, user_name: str, tracking_url: str, lat: float | None = None, lng: float | None = None) -> bool:
        location_str = ""
        if lat and lng:
            location_str = f"\nLocation: https://maps.google.com/?q={lat},{lng}"

        message = (
            f"🆘 EMERGENCY ALERT from {user_name}!\n"
            f"She has activated the SafeHer SOS button and may need immediate help.\n"
            f"Live tracking: {tracking_url}{location_str}\n"
            f"Please call her or go to her location immediately."
        )
        return await SMSService.send_sms(to, message)


    @staticmethod
    async def send_whatsapp(to: str, message: str) -> bool:
        """Send WhatsApp message via Twilio sandbox."""
        if not settings.TWILIO_ACCOUNT_SID:
            return False

        try:
            from twilio.rest import Client
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            msg = client.messages.create(
                body=message,
                from_=settings.TWILIO_WHATSAPP_FROM,
                to=f"whatsapp:{to}",
            )
            logger.info("WhatsApp sent: %s → %s", settings.TWILIO_WHATSAPP_FROM, to)
            return True
        except Exception as exc:
            logger.error("WhatsApp failed to %s: %s", to, exc)
            return False
