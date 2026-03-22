#!/bin/bash
# Amazon Linux 2023 - Desktop + VNC + Chrome + CDP 一键安装脚本
# 用法: sudo bash setup-desktop.sh
set -euo pipefail

echo "============================================"
echo " AL2023 Desktop Environment Setup"
echo " GNOME + TigerVNC + Chrome + CDP"
echo "============================================"

# 检查 root
if [[ $EUID -ne 0 ]]; then
  echo "❌ 请用 root 或 sudo 运行"; exit 1
fi

# 检查内存
MEM_MB=$(free -m | awk '/Mem:/{print $2}')
if [[ $MEM_MB -lt 2000 ]]; then
  echo "⚠️  内存 ${MEM_MB}MB < 2GB，GNOME 可能跑不动，建议 t2.medium 以上"
  read -p "继续？(y/N) " -n1 -r; echo
  [[ ! $REPLY =~ ^[Yy]$ ]] && exit 1
fi

echo ""
echo "[1/6] 安装 GNOME Desktop..."
dnf group install -y Desktop

echo ""
echo "[2/6] 安装 TigerVNC..."
dnf install -y tigervnc-server

echo ""
echo "[3/6] 配置 VNC..."
# 设置 VNC 密码（默认 vncpass，建议自行修改）
mkdir -p /root/.vnc
echo "vncpass" | vncpasswd -f > /root/.vnc/passwd
chmod 600 /root/.vnc/passwd

# xstartup
cat > /root/.vnc/xstartup << 'EOF'
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
exec gnome-session
EOF
chmod +x /root/.vnc/xstartup

# 用户绑定
grep -q ":1=root" /etc/tigervnc/vncserver.users 2>/dev/null || \
  echo ":1=root" >> /etc/tigervnc/vncserver.users

# VNC 全局配置
cat > /etc/tigervnc/vncserver-config-defaults << 'EOF'
session=gnome
securitytypes=vncauth,tlsvnc
geometry=1920x1080
localhost
alwaysshared
EOF

# 启用 VNC 服务
systemctl enable --now vncserver@:1

echo ""
echo "[4/6] 安装 Google Chrome..."
if ! command -v google-chrome &>/dev/null; then
  cat > /etc/yum.repos.d/google-chrome.repo << 'EOF'
[google-chrome]
name=google-chrome
baseurl=https://dl.google.com/linux/chrome/rpm/stable/x86_64
enabled=1
gpgcheck=1
gpgkey=https://dl.google.com/linux/linux_signing_key.pub
EOF
  dnf install -y google-chrome-stable
else
  echo "  Chrome 已安装: $(google-chrome --version)"
fi

echo ""
echo "[5/6] 配置 Chrome CDP 自启服务..."
cat > /etc/systemd/system/chrome-cdp.service << 'EOF'
[Unit]
Description=Google Chrome with CDP (Remote Debugging Port 9222)
After=vncserver@:1.service
Requires=vncserver@:1.service

[Service]
Type=simple
User=root
Environment=DISPLAY=:1
Environment=XAUTHORITY=/root/.Xauthority
ExecStart=/usr/bin/google-chrome --no-sandbox --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-cdp-profile --no-first-run about:blank
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now chrome-cdp.service

echo ""
echo "[6/6] 安装辅助工具..."
dnf install -y ImageMagick 2>/dev/null || true

echo ""
echo "============================================"
echo " ✅ 安装完成!"
echo ""
echo " VNC:    端口 5901 (localhost only)"
echo "         SSH 隧道: ssh -L 5901:localhost:5901 ec2-user@<IP>"
echo "         密码: vncpass (请修改: vncpasswd)"
echo ""
echo " Chrome CDP: http://localhost:9222"
echo "         Playwright 连接:"
echo "         ws_url = requests.get('http://localhost:9222/json/version').json()['webSocketDebuggerUrl']"
echo "         browser = pw.chromium.connect_over_cdp(ws_url)"
echo ""
echo " 截图:   DISPLAY=:1 import -window root /tmp/screenshot.png"
echo "============================================"
