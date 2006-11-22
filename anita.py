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
# This is used for getting relases only, not for daily builds.
# See http://www.netbsd.org/mirrors/#ftp for the complete list.

netbsd_mirror_url = "ftp://ftp.netbsd.org/pub/NetBSD/"
#netbsd_mirror_url = "ftp://ftp.fi.NetBSD.org/pub/NetBSD/"

# Run a shell command safely and with error checking

def spawn(command, args):
    ret = os.spawnvp(os.P_WAIT, command, args)
    if ret != 0:
        raise RuntimeError("could not run " + command)

# FTP a file, cleaning up the partial file if the transfer
# fails or is aborted before completion.

def ftp_file(file, url):
    try:
        spawn("ftp", ["ftp", "-o", file, url])
    except:
        if os.path.isfile(file):
            os.unlink(file)
        raise

# FTP a file from the FTP directory tree rooted at "urlbase"
# into a mirror tree rooted at "dirbase".  The file name to
# FTP is "relfile", which is relative to both roots.
# If the file already exists locally, do nothing.
# Return true iff we actually downloaded the file.

def ftp_if_missing(urlbase, dirbase, relfile):
    url = urlbase + relfile
    file = dirbase + "/" + relfile
    if os.path.isfile(file):
        return False
    dir = os.path.dirname(file)
    if not os.path.isdir(dir):
        os.makedirs(dir)
    ftp_file(file, url)
    return True

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

    # The list of boot floppies we should try downloading;
    # not all may actually exist
    def potential_floppies(self):
        return ['boot-com1.fs', 'boot2.fs', 'boot3.fs']

    # The list of boot floppies we actually have
    def floppies(self):
        return [f for f in self.potential_floppies() \
            if os.path.isfile(os.path.join(self.floppy_dir(), f))]

    # Download this release by FTP
    def ftp(self):
        # Depending on the NetBSD version, there may be two or three
        # boot floppies.  First download the ones that should always
        # exist.
        for floppy in self.potential_floppies()[0:2]:
            did_download_floppies = ftp_if_missing(self.dist_url(), 
                self.ftp_local_dir(), "i386/installation/floppy/" + floppy)
        # Then attempt to download the remining ones, but only
        # if we actually downloaded the initial ones rather
        # than finding them in the cache.
        if did_download_floppies:
            for floppy in self.potential_floppies()[2:]:
                try:
                    ftp_if_missing(self.dist_url(),
                       self.ftp_local_dir(),
                       "i386/installation/floppy/" + floppy)
                except:
                    pass
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

    # Install this version of NetBSD

    def _install(self):
        # Get the install ISO
        self.make_iso()

        floppy_paths = [ os.path.join(self.floppy_dir(), f) for f in self.floppies() ]

        spawn("qemu-img", ["qemu-img", "create", self.wd0_path(), "512M"])
        child = pexpect.spawn("qemu", ["qemu", "-m", "32", \
            "-hda", self.wd0_path(), \
            "-fda", floppy_paths[0], "-cdrom", self.iso_path(), \
            "-boot", "a", "-serial", "stdio", "-nographic"])
        child.log_file = sys.stdout
        child.timeout = 300

        for i in range(1, len(floppy_paths)):
            child.expect("insert disk %d, and press return..." % (i + 1))
            # Escape into qemu command mode to switch floppies
            child.send("\001c")
            child.expect('\(qemu\)')
            child.send("change fda %s" % floppy_paths[i])
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
        # Custom installation is choice "c" in -current,
        # choice "b" in older versions
        # We could use "Minimal", but it doesn't exist in
        # older versions.
        child.expect(re.compile("([a-z]): Custom installation"))
        child.send(child.match.group(1) + "\n")
        print "sent " + child.match.group(1)
        # Check the default for the comp set
        child.expect(re.compile("([a-z]): Compiler Tools.*((Yes)|(No))"))
        if child.match.group(2) == "No":
            # If disabled, enable it
            child.send(child.match.group(1) + "\n")
        # Check the default for the X11 sets
        child.expect(re.compile("([a-z]): X11 sets.*((All)|(None))"))
        # If the X11 sets are selected by default, deselect them
        if child.match.group(2) == "All":
            child.send(child.match.group(1) + "\n")
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
        child.expect(re.compile("([cx]): Continue"))
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
        os.unlink(self.iso_path())

    # Install this version of NetBSD if not installed already

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
    def base_dir(self):
        return Version.base_dir(self) + "-" + self.timestamp
    def dist_url(self):
        dash_ver = re.sub("[\\._]", "-", self.ver)
        return "http://ftp.netbsd.org/pub/NetBSD-daily/netbsd-" + \
            dash_ver + "/" + self.timestamp + "/"

# A local build

class LocalBuild(Version):
    def __init__(self, ver, release_path):
        Version.__init__(self, ver)
        self.release_path = release_path
    def dist_url(self):
        return "file://" + self.release_path
