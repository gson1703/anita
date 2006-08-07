#!/usr/pkg/bin/python

import pexpect
import sys
import os
import time
import re

# XXX unused, remove

def send_slowly(child, str):
    for char in str:
        child.send(char)
        child.expect(char)

def install_netbsd(iso, boot1, boot2, hd):

    os.system("qemu-img create %s 1500M" % hd)

    qemu_command = "qemu -m 32 -hda %s -fda %s -cdrom %s -boot a -serial stdio -nographic" % (hd, boot1, iso)
    print qemu_command
    child = pexpect.spawn(qemu_command)
    child.log_file = sys.stdout
    child.timeout = 3600

    child.expect("insert disk 2, and press return...")
    # Escape into qemu command mode to switch floppies
    child.send("\001c")
    child.expect('\(qemu\)')
    #send_slowly(child, "change fda %s" % boot2)
    child.send("change fda %s" % boot2)
    child.send("\n")
    child.expect('\(qemu\)')
    # Exit qemu command mode
    child.send("\001c\n")
    child.expect("a: Installation messages in English")
    child.send("\n")
    child.expect("Keyboard type")
    child.send("\n")
    child.expect("a: Install NetBSD to hard disk")
    child.send("\n")
    child.expect("Shall we continue")
    child.expect("b: Yes")
    child.send("b\n")
    child.expect("I found only one disk")
    child.expect("Hit enter to continue")
    child.send("\n")
    child.expect("a: Full installation")
    child.send("\n")
    child.expect("a: This is the correct geometry")
    child.send("\n")
    child.expect("b: Use the entire disk")
    child.send("b\n")
    child.expect("Do you want to install the NetBSD bootcode")
    child.expect("a: Yes")
    child.send("\n")
    # XXX If you select "b: Use existing partition sizes" here, things go wrong
    child.send("\n")
    child.expect("Accept partition sizes")
    # Press control-N enought times to get to the end of the list,
    # then press enter to continue
    child.send("\016\016\016\016\016\016\016\016\n")
    child.expect("x: Partition sizes ok")
    child.send("\n")
    child.expect("Please enter a name for your NetBSD disk")
    child.send("\n")
    child.expect("Shall we continue")
    child.expect("b: Yes")
    child.send("b\n")
    child.expect("b: Use serial port com0")
    # XXX sysinst is inconsistent here; you must select "x" to exit
    # the dialog, whereas other similar dialogs let you just press enter.
    child.send("bx\n")
    child.expect("a: Progress bar")
    child.send("\n")
    child.expect("a: CD-ROM")
    child.send("\n")
    # In 3.0.1, you type "c" to continue,; in -current, you type "x"
    regex = re.compile("([cx]): Continue")
    child.expect(regex)
    child.send(child.match.group(1) + "\n")
    child.expect("Hit enter to continue")
    child.send("\n")
    child.expect("Hit enter to continue")
    child.send("\n")
    child.expect("Please choose the timezone")
    child.send("x\n")
    child.expect("a: DES")
    child.send("\n")
    child.expect("root password")
    child.expect("b: No")
    child.send("b\n")
    child.expect("a: /bin/sh")
    child.send("\n")
    child.expect("Hit enter to continue")
    child.send("\n")
    child.expect("x: Exit")
    child.send("x\n")
    child.expect("#")  
    child.send("halt\n")
    child.expect("halted by root")

# XXX hardcodes pkg.hd, snapshot

def boot_netbsd(hd):
    qemu_command = "qemu -m 32 -hda " + hd + " -hdb pkg.hd -serial stdio -nographic -snapshot"
    print qemu_command
    child = pexpect.spawn(qemu_command)
    child.log_file = sys.stdout
    child.timeout = 3600

    child.expect("login:")
    child.send("root\n")
    child.expect("\n# ")
    return child

def root_command(child, cmd):
    child.send(cmd + "\n")
    child.expect("\n# ")

########################################################################

# pgsql stuff

def install_pgsql(child, version):
    root_command(child, "cd /mnt")
    root_command(child, "pkg_add %s.tgz" % version)
    # # If you actually do this, pgsql won't start due to lacking server.crt.
    # # root_command(child, "echo 'pgsql_flags=\"-l\"' >>/etc/rc.conf")
    root_command(child, "cp /usr/pkg/share/examples/rc.d/pgsql /etc/rc.d/")
    root_command(child, "echo 'pgsql=YES' >>/etc/rc.conf")
    root_command(child, "/etc/rc.d/pgsql start")

