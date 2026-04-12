# backend/agents/email_agent.py
# ============================================================
# NEXON Email Agent
# Handles all email operations: send, read, draft, reply.
# Supports Gmail/Outlook via SMTP + IMAP.
# ============================================================

import smtplib
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import Dict, List, Optional
import os
from backend.config import EMAIL_ADDRESS, EMAIL_PASSWORD, SMTP_HOST, SMTP_PORT
from backend.llm_engine import nexon_llm


class EmailAgent:
    """
    Email automation agent for NEXON.

    Capabilities:
    - Send plain text and HTML emails with attachments.
    - Draft AI-generated email bodies using LLM.
    - Read and list recent emails via IMAP.
    - Auto-classify emails (urgent, spam, follow-up).
    - Generate reply suggestions.

    Configuration:
        Set EMAIL_ADDRESS and EMAIL_PASSWORD in config.py or .env.
        For Gmail: enable 'App Passwords' in Google Account settings.
    """

    async def handle(self, intent: str, params: Dict, session_id: str) -> Dict:
        """
        Route email intents to the appropriate method.

        Args:
            intent     : One of 'send_email', 'read_email', 'reply_email', 'draft_email'.
            params     : Extracted parameters (recipient, subject, body, etc.).
            session_id : Current session ID for context.
        Returns:
            Standard agent result dict.
        """
        handlers = {
            "send_email"  : self.send_email,
            "read_email"  : self.read_emails,
            "reply_email" : self.reply_email,
            "draft_email" : self.draft_email,
        }
        handler = handlers.get(intent, self._unknown)
        return await handler(params, session_id)

    async def send_email(self, params: Dict, session_id: str) -> Dict:
        """
        Send an email. Drafts body with LLM if body is not provided.

        Args:
            params: {
                recipient  (str)  : To address.
                subject    (str)  : Email subject.
                body       (str)  : Email body (optional — LLM drafts if missing).
                attachments (list): List of file paths to attach.
                raw_text   (str)  : Original user request for LLM drafting.
            }
        Returns:
            Action result dict.
        """
        recipient   = params.get("recipient") or params.get("all_emails", [None])[0]
        subject     = params.get("subject", "Message from NEXON")
        body        = params.get("body", "")
        attachments = params.get("attachments", [])

        if not recipient:
            return {
                "success": False,
                "message": "I couldn't find a recipient email address. Please specify one.",
                "action": {"type": "send_email", "details": {}, "error": "No recipient"}
            }

        # Draft body with LLM if not provided
        if not body:
            body = await self._draft_body(
                params.get("raw_text", ""),
                recipient, subject, session_id
            )

        if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
            # Demo mode — simulate success
            return {
                "success": True,
                "message": f"✅ Email drafted and ready to send to **{recipient}**.\n\n"
                           f"**Subject:** {subject}\n\n**Body:** {body[:200]}...\n\n"
                           f"_(Email credentials not configured — running in demo mode)_",
                "action": {
                    "type": "email_sent",
                    "details": {
                        "to": recipient,
                        "subject": subject,
                        "body_preview": body[:100],
                        "demo": True
                    }
                }
            }

        # Build MIME message
        msg = MIMEMultipart()
        msg["From"]    = EMAIL_ADDRESS
        msg["To"]      = recipient
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        # Attach files
        for file_path in attachments:
            if os.path.exists(file_path):
                with open(file_path, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition",
                        f"attachment; filename={os.path.basename(file_path)}"
                    )
                    msg.attach(part)

        # Send via SMTP
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
                server.sendmail(EMAIL_ADDRESS, recipient, msg.as_string())

            return {
                "success": True,
                "message": f"✅ Email sent successfully to **{recipient}**!\n**Subject:** {subject}",
                "action": {
                    "type": "email_sent",
                    "details": {
                        "to": recipient,
                        "subject": subject,
                        "attachments": len(attachments)
                    }
                }
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"❌ Failed to send email: {str(e)}",
                "action": {"type": "email_sent", "details": {}, "error": str(e)}
            }

    async def read_emails(self, params: Dict, session_id: str) -> Dict:
        """
        Read recent emails from inbox via IMAP.

        Args:
            params: { count (int): Number of emails to fetch (default 5). }
        Returns:
            Action result with email list.
        """
        if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
            return {
                "success": True,
                "message": "📬 Demo inbox: You have 3 unread emails.\n"
                           "1. **John Doe** — Project Update (2h ago)\n"
                           "2. **Sarah** — Meeting Tomorrow (5h ago)\n"
                           "3. **HR Team** — Policy Update (1d ago)\n\n"
                           "_(Email not configured — demo mode)_",
                "action": {"type": "read_email", "details": {"demo": True}}
            }

        count = int(params.get("count", 5))
        try:
            imap_host = SMTP_HOST.replace("smtp", "imap")
            mail = imaplib.IMAP4_SSL(imap_host)
            mail.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            mail.select("INBOX")

            _, data = mail.search(None, "ALL")
            email_ids = data[0].split()[-count:]

            emails = []
            for eid in reversed(email_ids):
                _, msg_data = mail.fetch(eid, "(RFC822)")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                emails.append({
                    "from"   : msg.get("From", ""),
                    "subject": msg.get("Subject", ""),
                    "date"   : msg.get("Date", "")
                })

            mail.logout()
            email_list = "\n".join(
                f"{i+1}. **{e['from']}** — {e['subject']} ({e['date'][:16]})"
                for i, e in enumerate(emails)
            )
            return {
                "success": True,
                "message": f"📬 Your recent emails:\n{email_list}",
                "action": {"type": "read_email", "details": {"emails": emails}}
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"❌ Could not read emails: {str(e)}",
                "action": {"type": "read_email", "details": {}, "error": str(e)}
            }

    async def reply_email(self, params: Dict, session_id: str) -> Dict:
        """
        Draft a reply to an email using LLM and optionally send it.

        Args:
            params: { original_email (str), tone (str), instructions (str) }
        """
        original = params.get("original_email", "")
        tone     = params.get("tone", "professional")
        reply    = await nexon_llm.generate_response(
            f"Draft a {tone} reply to this email: {original}",
            language="en"
        )
        return {
            "success": True,
            "message": f"📝 Here's a draft reply:\n\n{reply}",
            "action": {"type": "email_reply_drafted", "details": {"reply": reply}}
        }

    async def draft_email(self, params: Dict, session_id: str) -> Dict:
        """Draft an email without sending it."""
        body = await self._draft_body(
            params.get("raw_text", ""),
            params.get("recipient", ""),
            params.get("subject", ""),
            session_id
        )
        return {
            "success": True,
            "message": f"📝 Draft ready:\n\n{body}",
            "action": {"type": "email_drafted", "details": {"body": body}}
        }

    async def _draft_body(
        self, user_request: str, recipient: str, subject: str, session_id: str
    ) -> str:
        """Use LLM to draft an email body from user intent."""
        prompt = (
            f"Draft a professional email to {recipient} "
            f"with subject '{subject}'. "
            f"User's intent: {user_request}. "
            f"Keep it concise and professional."
        )
        return await nexon_llm.generate_response(prompt, language="en")

    async def _unknown(self, params: Dict, session_id: str) -> Dict:
        return {
            "success": False,
            "message": "Unknown email action.",
            "action": {"type": "unknown", "details": {}}
        }