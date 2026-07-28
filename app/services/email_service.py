"""
Email service — SendGrid integration.
"""
import logging
from app.config import settings

logger = logging.getLogger("safeher.email")


class EmailService:

    @staticmethod
    async def send_email(to: str, subject: str, html_body: str) -> bool:
        if not settings.SENDGRID_API_KEY:
            logger.warning("SendGrid not configured — email not sent")
            return False

        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail

            message = Mail(
                from_email=(settings.FROM_EMAIL, settings.FROM_NAME),
                to_emails=to,
                subject=subject,
                html_content=html_body,
            )
            sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
            response = sg.send(message)
            logger.info("Email sent to %s (status %d)", to, response.status_code)
            return response.status_code == 202
        except Exception as exc:
            logger.error("Email failed to %s: %s", to, exc)
            return False


    @staticmethod
    async def send_welcome_email(to: str, name: str) -> bool:
        html = f"""
        <html><body style="font-family:sans-serif;color:#333;">
        <h2>Welcome to SafeHer, {name}!</h2>
        <p>Your safety is our priority. Here's what you can do next:</p>
        <ul>
            <li>Add emergency contacts</li>
            <li>Configure your SOS settings</li>
            <li>Try the AI safety assistant Aria</li>
            <li>Explore nearby safe places</li>
        </ul>
        <p>Stay safe. We're here 24/7.</p>
        <p>— The SafeHer Team</p>
        </body></html>
        """
        return await EmailService.send_email(to, f"Welcome to SafeHer, {name}!", html)


    @staticmethod
    async def send_password_reset_email(to: str, reset_url: str) -> bool:
        html = f"""
        <html><body style="font-family:sans-serif;">
        <h2>Reset Your SafeHer Password</h2>
        <p>Click the link below to reset your password:</p>
        <p><a href="{reset_url}" style="padding:12px 24px;background:#f0065e;color:#fff;text-decoration:none;border-radius:8px;">Reset Password</a></p>
        <p>This link expires in 1 hour.</p>
        <p>If you didn't request this, please ignore this email.</p>
        </body></html>
        """
        return await EmailService.send_email(to, "SafeHer — Password Reset", html)


    @staticmethod
    async def send_sos_email(to: str, user_name: str, tracking_url: str, lat: float | None, lng: float | None) -> bool:
        location_link = f"https://maps.google.com/?q={lat},{lng}" if lat and lng else "N/A"
        html = f"""
        <html><body style="font-family:sans-serif;color:#333;">
        <h2 style="color:#ef4444;">🆘 EMERGENCY ALERT</h2>
        <p><strong>{user_name}</strong> has activated the SafeHer SOS button and may need immediate help.</p>
        <p><strong>Live Tracking:</strong> <a href="{tracking_url}" style="color:#f0065e;">{tracking_url}</a></p>
        <p><strong>Last Known Location:</strong> <a href="{location_link}" style="color:#f0065e;">View on Map</a></p>
        <p style="margin-top:24px;">Please call her immediately or go to her location.</p>
        <p>— SafeHer Safety Team</p>
        </body></html>
        """
        return await EmailService.send_email(to, f"🆘 EMERGENCY: {user_name} needs help", html)
