#!/usr/pkg/bin/python
#
# This is Anita, the Automated NetBSD Installation and Test Application.
#
# See the file COPYRIGHT for copyright information.
#

import pexpect
import sys
import os
import time
import re

# Your preferred NetBSD FTP mirror site.
# See http://www.netbsd.org/mirrors/#ftp for the complete list.

netbsd_mirror_url = "ftp://ftp.netbsd.org/pub/NetBSD/"
#netbsd_mirror_url = "ftp://ftp.fi.NetBSD.org/pub/NetBSD/"

# Helper function to run a shell command safely and with error
# checking

def spawn(command, args):
    ret = os.spawnvp(os.P_WAIT, command, args)
    if ret != 0:
        raise RuntimeError("could not run " + command)

# FTP a file from the FTP directory tree rooted at "urlbase"
# into a mirror tree rooted at "dirbase".  The file name to
# FTP is "relfile", which is relative to both roots.
# If the file already exists locally, do nothing.

def ftp_if_missing(urlbase, dirbase, relfile):
    url = urlbase + relfile
    file = dirbase + "/" + relfile
    if os.path.isfile(file):
        return
    try:
        dir = os.path.dirname(file)
        if not os.path.isdir(dir):
            os.makedirs(dir)
        spawn("ftp", ["ftp", "-o", file, url])
    except:
        if os.path.isfile(file):
            os.unlink(file)
        raise

# A NetBSD version.
#
# Subclasses should define:
#
#    dist_url(self) - the URL for the top of the FTP tree
#                     where the version can be downloaded

class Version:
    def __init__(self, ver):
        self.ver = ver

    # The directory for files related to this release
    def base_dir(self):
        return "netbsd-" + self.ver
    # The file name of the install ISO (sans directory)
    def iso_name(self):
        if re.match("^[3-9]", self.ver) is not None:
            return "i386cd-" + self.ver + ".iso"
        else:
            return "i386cd.iso"
    # The directory where we mirror FTP files needed for installation
    def ftp_local_dir(self):
        return self.base_dir() + "/ftp/"
    # The path to the install ISO image
    def iso_path(self):
        return os.path.join(self.base_dir(), self.iso_name())
    # The directory for the install floppy images
    def floppy_dir(self):
        return os.path.join(self.ftp_local_dir(), "i386/installation/floppy")
    # The path to the NetBSD hard disk image
    def wd0_path(self):
        return os.path.join(self.base_dir(), "wd0.img")

    # Download this release by FTP
    def ftp(self):
        for floppy in ['boot-com1.fs', 'boot2.fs']:
            ftp_if_missing(self.dist_url(), self.ftp_local_dir(), \
                "i386/installation/floppy/" + floppy)
        for set in [ "base", "comp", "etc", "games", "man", "misc", \
            "text", "kern-GENERIC" ]:
            ftp_if_missing(self.dist_url(), self.ftp_local_dir(), \
                "i386/binary/sets/" + set + ".tgz")

    # Create an install ISO image to install from
    def make_iso(self):
        self.ftp()
        if os.path.isfile(self.iso_path()):
            return
        spawn("makefs", ["makefs", "-t", "cd9660", "-o", "rockridge", \
            self.iso_path(), self.ftp_local_dir()])

    def _install(self):
        # Get the install ISO
        self.make_iso()

        boot1 = os.path.join(self.floppy_dir(), "boot-com1.fs")
        boot2 = os.path.join(self.floppy_dir(), "boot2.fs")

        spawn("qemu-img", ["qemu-img", "create", self.wd0_path(), "512M"])
        child = pexpect.spawn("qemu", ["qemu", "-m", "32", \
            "-hda", self.wd0_path(), \
            "-fda", boot1, "-cdrom", self.iso_path(), \
            "-boot", "a", "-serial", "stdio", "-nographic"])
        child.log_file = sys.stdout
        child.timeout = 300

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
        # Choose "custom installation"
        child.send("b\n")
        # Go to the X set selection submenu
        child.expect("o: X11 sets")
        child.send("o\n")
        child.expect("a: X11 base and clients")
        # Deselect the X sets one by one.  Avoid
        # "g: Deselect all the above sets" as it behaves
        # inconsistently between NetBSD versions:
        # -current wants that to be followed by
        # "x\n" to exit the dialog, but older versions
        # do not.
        for c in "abcde":
             child.send(c + "\n")
        # Exit the X set selection submenu
        child.send("x\n")
        # Exit the main set selection menu
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
        # In 3.0.1, you type "c" to continue,; in -current, you type "x".
        # Handle both cases.
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

    def install(self):
        # Already installed?
        if os.path.isfile(self.wd0_path()):
            return
        try:
            self._install()
        except:
            if os.path.isfile(self.wd0_path()):
                os.unlink(self.wd0_path())
            raise

    def boot(self):
        self.install()
        child = pexpect.spawn("qemu", ["qemu", "-m", "32", \
            "-hda", self.wd0_path(), \
            "-serial", "stdio", "-nographic", "-snapshot"])
        child.log_file = sys.stdout
        child.timeout = 300
        child.expect("login:")
        return child

    def interact(self):
        self.boot().interact()

# An official NetBSD release

class Release(Version):
    def __init__(self, ver):
        Version.__init__(self, ver)
        pass
    def dist_url(self):
        return netbsd_mirror_url + "NetBSD-" + self.ver + "/"

# A daily build

class DailyBuild(Version):
    def __init__(self, ver, timestamp):
        Version.__init__(self, ver)
        self.timestamp = timestamp
    def dist_url(self):
        dash_ver = re.sub("[\\._]", "-", self.ver)
        return "http://ftp.netbsd.org/pub/NetBSD-daily/netbsd-" + \
            dash_ver + "/" + self.timestamp + "/"
