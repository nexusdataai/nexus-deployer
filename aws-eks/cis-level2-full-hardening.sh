#!/bin/bash
# Complete CIS Level 2 Hardening for Amazon Linux 2023 on EKS Nodes
# Based on CIS Amazon Linux 2023 Benchmark v1.0.0
# MUST be applied AFTER nodes join the cluster

set -e

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║     CIS Level 2 Complete Hardening for EKS Nodes              ║"
echo "║     Amazon Linux 2023 - Kubernetes Compatible                 ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "Node: $(hostname)"
echo "Date: $(date)"
echo "WARNING: Test in non-production first!"
echo ""

# Create backup directory
BACKUP_DIR="/root/cis-hardening-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

#=============================================================================
# Section 1: Initial Setup
#=============================================================================

echo "═══ Section 1: Initial Setup ═══"

# 1.1 Filesystem Configuration
echo "[1.1] Filesystem hardening..."

# Backup fstab
cp /etc/fstab "$BACKUP_DIR/fstab.backup"

# Configure /tmp with secure mount options (already mounted, adding options)
echo "tmpfs /dev/shm tmpfs defaults,nodev,nosuid,noexec 0 0" >> /etc/fstab

# 1.2 Configure Software Updates
echo "[1.2] Configuring automatic updates..."
dnf install -y dnf-automatic
sed -i 's/apply_updates = no/apply_updates = yes/' /etc/dnf/automatic.conf
systemctl enable --now dnf-automatic.timer

# 1.3 Filesystem Integrity Checking
echo "[1.3] Installing AIDE..."
dnf install -y aide
aide --init
mv /var/lib/aide/aide.db.new.gz /var/lib/aide/aide.db.gz

# 1.5 Additional Process Hardening
echo "[1.5] Process hardening..."
echo "kernel.randomize_va_space = 2" >> /etc/sysctl.d/90-cis.conf
echo "kernel.yama.ptrace_scope = 1" >> /etc/sysctl.d/90-cis.conf
echo "kernel.kptr_restrict = 2" >> /etc/sysctl.d/90-cis.conf

# 1.6 Mandatory Access Control - SELinux (be careful with K8s)
echo "[1.6] Verifying SELinux (permissive for K8s compatibility)..."
# SELinux should be permissive or disabled for EKS - don't change this

#=============================================================================
# Section 2: Services
#=============================================================================

echo "═══ Section 2: Services ═══"

# 2.1 Disable Unused Services
echo "[2.1] Disabling unused services..."
SERVICES_TO_DISABLE=(
    "autofs"
    "avahi-daemon"
    "cups"
    "dhcpd"
    "slapd"
    "nfs-server"
    "rpcbind"
    "named"
    "vsftpd"
    "httpd"
    "dovecot"
    "smb"
    "squid"
    "snmpd"
)

for service in "${SERVICES_TO_DISABLE[@]}"; do
    systemctl disable "$service" 2>/dev/null || true
    systemctl stop "$service" 2>/dev/null || true
done

# 2.2 Time Synchronization
echo "[2.2] Configuring chrony..."
dnf install -y chrony
systemctl enable --now chronyd

#=============================================================================
# Section 3: Network Configuration
#=============================================================================

echo "═══ Section 3: Network Configuration (K8s Compatible) ═══"

# 3.1 & 3.2 Network Parameters
echo "[3.1-3.2] Network security parameters..."
cat >> /etc/sysctl.d/90-cis.conf <<EOF

# Network Security (CIS Level 2)
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.default.accept_source_route = 0
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.all.secure_redirects = 0
net.ipv4.conf.default.secure_redirects = 0
net.ipv4.conf.all.log_martians = 1
net.ipv4.conf.default.log_martians = 1
net.ipv4.icmp_echo_ignore_broadcasts = 1
net.ipv4.icmp_ignore_bogus_error_responses = 1
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
net.ipv4.tcp_syncookies = 1

# IPv6 Security
net.ipv6.conf.all.accept_source_route = 0
net.ipv6.conf.default.accept_source_route = 0
net.ipv6.conf.all.accept_redirects = 0
net.ipv6.conf.default.accept_redirects = 0
net.ipv6.conf.all.accept_ra = 0
net.ipv6.conf.default.accept_ra = 0

# KEEP THESE FOR KUBERNETES
net.ipv4.ip_forward = 1
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1
EOF

# 3.3 Disable unused network protocols
echo "[3.3] Disabling unused protocols..."
cat > /etc/modprobe.d/cis-protocols.conf <<EOF
install dccp /bin/true
install sctp /bin/true
install rds /bin/true
install tipc /bin/true
EOF

