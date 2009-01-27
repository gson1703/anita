#
# This is the library part of Anita, the Automated NetBSD Installation
# and Test Application.
#

import md5
import os
import pexpect
import re
import string
import subprocess
import sys
import time

# Your preferred NetBSD FTP mirror site.
# This is used for getting relases only, not for daily builds.
# See http://www.netbsd.org/mirrors/#ftp for the complete list.

netbsd_mirror_url = "ftp://ftp.netbsd.org/pub/NetBSD/"
#netbsd_mirror_url = "ftp://ftp.fi.NetBSD.org/pub/NetBSD/"

# External commands we rely on

qemu = "qemu"
qemu_img = "qemu-img"
if os.uname()[0] == 'NetBSD':
    download_command = ["ftp", "-o"]
    makefs = ["makefs", "-t", "cd9660", "-o", "rockridge"]
else:
    download_command = ["wget", "-O"]
    makefs = ["genisoimage", "-r", "-o"]

# Get the version number of of the installed qemu

def get_qemu_version():
    proc = subprocess.Popen([qemu, '-h'], stdout=subprocess.PIPE)
    lines = proc.stdout.readlines()
    m = re.search(r"version ([0-9\.]+)", lines[0])
    if not m:
	raise RuntimeError("could not determine qemu version")
    proc.wait()
    return m.group(1)

# Convert a version number like "0.9.1" into a form that
# can be correctly compared using lexicographic string
# comparison

def lexversion(v):
    return "".join([string.zfill(d, 8) for d in v.split(".")])

qemu_version = get_qemu_version()

if lexversion(qemu_version) >= lexversion("0.9.1"):
    qemu_command_mode_switch = "\001c\n"
    qemu_floppy0_name = "floppy0"    
else:
    qemu_command_mode_switch = "\001c"
    qemu_floppy0_name = "fda"
    
# Create a directory if missing

def mkdir_p(dir):
    if not os.path.isdir(dir):
        os.makedirs(dir)

# Run a shell command safely and with error checking

def spawn(command, args):
    ret = os.spawnvp(os.P_WAIT, command, args)
    if ret != 0:
        raise RuntimeError("could not run " + command)

# Download a file, cleaning up the partial file if the transfer
# fails or is aborted before completion.

def download_file(file, url):
    try:
        spawn(download_command[0], download_command + [file, url])
    except:
        if os.path.exists(file):
            os.unlink(file)
        raise

# Download a file from the download directory tree rooted at "urlbase"
# into a mirror tree rooted at "dirbase".  The file name to download
# is "relfile", which is relative to both roots.  If the file already
# exists locally, do nothing.  Return true iff we actually downloaded
# the file.

def download_if_missing(urlbase, dirbase, relfile):
    url = urlbase + relfile
    file = os.path.join(dirbase, relfile)
    if os.path.exists(file):
        return False
    dir = os.path.dirname(file)
    mkdir_p(dir)
    download_file(file, url)
    return True

# Subclass pexpect.spawn to deal with silly cursor movement
# commands.  Makes " " match a \[[C sequence in addition
# to its usual meaning of matching a space, and introduce
# the special charcter "@" meaning "\[[C or any single char".

class spawn_cm(pexpect.spawn):
    def expect(self, match_re):
        new_re = re.sub(" ", "(?: |(?:\x1b\[C))", match_re)
        new_re = re.sub("@", "(?:.|(?:\x1b\[C))", new_re)
        # print "%s -> %s" % (match_re, new_re)
        return pexpect.spawn.expect(self, new_re)

#############################################################################

# A NetBSD version.
#
# Subclasses should define:
#
#    dist_url(self) - the URL for the top of the download tree
#                     where the version can be downloaded