def test_pgsql(child):
    root_command(child, "mount /dev/wd1a /mnt")

    install_pgsql(child, "postgresql74-server-7.4.13")

    # Populate the database
    #root_command(child, "su pgsql -c 'psql -d template1 -f araneus.pgdump'")
    # createdb root
    # pgsql
    #
    root_command(child, "cd /tmp")
    root_command(child, "su pgsql -c 'pg_dumpall' >backup.pgdump")
    root_command(child, "su pgsql -c 'pg_dumpall -o' >backup.pgdump-o")

    root_command(child, "/etc/rc.d/pgsql stop")
    root_command(child, "pkg_delete -R postgresql74-server")

    root_command(child, "rm -rf /usr/pkg/pgsql")

    # restore in 8.1:
    install_pgsql(child, "postgresql81-server-8.1.4")
    root_command(child, "su pgsql -c 'psql -d postgres -f /tmp/backup.pgdump-o'")

    # restore in 7.4.13
    #install_pgsql(child, "postgresql74-server-7.4.13")
    #root_command(child, "su pgsql -c 'psql -d template1 -f /tmp/backup.pgdump-o'")

# 3.0.1
# installs fine but booting the installed hd hangs after "root on ffs"
#install_netbsd("i386cd-3.0.1.iso", "boot-com1.fs", "boot2.fs", "hd-3.0.1")

# current / guava
# works
#dist="/usr/build/136/release/i386/installation"
#install_netbsd(dist + "/cdrom/netbsd-i386.iso", dist + "/floppy/boot-com1.fs", dist + "/floppy/boot2.fs", "hd-136")
#install_netbsd("dist/136/netbsd-i386.iso", "dist/136/boot-com1.fs", "dist/136/boot2.fs", "hd-136")

# current / guam
# install kernel hangs after probing kbc
#dist="/usr/build/1003/release/i386/installation"
#install_netbsd(dist + "/cdrom/netbsd-i386.iso", dist + "/floppy/boot-com1.fs", dist + "/floppy/boot2.fs", "hd-1003")

# current / guam
# works

#dist="/usr/build/1004/release/i386/installation"
#install_netbsd(dist + "/cdrom/netbsd-i386.iso", dist + "/floppy/boot-com1.fs", dist + "/floppy/boot2.fs", "hd-1004")
#os.system("touch hd-1004.timestamp")

def ftp_if_missing(url, file):
	if not os.path.isfile(file):
		dir = os.path.dirname(file)
		if not os.path.isdir(dir):
			os.makedirs(dir)
		# XXX check result
		os.spawnlp(os.P_WAIT, "ftp", "ftp", "-o", file, url)

# Determine the name of the official NetBSD install ISO for version "ver"

def iso_name(ver):
    if re.match("^[3-9]", ver) is not None:
	return "i386cd-" + ver + ".iso"
    else:
	return "i386cd.iso"

# FTP a NetBSD distribution.  We need an ISO and serial console boot floppies.
# This should work for 2.0 through 3.0.1, at least.

def ftp_netbsd_dist(ver):
    base_url = "http://ftp.netbsd.org/pub/NetBSD/"
    for floppy in ['boot-com1.fs', 'boot2.fs']:
	ftp_if_missing(base_url + "NetBSD-" + ver + "/i386/installation/floppy/" + floppy, "dist/" + ver + "/" + floppy)
    isoname = iso_name(ver)
    ftp_if_missing(base_url + "iso/" + ver + "/" + isoname, "dist/" + ver + "/" + isoname)

def install_netbsd_dist(ver):
    dir = "dist/" + ver + "/"
    install_netbsd(dir  + iso_name(ver), dir + "boot-com1.fs", dir + "boot2.fs", "hd-" + ver)

# run_netbsd("hd-1004")

#install_netbsd_dist("2.1")

#ftp_netbsd_dist("3.0")

#child = boot_netbsd("hd-3.0")
#child.interact()

#install_netbsd_dist("3.0.1")
#boot_netbsd("hd-3.0.1")



#install_netbsd_dist("3.0")
#boot_netbsd("hd-3.0")

boot_netbsd("hd-1004")