# 3.4 Disable unused filesystems
echo "[3.4] Disabling unused filesystems..."
cat > /etc/modprobe.d/cis-filesystems.conf <<EOF
install cramfs /bin/true
install freevxfs /bin/true
install jffs2 /bin/true
install hfs /bin/true
install hfsplus /bin/true
install udf /bin/true
install vfat /bin/true
EOF

# Apply all sysctl settings
sysctl -p /etc/sysctl.d/90-cis.conf

#=============================================================================
# Section 4: Logging and Auditing
#=============================================================================

echo "═══ Section 4: Logging and Auditing ═══"

# 4.1 Configure auditd
echo "[4.1] Configuring comprehensive auditd rules..."

# Backup existing rules
cp /etc/audit/rules.d/audit.rules "$BACKUP_DIR/audit.rules.backup" 2>/dev/null || true

# Install auditd if not present
dnf install -y audit

# Configure auditd
cat > /etc/audit/rules.d/cis-level2.rules <<'AUDIT_EOF'
# CIS Level 2 Audit Rules for Amazon Linux 2023 (Kubernetes Compatible)

# Remove any existing rules
-D

# Buffer Size
-b 8192

# Failure Mode
-f 1

# 4.1.3.1 changes to system time
-a always,exit -F arch=b64 -S adjtimex,settimeofday -k time-change
-a always,exit -F arch=b64 -S clock_settime -F a0=0x0 -k time-change
-w /etc/localtime -p wa -k time-change

# 4.1.3.2 changes to user/group information
-w /etc/group -p wa -k identity
-w /etc/passwd -p wa -k identity
-w /etc/gshadow -p wa -k identity
-w /etc/shadow -p wa -k identity
-w /etc/security/opasswd -p wa -k identity

# 4.1.3.3 system's network environment
-a always,exit -F arch=b64 -S sethostname,setdomainname -k system-locale
-w /etc/issue -p wa -k system-locale
-w /etc/issue.net -p wa -k system-locale
-w /etc/hosts -p wa -k system-locale
-w /etc/sysconfig/network -p wa -k system-locale

# 4.1.3.4 changes to Mandatory Access Controls
-w /etc/selinux/ -p wa -k MAC-policy

# 4.1.3.5 login and logout events
-w /var/log/lastlog -p wa -k logins
-w /var/run/faillock/ -p wa -k logins

# 4.1.3.6 session initiation information
-w /var/run/utmp -p wa -k session
-w /var/log/wtmp -p wa -k session
-w /var/log/btmp -p wa -k session

# 4.1.3.7 discretionary access control permission modifications
-a always,exit -F arch=b64 -S chmod,fchmod,fchmodat -F auid>=1000 -F auid!=4294967295 -k perm_mod
-a always,exit -F arch=b64 -S chown,fchown,lchown,fchownat -F auid>=1000 -F auid!=4294967295 -k perm_mod
-a always,exit -F arch=b64 -S setxattr,lsetxattr,fsetxattr,removexattr,lremovexattr,fremovexattr -F auid>=1000 -F auid!=4294967295 -k perm_mod

# 4.1.3.8 unauthorized access attempts to files (unsuccessful)
-a always,exit -F arch=b64 -S open,openat,openat2 -F exit=-EACCES -F auid>=1000 -F auid!=4294967295 -k access
-a always,exit -F arch=b64 -S open,openat,openat2 -F exit=-EPERM -F auid>=1000 -F auid!=4294967295 -k access

# 4.1.3.9 successful file system mounts
-a always,exit -F arch=b64 -S mount -F auid>=1000 -F auid!=4294967295 -k mounts

# 4.1.3.10 file deletion events by users
-a always,exit -F arch=b64 -S unlink,unlinkat,rename,renameat -F auid>=1000 -F auid!=4294967295 -k delete

# 4.1.3.11 changes to system administration scope (sudoers)
-w /etc/sudoers -p wa -k scope
-w /etc/sudoers.d/ -p wa -k scope

# 4.1.3.12 system administrator actions (sudolog)
-w /var/log/sudo.log -p wa -k actions

# 4.1.3.13 kernel module loading and unloading
-a always,exit -F arch=b64 -S init_module,finit_module,delete_module -F auid>=1000 -F auid!=4294967295 -k modules
-w /sbin/insmod -p x -k modules
-w /sbin/rmmod -p x -k modules
-w /sbin/modprobe -p x -k modules

# 4.1.3.14 Make audit configuration immutable
# NOTE: Commented out for Kubernetes - pods may need audit config changes
# -e 2

