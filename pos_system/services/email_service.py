import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication


def get_smtp_config():
    return {
        'host': os.environ.get('SMTP_HOST', ''),
        'port': int(os.environ.get('SMTP_PORT', '587') or 587),
        'user': os.environ.get('SMTP_USER', ''),
        'password': os.environ.get('SMTP_PASSWORD', ''),
        'from': os.environ.get('SMTP_FROM', os.environ.get('SMTP_USER', '')),
        'use_tls': os.environ.get('SMTP_USE_TLS', '1') != '0',
    }


def send_receipt_email(to_email, subject, body, pdf_bytes=None, filename='receipt.pdf'):
    cfg = get_smtp_config()
    if not cfg['host']:
        return False, 'Email not configured (SMTP_HOST missing)'
    if not to_email or '@' not in to_email:
        return False, 'Invalid recipient email'
    try:
        msg = MIMEMultipart()
        msg['From'] = cfg['from'] or cfg['user']
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body or '', 'plain', 'utf-8'))
        if pdf_bytes:
            part = MIMEApplication(pdf_bytes, _subtype='pdf')
            part.add_header('Content-Disposition', 'attachment', filename=filename)
            msg.attach(part)
        with smtplib.SMTP(cfg['host'], cfg['port'], timeout=20) as server:
            if cfg['use_tls']:
                server.starttls()
            if cfg['user']:
                server.login(cfg['user'], cfg['password'])
            server.send_message(msg)
        return True, 'Email sent'
    except Exception as e:
        return False, str(e)
