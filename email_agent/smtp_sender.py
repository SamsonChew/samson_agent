"""Send the digest through Gmail SMTP."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage


def send_html(user: str, app_password: str, to: str, subject: str, html: str,
              host: str = "smtp.gmail.com", port: int = 465) -> None:
    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content("这封摘要是 HTML 格式，请用支持 HTML 的邮件客户端查看。")
    msg.add_alternative(html, subtype="html")
    with smtplib.SMTP_SSL(host, port, timeout=60) as smtp:
        smtp.login(user, app_password)
        smtp.send_message(msg)