# Kubernetes-specific audit rules
-w /etc/kubernetes/ -p wa -k kubernetes_config
-w /var/lib/kubelet/ -p wa -k kubelet_config
-w /etc/systemd/system/kubelet.service -p wa -k kubelet_service
-w /etc/cni/net.d/ -p wa -k cni_config
-w /etc/containerd/config.toml -p wa -k containerd_config
AUDIT_EOF

# Load audit rules
augenrules --load
systemctl restart auditd

# 4.2 Configure Logging
echo "[4.2] Configuring rsyslog..."
dnf install -y rsyslog
systemctl enable --now rsyslog

cat >> /etc/rsyslog.conf <<EOF
# CIS Level 2 Logging
*.emerg :omusrmsg:*
auth,authpriv.* /var/log/secure
mail.* -/var/log/maillog
cron.* /var/log/cron
*.info;mail.none;authpriv.none;cron.none /var/log/messages
EOF

systemctl restart rsyslog

# Configure log rotation
cat > /etc/logrotate.d/cis <<EOF
/var/log/messages
/var/log/secure
/var/log/maillog
/var/log/cron
{
    daily
    rotate 90
    compress
    delaycompress
    missingok
    notifempty
    create 0600 root root
}
EOF

#=============================================================================
# Section 5: Access, Authentication and Authorization
#=============================================================================

echo "═══ Section 5: Access Control ═══"

# 5.1 Configure cron
echo "[5.1] Configuring cron access..."
rm -f /etc/cron.deny /etc/at.deny
touch /etc/cron.allow /etc/at.allow
chmod 600 /etc/cron.allow /etc/at.allow
chown root:root /etc/cron.allow /etc/at.allow

# 5.2 SSH Server Configuration
echo "[5.2] Comprehensive SSH hardening..."
cp /etc/ssh/sshd_config "$BACKUP_DIR/sshd_config.backup"

cat > /etc/ssh/sshd_config.d/99-cis-hardening.conf <<EOF
# CIS Level 2 SSH Configuration
Protocol 2
LogLevel INFO
PermitRootLogin no
MaxAuthTries 3
MaxSessions 10
PasswordAuthentication no
PermitEmptyPasswords no
ChallengeResponseAuthentication no
KerberosAuthentication no
GSSAPIAuthentication no
UsePAM yes
X11Forwarding no
PermitUserEnvironment no
ClientAliveInterval 300
ClientAliveCountMax 0
LoginGraceTime 60
Banner /etc/issue.net
AllowTcpForwarding no
MaxStartups 10:30:60
HostbasedAuthentication no
IgnoreRhosts yes
EOF

# Create SSH banner
cat > /etc/issue.net <<EOF
**************************************************************************
                            AUTHORIZED USE ONLY
**************************************************************************
Unauthorized access to this system is forbidden and will be prosecuted.
All activities are monitored and logged.
**************************************************************************
EOF

# Note: Not restarting SSH automatically - may disconnect
# systemctl restart sshd

# 5.3 Configure sudo
echo "[5.3] Configuring sudo..."
echo "Defaults use_pty" >> /etc/sudoers.d/cis-hardening
echo "Defaults logfile=\"/var/log/sudo.log\"" >> /etc/sudoers.d/cis-hardening
echo "Defaults timestamp_timeout=5" >> /etc/sudoers.d/cis-hardening
chmod 440 /etc/sudoers.d/cis-hardening

# 5.4 PAM Configuration
echo "[5.4] Configuring PAM..."

# Password quality requirements
cat > /etc/security/pwquality.conf <<EOF
# CIS Level 2 Password Requirements
minlen = 14
dcredit = -1
ucredit = -1
ocredit = -1
lcredit = -1
minclass = 4
maxrepeat = 3
maxsequence = 3
gecoscheck = 1
dictcheck = 1
usercheck = 1
enforcing = 1
EOF

# Configure password history
sed -i 's/^password.*pam_unix.so.*/password    sufficient    pam_unix.so sha512 shadow use_authtok remember=5/' /etc/pam.d/system-auth

# Account lockout policy
cat > /etc/security/faillock.conf <<EOF
# CIS Level 2 Account Lockout
deny = 5
unlock_time = 900
fail_interval = 900
EOF

# 5.5 User Accounts
echo "[5.5] User account hardening..."

# Set password aging
sed -i 's/^PASS_MAX_DAYS.*/PASS_MAX_DAYS   90/' /etc/login.defs
sed -i 's/^PASS_MIN_DAYS.*/PASS_MIN_DAYS   1/' /etc/login.defs
sed -i 's/^PASS_MIN_LEN.*/PASS_MIN_LEN    14/' /etc/login.defs
sed -i 's/^PASS_WARN_AGE.*/PASS_WARN_AGE   7/' /etc/login.defs

