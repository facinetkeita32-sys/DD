import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr


def _smtp_settings():
    host = os.environ.get('SMTP_HOST', 'smtp.hostinger.com')
    port = int(os.environ.get('SMTP_PORT', '587'))
    user = os.environ.get('SMTP_USER', '')
    password = os.environ.get('SMTP_PASS', '')
    mail_from = os.environ.get('MAIL_FROM', '') or user
    return host, port, user, password, mail_from


def send_email(to_address, subject, html_body, attachment_name=None, attachment_bytes=None):
    host, port, user, password, mail_from = _smtp_settings()
    if not user or not password:
        raise RuntimeError('SMTP is not configured: set SMTP_USER and SMTP_PASS')
    msg = EmailMessage()
    msg['From'] = formataddr(('ShopDD POS', mail_from))
    msg['To'] = to_address
    msg['Subject'] = subject
    msg.set_content('This email requires an HTML-capable client.')
    msg.add_alternative(html_body, subtype='html')
    if attachment_name and attachment_bytes:
        msg.add_attachment(attachment_bytes, maintype='text', subtype='csv', filename=attachment_name)
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.login(user, password)
        server.send_message(msg)