class Version:
    # Information about the available installation file sets.
    # Each is a tuple of three fields: the file name, the
    # label used by sysinst, and a flag indicating whether
    # the set should be installed by default.
    sets = [
      ( 'kern-GENERIC', 'Kernel (GENERIC)', 1 ),
      ( 'kern-GENERIC.NOACPI', 'Kernel (GENERIC.NOACPI)', 0 ),
      ( 'base', 'Base', 1 ),
      ( 'etc', 'System (/etc)', 1 ),
      ( 'comp', 'Compiler Tools', 1 ),
      ( 'games', 'Games', 0 ),
      ( 'man', 'Online Manual Pages', 0 ),
      ( 'misc', 'Miscellaneous', 0 ),
      ( 'tests', 'Test programs', 0 ),
      ( 'text', 'Text Processing Tools', 0 ),
    ]
    def __init__(self):
        self.tempfiles = []
    def set_workdir(self, dir):
        self.workdir = dir
    # The directory where we mirror files needed for installation
    def download_local_dir(self):
        return self.workdir + "/download/"
    # The path to the install ISO image
    def iso_path(self):
        return os.path.join(self.workdir, self.iso_name())
    # The directory for the install floppy images
    def floppy_dir(self):
        return os.path.join(self.download_local_dir(), "i386/installation/floppy")

    # The list of boot floppies we should try downloading;
    # not all may actually exist
    def potential_floppies(self):
        return ['boot-com1.fs', 'boot2.fs', 'boot3.fs']

    # The list of boot floppies we actually have
    def floppies(self):
        return [f for f in self.potential_floppies() \
            if os.path.exists(os.path.join(self.floppy_dir(), f))]

    def cleanup(self):
        for fn in self.tempfiles:
            os.unlink(fn)

    # Download this release
    def download(self):
        # Depending on the NetBSD version, there may be two or three
        # boot floppies.  First download the ones that should always
        # exist.
        for floppy in self.potential_floppies()[0:2]:
            did_download_floppies = download_if_missing(self.dist_url(), 
                self.download_local_dir(), os.path.join("i386/installation/floppy/", floppy))
        # Then attempt to download the remining ones, but only
        # if we actually downloaded the initial ones rather
        # than finding them in the cache.
        if did_download_floppies:
            for floppy in self.potential_floppies()[2:]:
                try:
                    download_if_missing(self.dist_url(),
                       self.download_local_dir(),
                       "i386/installation/floppy/" + floppy)
                except:
                    pass
        for set in Version.sets:
            (fn, label, enable) = set
            if enable:
		download_if_missing(self.dist_url(), self.download_local_dir(), \
		    os.path.join("i386/binary/sets", fn + ".tgz"))

    # Create an install ISO image to install from
    def make_iso(self):
        self.download()
        if not os.path.exists(self.iso_path()):
	    spawn(makefs[0], makefs + \
		[self.iso_path(), self.download_local_dir()])
            self.tempfiles.append(self.iso_path())

    # Backwards compatibility with Anita 1.2 and older
    def install(self):
        Anita(dist = self).install()
    def boot(self):
        Anita(dist = self).boot()
    def interact(self):
        Anita(dist = self).interact()

# Subclass for versions where we pass in the version number explicitly

class NumberedVersion(Version):
    def __init__(self, ver):
        Version.__init__(self)
        self.ver = ver
    # The file name of the install ISO (sans directory)
    def iso_name(self):
        if re.match("^[3-9]", self.ver) is not None:
            return "i386cd-" + self.ver + ".iso"
        else:
            return "i386cd.iso"
    # The directory for files related to this release
    def default_workdir(self):
        return "netbsd-" + self.ver

# An official NetBSD release

class Release(NumberedVersion):
    def __init__(self, ver):
        NumberedVersion.__init__(self, ver)
        pass
    def dist_url(self):
        return netbsd_mirror_url + "NetBSD-" + self.ver + "/"

# A daily build

class DailyBuild(NumberedVersion):
    def __init__(self, branch, timestamp):
        ver = re.sub("^netbsd-", "", branch)
        NumberedVersion.__init__(self, ver)
        self.timestamp = timestamp
    def default_workdir(self):
        return NumberedVersion.default_workdir(self) + "-" + self.timestamp
    def dist_url(self):
        branch = re.sub("[\\._]", "-", self.ver)
        if re.match("^[0-9]", branch):
            branch = "netbsd-" + branch
        return "http://ftp.netbsd.org/pub/NetBSD-daily/" + \
            branch + "/" + self.timestamp + "/"

# A local build

class LocalBuild(NumberedVersion):
    def __init__(self, ver, release_path):
        NumberedVersion.__init__(self, ver)
        self.release_path = release_path
    def dist_url(self):
        return "file://" + self.release_path

