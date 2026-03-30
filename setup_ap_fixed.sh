#!/bin/bash

echo "🚀 PRESENS Monitor - Raspberry Pi Access Point Setup (FIXED)"
echo "============================================================"

# Verificar que se ejecuta como root
if [ "$EUID" -ne 0 ]; then
    echo "❌ Please run as root: sudo ./setup_ap_fixed.sh"
    exit 1
fi

echo "📦 Installing required packages..."
apt update
apt install -y hostapd dnsmasq iptables-persistent

echo "🛑 Stopping services..."
systemctl stop hostapd
systemctl stop dnsmasq
systemctl stop wpa_supplicant

echo "🔧 Disabling wpa_supplicant..."
systemctl disable wpa_supplicant.service
systemctl mask wpa_supplicant.service

# Backup y deshabilitar redes guardadas
if [ -f /etc/wpa_supplicant/wpa_supplicant.conf ]; then
    mv /etc/wpa_supplicant/wpa_supplicant.conf /etc/wpa_supplicant/wpa_supplicant.conf.backup
    echo "✓ Redes WiFi guardadas desactivadas"
fi

echo "⚙️ Configuring hostapd..."
cat > /etc/hostapd/hostapd.conf << 'EOF'
interface=wlan0
driver=nl80211
ssid=PRESENS-Monitor
hw_mode=g
channel=7
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
EOF

# Asegurar que hostapd use el archivo de configuración correcto
sed -i 's|#DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd

echo "🔧 Configuring static IP with dhcpcd..."
# Limpiar configuración previa
sed -i '/# PRESENS Monitor Access Point/,/nohook wpa_supplicant/d' /etc/dhcpcd.conf

# Añadir configuración al final
cat >> /etc/dhcpcd.conf << 'EOF'

# PRESENS Monitor Access Point
interface wlan0
    static ip_address=192.168.4.1/24
    nohook wpa_supplicant
    nohook dhcpcd
EOF

echo "🌐 Configuring dnsmasq..."
# Backup del original
cp /etc/dnsmasq.conf /etc/dnsmasq.conf.backup 2>/dev/null || true

cat > /etc/dnsmasq.conf << 'EOF'
# Interface to bind to
interface=wlan0

# Don't bind to other interfaces
bind-interfaces

# Don't forward queries to upstream DNS
no-resolv

# DHCP range
dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h

# DNS entries
address=/presens.local/192.168.4.1
address=/monitor.local/192.168.4.1
address=/sensor.local/192.168.4.1

# Log for debugging
log-queries
log-dhcp
EOF

echo "🔄 Configuring systemd service dependencies..."

# Crear override para dnsmasq que espere a que dhcpcd configure la interfaz
mkdir -p /etc/systemd/system/dnsmasq.service.d
cat > /etc/systemd/system/dnsmasq.service.d/override.conf << 'EOF'
[Unit]
After=dhcpcd.service hostapd.service
Wants=dhcpcd.service hostapd.service
Requires=hostapd.service

[Service]
# Dar tiempo a que la interfaz esté lista
ExecStartPre=/bin/sleep 5
Restart=on-failure
RestartSec=5
EOF

# Crear override para hostapd
mkdir -p /etc/systemd/system/hostapd.service.d
cat > /etc/systemd/system/hostapd.service.d/override.conf << 'EOF'
[Unit]
After=dhcpcd.service
Wants=dhcpcd.service

[Service]
# Dar tiempo a que la interfaz esté lista
ExecStartPre=/bin/sleep 3
Restart=on-failure
RestartSec=5
EOF

echo "🔥 Configuring iptables (captive portal)..."
iptables -t nat -F PREROUTING 2>/dev/null || true
iptables -t nat -A PREROUTING -i wlan0 -p tcp --dport 80 -j REDIRECT --to-port 5000
iptables -t nat -A PREROUTING -i wlan0 -p tcp --dport 443 -j REDIRECT --to-port 5000
netfilter-persistent save 2>/dev/null || iptables-save > /etc/iptables/rules.v4

echo "📱 Creating PRESENS app service..."
cat > /etc/systemd/system/presens-monitor.service << EOF
[Unit]
Description=PRESENS O2 Monitor
After=network.target dnsmasq.service
Wants=network.target dnsmasq.service

[Service]
Type=simple
User=$SUDO_USER
WorkingDirectory=$(pwd)
ExecStart=$(pwd)/.venv/bin/python $(pwd)/app.py
Restart=always
RestartSec=10
Environment=PYTHONPATH=$(pwd)

[Install]
WantedBy=multi-user.target
EOF

echo "🔄 Enabling services..."
systemctl daemon-reload
systemctl unmask hostapd
systemctl enable hostapd
systemctl enable dnsmasq
systemctl enable presens-monitor.service

echo "✅ Setup completed!"
echo ""
echo "📋 IMPORTANTE - Próximos pasos:"
echo "1. Desconéctate de tu red móvil WiFi"
echo "2. sudo reboot"
echo "3. Después del reinicio:"
echo "   - La Raspberry NO se conectará a ninguna red WiFi"
echo "   - Creará su propia red: 'PRESENS-Monitor' (sin contraseña)"
echo "   - Conéctate desde tu dispositivo a 'PRESENS-Monitor'"
echo "   - Ve a: http://192.168.4.1:5000 o http://presens.local"
echo ""
echo "🔧 Troubleshooting:"
echo "sudo systemctl status hostapd"
echo "sudo systemctl status dnsmasq"
echo "sudo systemctl status presens-monitor"
echo "sudo journalctl -u dnsmasq -n 50"
echo "ip addr show wlan0  # Debe mostrar: 192.168.4.1/24"
