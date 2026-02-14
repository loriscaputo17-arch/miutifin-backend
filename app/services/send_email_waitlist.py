import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
import os

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM = os.getenv("SMTP_FROM")


def send_waitlist_email(to: str, link: str, name: Optional[str] = None):
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD, SMTP_FROM]):
        raise RuntimeError("SMTP not configured")

    subject = "✨ Sei dentro! Benvenuto su Miutifin"

    greeting = f"Ciao {name}," if name else "Ciao,"
    
    html = f"""
    <html>
      <body style="background:#050505;color:#ffffff;font-family:Arial,sans-serif;padding:40px">
        <div style="max-width:520px;margin:auto;background:#0c0c0c;border-radius:16px;padding:32px">
          
          <h1 style="color:white;">🎉 Benvenuto su Miutifin</h1>

          <p style="color:#cccccc;font-size:14px;">
            {greeting}<br><br>
            la tua richiesta è stata <strong>approvata</strong>.
            Ora puoi accedere a esperienze selezionate, eventi e contenuti esclusivi.
          </p>

          <a href="{link}"
             style="
               display:inline-block;
               margin-top:24px;
               padding:14px 22px;
               background:white;
               color:black;
               text-decoration:none;
               border-radius:10px;
               font-weight:600;
             ">
            Completa la registrazione →
          </a>

          <p style="color:#777;font-size:12px;margin-top:24px;">
            Questo link è personale e può essere usato una sola volta.
          </p>

        </div>
      </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["From"] = SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject

    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM, to, msg.as_string())

    print(f"📨 Invite email sent to {to}")
