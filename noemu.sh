#!/bin/sh

releasedir="$1"
arch="$2"

# Work-in-progress "devirtualized" qemu replacement, controlling
# a physical machine instead of a virtual one

#. ./bracket.conf
. ./noemu.conf

child_pids=''

trap 'echo kill $child_pids; kill $child_pids' 0 1 15

test $(id -u) = 0 || exit 1

# Interface setup

ifconfig $interface $serveraddr netmask $netmask

# DHCPD setup

cat >dhcpd.conf <<EOF
pid-file-name "dhcpd.pid";
subnet $subnet netmask $netmask {
    range $range_begin $range_end;
}

class "pxe-clients-ia32" {
    match if substring (option vendor-class-identifier, 0, 20) = "PXEClient:Arch:00000";
    filename "pxeboot_ia32_com.bin";
#   filename "pxeboot_ia32_kgdb.bin";
}

next-server $serveraddr;
filename "tftp:netbsd-install";
EOF

: >dhcpd.leases

# TFTPD and HTTPD setup

tftpdir=`pwd`/tftp
test -d $tftpdir || mkdir $tftpdir

cat <<EOF >inetd.conf
tftp		dgram	udp	wait	root	/usr/libexec/tftpd	tftpd -l -s $tftpdir
http            stream tcp      nowait:600 root /usr/libexec/httpd 	httpd $releasedir
EOF

cp $releasedir/$arch/installation/misc/pxeboot_ia32.bin $tftpdir/

# Create a serial console version of pxeboot
cp $tftpdir/pxeboot_ia32.bin $tftpdir/pxeboot_ia32_com.bin
installboot -e -o console=com0 $tftpdir/pxeboot_ia32_com.bin

gunzip <$releasedir/$arch/binary/kernel/netbsd-INSTALL.gz >tftp/netbsd-install

# Start services

/usr/pkg/sbin/dhcpd -d -f -cf dhcpd.conf -lf dhcpd.leases $interface &
dhcpd_pid=$!
echo "dhcpd pid $dhcpd_pid"
child_pids="$child_pids $dhcpd_pid"

# Run tftpd and httpd via inetd
inetd `pwd`/inetd.conf &
inetd_pid=$!
echo "inetd pid $inet_pid"
child_pids="$child_pids $inetd_pid"

echo "connecting"
tip puc &
tip_pid=$!
child_pids="$child_pids $tip_pid"

echo "$child_pids" >noemu.pids

wait