# An ISO

class ISO(Version):
    def __init__(self, iso_path):
        Version.__init__(self)
        self.m_iso_path = iso_path
    def iso_path(self):
        return self.m_iso_path
    # XXX actually version specific
    def potential_floppies(self):
        return ['boot-com1.fs', 'boot-com2.fs']
    def floppies(self):
        return ['boot-com1.fs', 'boot-com2.fs']
    def default_workdir(self):
        return "netbsd-" + md5.new(self.m_iso_path).hexdigest()

    # We don't need to download sets because we already have
    # a useable ISO.  However, we don't have a boot-com1.fs.
    # Extract it.
    def download(self):
        mkdir_p(self.floppy_dir())
        for floppy in self.potential_floppies():
            fn = os.path.join(self.floppy_dir(), floppy)
            f = open(fn, 'w')
            subprocess.call(['isoinfo', '-R', '-i', self.iso_path(), \
		'-x',  '/i386/installation/floppy/' + floppy], stdout=f)
            f.close()
        # XXX check that we have at least one

# The top-level URL of a release tree

class URL(Version):
    def __init__(self, url):
        Version.__init__(self)
        self.url = url
    def dist_url(self):
        # XXX check
        return re.sub('/i386/', '/', self.url)
    def iso_name(self):
        return "install_tmp.iso"
    def default_workdir(self):
        return "netbsd-" + md5.new(self.url).hexdigest()

#############################################################################