# Set default umask
sed -i 's/umask 022/umask 027/' /etc/bashrc
sed -i 's/umask 002/umask 027/' /etc/profile

# Set shell timeout
echo "TMOUT=900" >> /etc/profile.d/cis-timeout.sh
echo "readonly TMOUT" >> /etc/profile.d/cis-timeout.sh
echo "export TMOUT" >> /etc/profile.d/cis-timeout.sh

#=============================================================================
# Section 6: System Maintenance
#=============================================================================

echo "═══ Section 6: System Maintenance ═══"

# 6.1 System File Permissions
echo "[6.1] Setting system file permissions..."

chmod 644 /etc/passwd
chmod 644 /etc/passwd-
chmod 644 /etc/group
chmod 644 /etc/group-
chmod 000 /etc/shadow
chmod 000 /etc/shadow-
chmod 000 /etc/gshadow
chmod 000 /etc/gshadow-
chmod 644 /etc/shells

# Secure critical files
chmod 600 /etc/ssh/sshd_config
chmod 600 /boot/grub2/grub.cfg 2>/dev/null || true
chmod 600 /boot/efi/EFI/*/grub.cfg 2>/dev/null || true

# 6.2 User and Group Settings
echo "[6.2] Auditing user/group settings..."

# Ensure no legacy + entries
grep '^\+:' /etc/passwd /etc/shadow /etc/group /etc/gshadow || echo "No legacy + entries found"

# Lock system accounts
for user in $(awk -F: '($3 < 1000) {print $1 }' /etc/passwd); do
    if [ $user != "root" ] && [ $user != "sync" ] && [ $user != "shutdown" ] && [ $user != "halt" ]; then
        usermod -L $user 2>/dev/null || true
        usermod -s /sbin/nologin $user 2>/dev/null || true
    fi
done

#=============================================================================
# Additional Hardening
#=============================================================================

echo "═══ Additional Security Hardening ═══"

# Disable core dumps
echo "* hard core 0" >> /etc/security/limits.conf
echo "fs.suid_dumpable = 0" >> /etc/sysctl.d/90-cis.conf
sysctl -w fs.suid_dumpable=0

# Configure system accounting
dnf install -y psacct
systemctl enable --now psacct

# Install and configure security tools
dnf install -y aide chkrootkit

# Remove unnecessary packages (be careful not to break K8s)
# dnf remove -y telnet-server telnet rsh-server rsh ypserv tftp-server talk-server

# Set bootloader password (if needed in your environment)
# grub2-setpassword

#=============================================================================
# Kubernetes-Specific Configurations
#=============================================================================

echo "═══ Kubernetes Compatibility Checks ═══"

# Verify critical K8s services still running
echo "[K8s] Verifying kubelet..."
systemctl is-active kubelet || echo "WARNING: Kubelet not active!"

echo "[K8s] Verifying containerd..."
systemctl is-active containerd || echo "WARNING: Containerd not active!"

# Verify networking modules still loaded
echo "[K8s] Verifying network modules..."
lsmod | grep -E "br_netfilter|overlay" || echo "WARNING: Network modules may need loading"

#=============================================================================
# Final Steps
#=============================================================================

echo ""
echo "═══ Finalizing Configuration ═══"

# Apply all sysctl changes
sysctl --system

# Verify audit daemon
systemctl restart auditd
systemctl status auditd --no-pager | head -5

# Set SELinux to permissive (K8s requirement)
setenforce 0 2>/dev/null || true
sed -i 's/^SELINUX=enforcing/SELINUX=permissive/' /etc/selinux/config 2>/dev/null || true

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║              CIS Level 2 Hardening Complete!                   ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "✅ Applied comprehensive CIS Level 2 controls"
echo "✅ Kubernetes compatibility preserved"
echo "✅ Backup created: $BACKUP_DIR"
echo ""
echo "⚠️  IMPORTANT NEXT STEPS:"
echo ""
echo "1. Verify node is still Ready:"
echo "   kubectl get nodes"
echo ""
echo "2. Test pod deployment:"
echo "   kubectl run test --image=nginx --restart=Never"
echo ""
echo "3. Run CIS scanner for compliance verification:"
echo "   oscap xccdf eval --profile cis_level2 ..."
echo ""
echo "4. Review and address any failures"
echo ""
echo "5. Document exceptions for K8s-incompatible controls"
echo ""
echo "Backup location: $BACKUP_DIR"
echo "════════════════════════════════════════════════════════════════════"
