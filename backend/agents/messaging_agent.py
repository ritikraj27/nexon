# backend/agents/messaging_agent.py
# ============================================================
# NEXON Messaging Agent
# WhatsApp, SMS (Twilio), Slack, Discord, Telegram.
# ============================================================

from typing import Dict
from backend.config import TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM, SLACK_TOKEN
from backend.llm_engine import nexon_llm


class MessagingAgent:
    """
    Multi-platform messaging agent for NEXON.

    Capabilities:
    - Send SMS via Twilio.
    - Send Slack messages via Slack Web API.
    - Send Discord messages via webhook.
    - Send Telegram messages via Bot API.
    - WhatsApp via Twilio WhatsApp sandbox.
    - Auto-translate messages before sending.
    - Draft contextual replies using LLM.
    """

    async def handle(self, intent: str, params: Dict, session_id: str) -> Dict:
        handlers = {
            "send_message": self.send_message,
            "make_call"   : self.make_call,
        }
        handler = handlers.get(intent, self._unknown)
        return await handler(params, session_id)

    async def send_message(self, params: Dict, session_id: str) -> Dict:
        """
        Send a message on the specified platform.

        Args:
            params: {
                platform  (str): 'sms'|'whatsapp'|'slack'|'discord'|'telegram'.
                to        (str): Recipient (phone number, channel ID, webhook URL).
                message   (str): Message text (LLM-drafted if not provided).
                translate_to (str): Target language for translation (optional).
                raw_text  (str): Original user request.
            }
        """
        platform = params.get("platform", "").lower()
        to       = params.get("to", "")
        message  = params.get("message", "")
        translate_to = params.get("translate_to", "")

        # Draft message with LLM if not provided
        if not message and params.get("raw_text"):
            message = await nexon_llm.generate_response(
                f"Draft a concise message based on: {params['raw_text']}",
                language="en"
            )

        # Translate if requested
        if translate_to and message:
            message = await nexon_llm.generate_response(
                f"Translate this message to {translate_to}: {message}",
                language="en"
            )

        # Route to platform
        if platform in ("sms", "whatsapp"):
            return await self._send_twilio(platform, to, message)
        elif platform == "slack":
            return await self._send_slack(to, message, params)
        elif platform == "discord":
            return await self._send_discord(to, message)
        elif platform == "telegram":
            return await self._send_telegram(to, message, params)
        else:
            # Demo mode
            return {
                "success": True,
                "message": (
                    f"📨 Message ready to send!\n"
                    f"**Platform:** {platform or 'Not specified'}\n"
                    f"**To:** {to or 'Not specified'}\n"
                    f"**Message:** {message[:200]}\n\n"
                    f"_(Configure platform credentials in .env to actually send)_"
                ),
                "action": {
                    "type"   : "message_drafted",
                    "details": {"platform": platform, "to": to, "message": message}
                }
            }

    async def _send_twilio(self, platform: str, to: str, message: str) -> Dict:
        """Send SMS or WhatsApp via Twilio."""
        if not all([TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM]):
            return {
                "success": True,
                "message": f"📱 **Demo {platform.upper()} Message**\nTo: {to}\n\n{message}\n\n_(Twilio not configured)_",
                "action" : {"type": f"{platform}_sent", "details": {"demo": True}}
            }
        try:
            from twilio.rest import Client
            client = Client(TWILIO_SID, TWILIO_TOKEN)
            from_num = f"whatsapp:{TWILIO_FROM}" if platform == "whatsapp" else TWILIO_FROM
            to_num   = f"whatsapp:{to}" if platform == "whatsapp" else to
            msg = client.messages.create(body=message, from_=from_num, to=to_num)
            return {
                "success": True,
                "message": f"✅ {platform.upper()} sent to {to}!\nSID: {msg.sid}",
                "action" : {"type": f"{platform}_sent", "details": {"sid": msg.sid}}
            }
        except Exception as e:
            return {"success": False, "message": f"❌ {platform} failed: {e}", "action": {}}

    async def _send_slack(self, channel: str, message: str, params: Dict) -> Dict:
        """Send a message to a Slack channel."""
        if not SLACK_TOKEN:
            return {
                "success": True,
                "message": f"💬 **Demo Slack Message**\nChannel: #{channel}\n\n{message}\n\n_(Slack token not configured)_",
                "action" : {"type": "slack_sent", "details": {"demo": True}}
            }
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={"Authorization": f"Bearer {SLACK_TOKEN}"},
                    json={"channel": channel, "text": message}
                )
                data = resp.json()
                if data.get("ok"):
                    return {
                        "success": True,
                        "message": f"✅ Slack message sent to #{channel}!",
                        "action" : {"type": "slack_sent", "details": {"channel": channel}}
                    }
                return {"success": False, "message": f"Slack error: {data.get('error')}", "action": {}}
        except Exception as e:
            return {"success": False, "message": f"❌ Slack failed: {e}", "action": {}}

    async def _send_discord(self, webhook_url: str, message: str) -> Dict:
        """Send a message to a Discord channel via webhook."""
        if not webhook_url.startswith("https://discord.com/api/webhooks/"):
            return {
                "success": True,
                "message": f"💬 **Demo Discord Message**\n\n{message}\n\n_(Provide a Discord webhook URL)_",
                "action" : {"type": "discord_sent", "details": {"demo": True}}
            }
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.post(webhook_url, json={"content": message})
                if resp.status_code in (200, 204):
                    return {
                        "success": True,
                        "message": "✅ Discord message sent!",
                        "action" : {"type": "discord_sent", "details": {}}
                    }
                return {"success": False, "message": f"Discord error: {resp.status_code}", "action": {}}
        except Exception as e:
            return {"success": False, "message": f"❌ Discord failed: {e}", "action": {}}

    async def _send_telegram(self, chat_id: str, message: str, params: Dict) -> Dict:
        """Send a message via Telegram Bot API."""
        bot_token = params.get("bot_token", "")
        if not bot_token:
            return {
                "success": True,
                "message": f"💬 **Demo Telegram Message**\nChat: {chat_id}\n\n{message}\n\n_(Set bot_token in params)_",
                "action" : {"type": "telegram_sent", "details": {"demo": True}}
            }
        try:
            import httpx
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"})
                data = resp.json()
                if data.get("ok"):
                    return {"success": True, "message": "✅ Telegram message sent!", "action": {"type": "telegram_sent", "details": {}}}
                return {"success": False, "message": f"Telegram error: {data}", "action": {}}
        except Exception as e:
            return {"success": False, "message": f"❌ Telegram failed: {e}", "action": {}}

    async def make_call(self, params: Dict, session_id: str) -> Dict:
        """Stub: initiate a voice/video call."""
        platform = params.get("platform", "zoom")
        to       = params.get("to", "")
        return {
            "success": True,
            "message": f"📞 Initiating {platform} call to {to}...\n_(Full call integration requires {platform} SDK)_",
            "action" : {"type": "call_initiated", "details": {"platform": platform, "to": to}}
        }

    async def _unknown(self, params: Dict, session_id: str) -> Dict:
        return {"success": False, "message": "Unknown messaging action.", "action": {}}