class Anita:
    def __init__(self, dist, workdir = None):
        self.dist = dist
        if workdir:
           self.workdir = workdir
        else:
            self.workdir = dist.default_workdir()

    # The path to the NetBSD hard disk image
    def wd0_path(self):
        return os.path.join(self.workdir, "wd0.img")

    def _install(self):
        # Get the install ISO
        self.dist.set_workdir(self.workdir)
        self.dist.make_iso()

        floppy_paths = [ os.path.join(self.dist.floppy_dir(), f) \
            for f in self.dist.floppies() ]

        spawn(qemu_img, ["qemu-img", "create", self.wd0_path(), "384M"])
        child = spawn_cm(qemu, ["-m", "32", \
            "-hda", self.wd0_path(), \
            "-fda", floppy_paths[0], "-cdrom", self.dist.iso_path(), \
            "-boot", "a", "-serial", "stdio", "-nographic"])

	# pexpect 2.1 uses "child.logfile", but pexpect 0.999nb1 usess "child.log_file"
        child.logfile = sys.stdout
        child.log_file = sys.stdout
        child.timeout = 300
        child.setecho(False)

        while True:
            child.expect("(insert disk (\d+), and press return...)|(a: Installation messages in English)")
	    if not child.match.group(1):
		break
            # There is no floppy 0, hence the "- 1"
            floppy_index = int(child.match.group(2)) - 1

            # Escape into qemu command mode to switch floppies
            child.send(qemu_command_mode_switch)
            child.expect('\(qemu\)')
            child.send("change %s %s" % (qemu_floppy0_name, floppy_paths[floppy_index]))
            child.send("\n")
            child.expect('\(qemu\)')
            # Exit qemu command mode
            child.send("\001c\n")

        # Confirm "Installation messages in English"
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
        child.expect("([a-z]): Custom installation")
        child.send(child.match.group(1) + "\n")

        # Enable/disable sets.  First parse the set selection
	# screen; it's messier than most.

        setinfo = { }
        x11_state = None
        x11_letter = None
        while True:
            # Match a letter-label pair, like "h: Compiler Tools".
            # The label can be separated from the "Yes/No" field
            # either by spaces (at least two, so that there can
            # be single spaces within the label), or by a cursor
            # positioning escape sequence.
	    child.expect("([a-z]): ([^ \x1b]+(?: [^ \x1b]+)*)(?:(?:\s\s)|(?:\x1b))")
            (letter, label) = child.match.groups()
            if letter == 'x':
                break
            child.expect("((Yes)|(No)|(All)|(None))\W")
            yesno = child.match.group(1)
            if label == 'X11 sets':
                x11_state = yesno
                x11_letter = letter
            for set in Version.sets:
                (fn, setlabel, enable) = set
                # Could use RE match here fore more flexibility
		if label == setlabel:
                    setinfo[fn] = { 'letter': letter, 'state': yesno }

        # Then make the actual selections
        for set in Version.sets:
            (fn, setlabel, enable) = set
            info = setinfo.get(fn)
            if info is None:
                continue
            state = info['state']
	    if enable and state == "No" or \
		    not enable and state == "Yes":
		child.send(info['letter'] + "\n")

        # If the X11 sets are selected by default, deselect them
        if x11_state == "All":
            child.send(x11_letter + "\n")
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
        # Press cursor-down enough times to get to the end of the list,
        # then enter to continue.  Previously, we used control-N ("\016"), 
        # but if it gets echoed (which has happened), it is interpreted by
        # the terminal as "enable line drawing character set", leaving the
        # terminal in an unusable state.
        child.send("\033[B" * 8 + "\n")
        child.expect("x: Partition sizes ok")
        child.send("\n")
        child.expect("Please @nt@r a name for your NetBSD d@sk")
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
        child.expect("([cx]): Continue")
        child.send(child.match.group(1) + "\n")
        # At this point, we will be asked to "Hit enter to continue"
        # either once or twice before we get to the next real question.
        # The first time is
        #
        #     Status: Finished
        #     Command: /sbin/mount -rt cd9660 /dev/cd0a /mnt2
        #     Hit enter to continue
        #
        # but that doesn't always happen; why?  The second one is after
        #
        #     The extraction of the selected sets for NetBSD-3.1 is
        #     complete.  The system is now able to boot from the selected
        #     harddisk.  To complete the installation, sysinst will give
        #     you the opportunity to configure some essential things first.
        #
        # For simplicity, we allow any number of "Hit enter to continue"
        # prompts.
        while True:
            child.expect("(Hit enter to continue)|(Pl@ase choose the @imezon@)")
            if child.match.group(1):
                child.send("\n")
            else:
                break
        # "Press 'x' followed by RETURN to quit the timezone selection"
        child.send("x\n")
        child.expect("a: DES")
        child.send("\n")
        child.expect("root password")
        child.expect("b: No")
        child.send("b\n")
        child.expect("a: /bin/sh")
        child.send("\n")
        # "The installation of NetBSD-3.1 is now complete.  The system
        # should boot from hard disk.  Follow the instructions in the
        # INSTALL document about final configuration of your system.
        # The afterboot(8) manpage is another recommended reading; it
        # contains a list of things to be checked after the first
        # complete boot."
        child.expect("Hit enter to continue")
        child.send("\n")
        child.expect("x: Exit")
        child.send("x\n")
        child.expect("#")  
        child.send("halt\n")
        child.expect("halted by root")
        child.close()
        self.dist.cleanup()

    # Install this version of NetBSD if not installed already

    def install(self):
        # Already installed?
        if os.path.exists(self.wd0_path()):
            return
        try:
            self._install()
        except:
            if os.path.exists(self.wd0_path()):
                os.unlink(self.wd0_path())
            raise

    def boot(self):
        self.install()
        child = pexpect.spawn(qemu, ["-m", "32", \
            "-hda", self.wd0_path(), \
            "-serial", "stdio", "-nographic", "-snapshot", \
            "-no-acpi"])
        # "-net", "nic,model=ne2k_pci", "-net", "user"

	# pexpect 2.1 uses "child.logfile", but pexpect 0.999nb1 uses "child.log_file"
        child.logfile = sys.stdout
        child.log_file = sys.stdout
        child.timeout = 300
        child.setecho(False)
        child.expect("login:")
        # Can't close child here because we still need it if called from interact()
        return child

    def interact(self):
        child = self.boot()
        # We need this in pexpect 2.x or everything will be printed twice
        child.logfile = None
        child.interact()

def login(child):
    child.send("\n")
    child.expect("login:")
    child.send("root\n")
    child.expect("\n# ")

def net_setup(child):
    child.send("dhclient ne2\n")
    child.expect("bound to.*\n# ")

def shell_cmd(child, cmd):
    child.send(cmd + "\n")
    child.expect("\n# ")

#############################################################################
