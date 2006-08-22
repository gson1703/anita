#!/usr/pkg/bin/python
#
# Scripted NetBSD installation
#

import pexpect
import sys
import os
import time
import re

def spawn(command, args):
    ret = os.spawnvp(os.P_WAIT, command, args)
    if ret != 0:
        raise RuntimeError("could not run " + command)

def install_netbsd(iso, boot1, boot2, hd):
    if os.path.isfile(hd):
        return
    spawn("qemu-img", ["qemu-img", "create", hd, "1500M"])
    child = pexpect.spawn("qemu", ["qemu", "-m", "32", "-hda", hd, "-fda", boot1, "-cdrom", iso, \
        "-boot", "a", "-serial", "stdio", "-nographic"])
    child.log_file = sys.stdout
    child.timeout = 3600

    child.expect("insert disk 2, and press return...")
    # Escape into qemu command mode to switch floppies
    child.send("\001c")
    child.expect('\(qemu\)')
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
    if False:
	# With X
	child.send("a\n")
    else:
	# Without X
	child.send("b\n")
	child.expect("o: X11 sets")
	child.send("o\n")
	child.expect("g: Deselect all")
	child.send("g\n")
	child.send("x\n")
	child.send("x\n")
    child.expect("a: This is the correct geometry")
    child.send("\n")
    child.expect("b: Use the entire disk")
    child.send("b\n")
    child.expect("Do you want to install the NetBSD bootcode")
    child.expect("a: Yes")
    child.send("\n")
    child.send("\n")
    child.expect("Accept partition sizes")
    # Press control-N enough times to get to the end of the list,
    # then enter to continue
    child.send("\016\016\016\016\016\016\016\016\n")
    child.expect("x: Partition sizes ok")
    child.send("\n")
    child.expect("Please enter a name for your NetBSD disk")
    child.send("\n")
    child.expect("Shall we continue")
    child.expect("b: Yes")
    child.send("b\n")
    child.expect("b: Use serial port com0")
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

# XXX hardcodes -snapshot

def boot_netbsd(ver):
    hd = "netbsd-" + ver + "/" + "wd0"
    child = pexpect.spawn("qemu", ["qemu", "-m", "32", "-hda", hd, "-serial", "stdio", "-nographic", "-snapshot"])
    child.log_file = sys.stdout
    child.timeout = 3600
    child.expect("login:")
    return child


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

def ftp_if_missing(url, file):
	if not os.path.isfile(file):
		dir = os.path.dirname(file)
		print "missing " + file
		if not os.path.isdir(dir):
			os.makedirs(dir)
		print "FTP " + url
		spawn("ftp", ["ftp", "-o", file, url])

def ftp_if_missing_2(urlbase, dirbase, relfile):
    url = urlbase + relfile
    file = dirbase + "/" + relfile
    if os.path.isfile(file):
	return
    print "missing " + file
    dir = os.path.dirname(file)
    if not os.path.isdir(dir):
	os.makedirs(dir)
    print "FTP " + url
    spawn("ftp", ["ftp", "-o", file, url])

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
    dist_url = base_url + "NetBSD-" + ver + "/"
    for floppy in ['boot-com1.fs', 'boot2.fs']:
	ftp_if_missing(dist_url + "i386/installation/floppy/" + floppy, "dist/" + ver + "/" + floppy)
    isoname = iso_name(ver)
    ftp_if_missing(base_url + "iso/" + ver + "/" + isoname, "dist/" + ver + "/" + isoname)


def ftp_netbsd_rc(ver, datetime):
    dash_ver = re.sub("[\\._]", "-", ver)
    base_url = "http://ftp.netbsd.org/pub/NetBSD-daily/netbsd-" + dash_ver + "/" + datetime + "/";
    dist_url = base_url
    for floppy in ['boot-com1.fs', 'boot2.fs']:
	ftp_if_missing(dist_url + "i386/installation/floppy/" + floppy, "dist/" + ver + "/" + floppy)
    isoname = iso_name(ver)
    ftp_if_missing(base_url + "iso/" + isoname, "dist/" + ver + "/" + isoname)

def install_netbsd_dist(ver):
    dir = "netbsd-" + ver + "/"
    floppy_dir = dir + "ftp/i386/installation/floppy/"
    install_netbsd(dir  + iso_name(ver), floppy_dir + "boot-com1.fs", floppy_dir + "boot2.fs", dir + "wd0")

#install_netbsd_dist("2.1")
#ftp_netbsd_dist("3.0")

#child = boot_netbsd("hd-3.0")
#child.interact()

#install_netbsd_dist("3.0.1")
#boot_netbsd("hd-3.0.1")

#install_netbsd_dist("3.0")
#boot_netbsd("hd-3.0")

#boot_netbsd("hd-1004")

#dist="/usr/build/1005/release/i386/installation"
#install_netbsd(dist + "/cdrom/netbsd-i386.iso", dist + "/floppy/boot-com1.fs", dist + "/floppy/boot2.fs", "hd-1005")

#child = boot_netbsd("hd-1005")
#child.interact()

# ftp://ftp.netbsd.org/pub/NetBSD-daily/HEAD/200608050000Z/i386/installation/cdrom/boot-com.iso

#ftp_netbsd_rc("3.1_RC1", "200608202102Z")
#install_netbsd_dist("3.1_RC1")
#boot_netbsd("hd-3.1_RC1")

#ftp_netbsd_rc("HEAD", "200608050000Z")

#ftp://ftp.netbsd.org/pub/NetBSD-daily/HEAD/200608050000Z/i386/installation/cdrom/boot-com.iso

def ftp_netbsd_daily(ver, datetime):
    dash_ver = re.sub("[\\._]", "-", ver)
    base_url = "http://ftp.netbsd.org/pub/NetBSD-daily/netbsd-" + dash_ver + "/" + datetime + "/"
    dist_url = base_url
    base_dir = "netbsd-" + ver + "/ftp/"
    for floppy in ['boot-com1.fs', 'boot2.fs']:
	ftp_if_missing_2(dist_url, base_dir, "i386/installation/floppy/" + floppy)
    # "xbase", "xcomp", "xetc", "xfont", "xserver", 
    for set in [ "base", "comp", "etc", "games", "man", "misc", "text", "kern-GENERIC" ]:
        ftp_if_missing_2(dist_url, base_dir, "i386/binary/sets/" + set + ".tgz")
    spawn("makefs", ["makefs", "-t", "cd9660", "-o", "rockridge", "netbsd-" + ver + "/" + iso_name(ver), "base_dir"])

#ftp_netbsd_daily("4", "200608170000Z")
#install_netbsd_dist("4")
child = boot_netbsd("4")
child.interact()
