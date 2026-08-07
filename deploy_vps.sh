#!/bin/bash
# Deploy Shop With DD POS on a Hostinger VPS (Ubuntu 22.04)
# Run as root:  bash deploy_vps.sh
set -e

# ================= CONFIGURATION (EDIT THESE) =================
REPO_URL="https://github.com/facinetkeita32-sys/DD.git"
APP_DIR="/opt/shopdd"
DB_NAME="shopdd"
DB_USER="pos"
DB_PASS="CHANGE_ME_STRONG_PASSWORD"
SECRET_KEY="CHANGE_ME_RANDOM_SECRET"
DOMAIN="yourdomain.com"
# ==============================================================

echo "==> Updating system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get upgrade -y

echo "==> Installing packages"
apt-get install -y python3 python3-venv python3-pip git postgresql postgresql-contrib nginx curl

echo "==> Creating app user"
id -u pos >/dev/null 2>&1 || useradd -m -s /bin/bash pos

echo "==> Setting up PostgreSQL"
su - postgres -c "psql -c \"CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';\""
su - postgres -c "psql -c \"CREATE DATABASE $DB_NAME OWNER $DB_USER;\""

echo "==> Cloning repository"
rm -rf "$APP_DIR"
git clone "$REPO_URL" "$APP_DIR"
chown -R pos:pos "$APP_DIR"

echo "==> Installing Python dependencies"
cd "$APP_DIR"
su - pos -c "cd $APP_DIR && python3 -m venv venv"
su - pos -c "cd $APP_DIR && ./venv/bin/pip install --upgrade pip"
su - pos -c "cd $APP_DIR && ./venv/bin/pip install -r requirements.txt gunicorn"

echo "==> Writing environment file"
cat > "$APP_DIR/.env" <<EOF
SECRET_KEY=$SECRET_KEY
DATABASE_URL=postgresql://$DB_USER:$DB_PASS@localhost:5432/$DB_NAME
EOF
chown pos:pos "$APP_DIR/.env"
chmod 600 "$APP_DIR/.env"

echo "==> Creating systemd service"
cat > /etc/systemd/system/shopdd.service <<EOF
[Unit]
Description=Shop With DD POS
After=network.target postgresql.service

[Service]
Type=simple
User=pos
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/gunicorn pos_system.main:app --bind 127.0.0.1:8000 --workers 1 --timeout 120
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

echo "==> Configuring Nginx"
cat > /etc/nginx/sites-available/shopdd <<EOF
server {
    listen 80;
    server_name $DOMAIN;

    client_max_body_size 20M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
ln -sf /etc/nginx/sites-available/shopdd /etc/nginx/sites-enabled/shopdd
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx
systemctl restart nginx

systemctl daemon-reload
systemctl enable shopdd

echo ""
echo "======================================================"
echo " SERVER SETUP DONE - APP NOT STARTED YET"
echo "======================================================"
echo " IMPORTANT: restore your data from Supabase BEFORE"
echo " starting the app (otherwise demo data is seeded)."
echo ""
echo " 1. On this VPS, dump your Supabase database:"
echo "    pg_dump \"postgresql://postgres.YOURREF:YOURPASS@db.YOURREF.supabase.co:5432/postgres\" --no-owner -f dump.sql"
echo ""
echo " 2. Restore it into the local database:"
echo "    pg_restore --dbname=\"postgresql://$DB_USER:$DB_PASS@localhost:5432/$DB_NAME\" --no-owner dump.sql"
echo "    (or if dump.sql is plain text, use: psql \"postgresql://$DB_USER:$DB_PASS@localhost:5432/$DB_NAME\" < dump.sql)"
echo ""
echo " 3. Start the app:"
echo "    systemctl start shopdd"
echo ""
echo " 4. Add HTTPS:  certbot --nginx -d $DOMAIN"
echo ""
echo " Check logs:  journalctl -u shopdd -f"
echo "======================================================"
