# POS Deployment Notes

## Server
- Provider: Hostinger VPS (`srv1887188`)
- SSH: `ssh root@2.25.99.2` (or the hostname)
- OS: Ubuntu 24.04
- Live app: https://pos-shopwithdd.online

## Deploy
Backend changes:
```
ssh root@2.25.99.2
cd /opt/shopdd && git pull
sudo systemctl restart shopdd
```
Frontend-only changes: `git pull` on the server, then hard-refresh the browser.

## App
- systemd service: `shopdd` (gunicorn, bind `127.0.0.1:8000`, User=pos, WorkingDirectory=/opt/shopdd)
- Database: PostgreSQL `shopdd` / user `pos`; psql at `/usr/lib/postgresql/17/bin/psql`

## SMTP (Hostinger mailbox)
Env vars for `/etc/systemd/system/shopdd.service.d/smtp.conf` override:
- SMTP_HOST=smtp.hostinger.com
- SMTP_PORT=587
- SMTP_USER=info@pos-shopwithdd.online
- SMTP_PASS=qBU4B!2ybXhe
- MAIL_FROM=info@pos-shopwithdd.online
At least one admin user must have an email set (Users screen) for emailed reports/receipts.
