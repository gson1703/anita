#
# This is the library part of Anita, the Automated NetBSD Installation
# and Test Application.
#

import os
import pexpect
import re
import string
import subprocess
import sys
import time
import urllib
import urlparse

# Your preferred NetBSD FTP mirror site.
# This is used only by the obsolete code for getting releases
# by number, not by the recommended method of getting them by URL.
# See http://www.netbsd.org/mirrors/#ftp for the complete list.

netbsd_mirror_url = "ftp://ftp.netbsd.org/pub/NetBSD/"
#netbsd_mirror_url = "ftp://ftp.fi.NetBSD.org/pub/NetBSD/"

arch_qemu_map = {
    'i386': 'qemu',
    'amd64': 'qemu-system-x86_64',
    'sparc': 'qemu-system-sparc',
     # The following ones don't actually work
    'sparc64': 'qemu-system-sparc64',
    'macppc': 'qemu-system-ppc',
}

# External commands we rely on

qemu_img = "qemu-img"
if os.uname()[0] == 'NetBSD':
    makefs = ["makefs", "-t", "cd9660", "-o", "rockridge"]
elif os.uname()[0] == 'FreeBSD':
    makefs = ["mkisofs", "-r", "-o"]
else:
    # For Linux, and maybe others
    # On Ubuntu, this is in the "genisoimage" package
    makefs = ["genisoimage", "-r", "-o"]

# Create a directory if missing

def mkdir_p(dir):
    if not os.path.isdir(dir):
        os.makedirs(dir)

# Run a shell command safely and with error checking

def spawn(command, args):
    ret = os.spawnvp(os.P_WAIT, command, args)
    if ret != 0:
        raise RuntimeError("could not run " + command)

# Subclass urllib.FancyURLopener so that we can catch
# HTTP 404 errors

class MyURLopener(urllib.FancyURLopener):
    def http_error_default(self, url, fp, errcode, errmsg, headers):
        raise IOError, 'HTTP error code %d' % errcode

def my_urlretrieve(url, filename):
    return MyURLopener().retrieve(url, filename)

# Download a file, cleaning up the partial file if the transfer
# fails or is aborted before completion.

def download_file(file, url):
    try:
        print "Downloading", url, "..."
        my_urlretrieve(url, file)
    except:
        if os.path.exists(file):
            os.unlink(file)
        raise

# Download "url" to the local file "file".  If the file already
# exists locally, do nothing.  If "optional" is true, ignore download
# failures and cache the absence of a missing file by creating a marker
# file with the extension ".MISSING".

def download_if_missing_2(url, file, optional = False):
    if os.path.exists(file):
        return
    if os.path.exists(file + ".MISSING"):
        return
    dir = os.path.dirname(file)
    mkdir_p(dir)
    try:
        download_file(file, url)
    except:
        if optional:
            f = open(file + ".MISSING", "w")
            f.close()
        else:
            raise

# As above, but download a file from the download directory tree
# rooted at "urlbase" into a mirror tree rooted at "dirbase".  The
# file name to download is "relfile", which is relative to both roots.

def download_if_missing(urlbase, dirbase, relfile, optional = False):
    url = urlbase + relfile
    file = os.path.join(dirbase, relfile)
    return download_if_missing_2(url, file, optional)

# Map a URL to a directory name.  No two URLs should map to the same
# directory.

def url2dir(url):
    tail = []
    def munge(match):
        index = string.find("/:+-", match.group())
        if index != 0:
            tail.append(chr(0x60 + index) + str(match.start()))
        return "-"
    return "work-" + re.sub("[/:+-]", munge, url) + "+" + "".join(tail)

# Inverse of the above; not used, but included just to show that the
# mapping is invertible and therefore collision-free

class InvalidDir(Exception):
    pass

def dir2url(dir):
    match = re.match(r"(work-)(.*)\+(.*)", dir)
    work, s, tail = match.groups()
    if work != 'work-':
        raise InvalidDir()
    s = re.sub("-", "/", s)
    chars = list(s)
    while True:
        m = re.match(r"([a-z])([0-9]+)", tail)
        if not m:
            break
        c, i = m.groups()
	chars[int(i)] = "/:+-"[ord(c) - 0x60]
        tail = tail[m.end():]
    return "".join(chars)

def check_arch_supported(arch, dist_type):
    if arch_qemu_map.get(arch) is None:
        raise RuntimeError(("'%s' is not the name of a " + \
        "supported NetBSD port") % arch)
    if (arch == 'i386' or arch == 'amd64') and dist_type != 'reltree':
        raise RuntimeError(("NetBSD/%s must be installed from " +
	    "a release tree, not an ISO") % arch)
    if (arch == 'sparc') and dist_type != 'iso':
        raise RuntimeError(("NetBSD/%s must be installd from " +
	"an ISO, not a release tree") % arch)

#############################################################################

# A NetBSD version.
#
# Subclasses should define:
#
#    dist_url(self)
#	the URL for the top of the download tree where the version
#       can be downloaded
#
#    default_workdir(self)
#        a file name component identifying the version, for use in
#        constructing a unique, version-specific working directory
#
#    arch(self)
#        the name of the machine architecture the version is for

class Version:
    # Information about the available installation file sets.
    # Each is a tuple of four fields:
    #   - the file name
    #   - the label used by sysinst
    #   - a flag indicating that the set should be installed by default
    #   - a flag indicating that the set is not present in all versions
    sets = [
      ( 'kern-GENERIC', 'Kernel (GENERIC)', 1, 0 ),
      ( 'kern-GENERIC.NOACPI', 'Kernel (GENERIC.NOACPI)', 0, 1 ),
      ( 'modules', 'Kernel Modules', 1, 1 ),
      ( 'base', 'Base', 1, 0 ),
      ( 'etc', 'System (/etc)', 1, 0 ),
      ( 'comp', 'Compiler Tools', 1, 0 ),
      ( 'games', 'Games', 0, 0 ),
      ( 'man', 'Online Manual Pages', 0, 0 ),
      ( 'misc', 'Miscellaneous', 0, 0 ),
      ( 'tests', 'Test programs', 1, 1 ),
      ( 'text', 'Text Processing Tools', 0, 0 ),
    ]
    def __init__(self):
        self.tempfiles = []
    def set_workdir(self, dir):
        self.workdir = dir
    # The directory where we mirror files needed for installation
    def download_local_mi_dir(self):
        return self.workdir + "/download/"
    def download_local_arch_dir(self):
        return self.download_local_mi_dir() + self.arch() + "/"
    # The path to the install ISO image
    def iso_path(self):
        return os.path.join(self.workdir, self.iso_name())
    # The directory for the install floppy images
    def floppy_dir(self):
        return os.path.join(self.download_local_arch_dir(),
	    "installation/floppy")

    def boot_from_floppy(self):
        return True

    # The list of boot floppies we should try downloading;
    # not all may actually exist.  amd64 currently has five,
    # i386 has three, and older versions may have fewer.
    # Add a couple extra to accomodate future growth.
    def potential_floppies(self):
        return ['boot-com1.fs'] + ['boot%i.fs' % i for i in range(2, 8)]

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
        # boot floppies.  Treat any floppies past the first two as
        # optional files.
        i = 0
        for floppy in self.potential_floppies():
            download_if_missing(self.dist_url(),
                self.download_local_arch_dir(),
                os.path.join("installation/floppy/", floppy),
                i >= 2)
            i = i + 1

        for set in Version.sets:
            (fn, label, enable, optional) = set
            if enable:
                download_if_missing(self.dist_url(),
                                    self.download_local_arch_dir(), \
                                    os.path.join("binary/sets", fn + ".tgz"),
                                    optional)

    # Create an install ISO image to install from
    def make_iso(self):
        self.download()
        if not os.path.exists(self.iso_path()):
	    spawn(makefs[0], makefs + \
		[self.iso_path(), self.download_local_mi_dir()])
            self.tempfiles.append(self.iso_path())

    # Get the architecture name.  This is a hardcoded default for use
    # by the obsolete subclasses; the "URL" class overrides it.
    def arch(self):
        return "i386"

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
        return netbsd_mirror_url + "NetBSD-" + self.ver + "/i386/"

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
            branch + "/" + self.timestamp + "/i386/"

# A local build

class LocalBuild(NumberedVersion):
    def __init__(self, ver, release_path):
        NumberedVersion.__init__(self, ver)
        self.release_path = release_path
    def dist_url(self):
        return "file://" + self.release_path + "/i386/"

# The top-level URL of a release tree

class URL(Version):
    def __init__(self, url):
        Version.__init__(self)
        self.url = url
	match = re.search(r'/([^/]+)/$', url)
	if match is None:
            raise RuntimeError(("URL '%s' doesn't look like the URL of a " + \
	    "NetBSD distribution") % url)
        self.m_arch = match.group(1)
	check_arch_supported(self.m_arch, 'reltree')
    def dist_url(self):
        return self.url
    def iso_name(self):
        return "install_tmp.iso"
    def default_workdir(self):
        return url2dir(self.url)
    def arch(self):
        return self.m_arch

# A local release directory

class LocalDirectory(URL):
    def __init__(self, dir):
        # This could be optimized to avoid copying the files
        URL.__init__(self, "file://" + dir)

# An URL or local file name pointing at an ISO image

class ISO(Version):
    def __init__(self, iso_url):
        Version.__init__(self)
        if re.match(r'/', iso_url):
	    self.m_iso_url = "file://" + iso_url
	    self.m_iso_path = iso_url
	else:
            self.m_iso_url = iso_url
	    self.m_iso_path = None
	# We can't determine the final ISO file name yet because the work
	# directory is not known at this point, but we can precalculate the
	# basename of it.
	self.m_iso_basename = os.path.basename(
	    urllib.url2pathname(urlparse.urlparse(iso_url)[2]))
	m = re.match("(.*)cd.*iso", self.m_iso_basename)
	if m is None:
            raise RuntimeError("cannot guess architecture from ISO name '%s'"
	        % self.m_iso_basename)
	self.m_arch = m.group(1)
	check_arch_supported(self.m_arch, 'iso')
    def iso_path(self):
        if self.m_iso_path is not None:
	    return self.m_iso_path
	else:
            return os.path.join(self.download_local_arch_dir(),
	        self.m_iso_basename)
    def default_workdir(self):
         return url2dir(self.m_iso_url)
    def make_iso(self):
        self.download()
    def download(self):
        if self.m_iso_path is None:
            download_if_missing_2(self.m_iso_url, self.iso_path())
	else:
	    mkdir_p(self.workdir)
    def arch(self):
        return self.m_arch
    def boot_from_floppy(self):
        return False

#############################################################################

class Anita:
    def __init__(self, dist, workdir = None, qemu_args = None,
        disk_size = None):
        self.dist = dist
        if workdir:
            self.workdir = workdir
        else:
            self.workdir = dist.default_workdir()

	# Set the default disk size if none was given.
	# 384M is sufficient for i386 but not for amd64.
        if disk_size is None:
	    disk_size = "512M"
	self.disk_size = disk_size

	self.qemu = arch_qemu_map.get(dist.arch())
	if self.qemu is None:
            raise RuntimeError("NetBSD port '%s' is not supported" %
	        dist.arch())

        if qemu_args is None:
            qemu_args = []
        self.extra_qemu_args = qemu_args

    # The path to the NetBSD hard disk image
    def wd0_path(self):
        return os.path.join(self.workdir, "wd0.img")

    def start_qemu(self, qemu_args, snapshot_system_disk):
        child = pexpect.spawn(self.qemu, [
	    "-m", "32",
            "-drive", "file=%s,index=0,media=disk,snapshot=%s" %
	        (self.wd0_path(), ("off", "on")[snapshot_system_disk]),
            "-nographic"
            ] + qemu_args + self.extra_qemu_args)
	# pexpect 2.1 uses "child.logfile", but pexpect 0.999nb1 uses
	# "child.log_file", so we set both variables for portability
        child.logfile = sys.stdout
        child.log_file = sys.stdout
        child.timeout = 300
        child.setecho(False)
	self.child = child
        return child

    def _install(self):
        # Get the install ISO
        self.dist.set_workdir(self.workdir)
        self.dist.make_iso()

	arch = self.dist.arch()
	boot_from_floppy = self.dist.boot_from_floppy()

	# Create a disk image file
        spawn(qemu_img, ["qemu-img", "create", self.wd0_path(), self.disk_size])

        qemu_args = ["-cdrom", self.dist.iso_path()]

        if boot_from_floppy:
	    floppy_paths = [ os.path.join(self.dist.floppy_dir(), f) \
		for f in self.dist.floppies() ]
	    if len(floppy_paths) == 0:
	        raise RuntimeError("found no boot floppies")
            qemu_args += ["-fda", floppy_paths[0], "-boot", "a"]
	else:
	    qemu_args += ["-boot", "d"]

        child = self.start_qemu(qemu_args, snapshot_system_disk = False)

        if boot_from_floppy:
	    # Do the floppy swapping dance
	    floppy0_name = None
	    while True:
		child.expect("(insert disk (\d+), and press return...)|" +
		    "(a: Installation messages in English)")
		if not child.match.group(1):
		    break
		# There is no floppy 0, hence the "- 1"
		floppy_index = int(child.match.group(2)) - 1

		# Escape into qemu command mode to switch floppies
		child.send("\001c")
		# We used to wait for a (qemu) prompt here, but qemu 0.9.1
		# no longer prints it
		# child.expect('\(qemu\)')
		if not floppy0_name:
		    # Between qemu 0.9.0 and 0.9.1, the name of the floppy
		    # device accepted by the "change" command changed from
		    # "fda" to "floppy0" without any provision for backwards
		    # compatibility.  Deal with it.
		    child.send("info block\n")
		    child.expect(r'\n(\w+): type=floppy')
		    floppy0_name = child.match.group(1)
		# Now we chan change the floppy
		child.send("change %s %s\n" %
		    (floppy0_name, floppy_paths[floppy_index]))
		# Exit qemu command mode
		child.send("\001c\n")
        else:
	    if self.dist.arch() == 'sparc':
	        child.expect("Installation medium to load the " +
		    "additional utilities from: ")
		child.send("cdrom\n")
	        child.expect("CD-ROM device to use")
		child.send("\n")
	        child.expect("Path to instfs.tgz")
		child.send("\n")
	        child.expect("Terminal type")
		# The default is "sun", but anita is more likely to run
		# in an xterm or some other ansi-like terminal than on
		# a sun console.
		child.send("xterm\n")
	        child.expect("nstall/Upgrade")
		child.send("I\n")
	    child.expect("a: Installation messages in English")

        # Confirm "Installation messages in English"
        child.send("\n")
	# i386 and amd64 ask for keyboard type here; sparc doesn't
	while True:
            child.expect("(Keyboard type)|(a: Install NetBSD to hard disk)|" +
	        "(Shall we continue)")
            if child.match.group(1) or child.match.group(2):
	        child.send("\n")
	    elif child.match.group(3):
                child.expect("b: Yes")
	        child.send("b\n")
	        break
            else:
	        raise AssertionError

        # Depending on the number of disks attached, we get either
        # "Found only one disk" followed by "Hit enter to continue",
        # or "On which disk do you want to install".
        child.expect("(Hit enter to continue)|" +
	    "(On which disk do you want to install)")
	if child.match.group(1):
            child.send("\n")
	elif child.match.group(2):
	    child.send("a\n")
        else:
            raise AssertionError

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
	    child.expect(
	        "([a-z]): ([^ \x1b]+(?: [^ \x1b]+)*)(?:(?:\s\s)|(?:\x1b))")
            (letter, label) = child.match.groups()
            if letter == 'x':
                break
            child.expect("((Yes)|(No)|(All)|(None))\W")
            yesno = child.match.group(1)
            if label == 'X11 sets':
                x11_state = yesno
                x11_letter = letter
            for set in Version.sets:
                (fn, setlabel, enable, optional) = set
                # Could use RE match here fore more flexibility
		if label == setlabel:
                    setinfo[fn] = { 'letter': letter, 'state': yesno }

        # Then make the actual selections
        for set in Version.sets:
            (fn, setlabel, enable, optional) = set
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

	if arch == 'i386' or arch == 'amd64':
	    child.expect("(a: This is the correct geometry)|" +
	        "(a: Use one of these disks)")
            if child.match.group(1):
	        child.send("\n")
	    elif child.match.group(2):
	        child.send("a\n")
		child.expect("Choose disk")
		child.send("0\n")
	    else:
		raise AssertionError
	    child.expect("b: Use the entire disk")
	    child.send("b\n")
	    child.expect("Do you want to install the NetBSD bootcode")
	    child.expect("a: Yes")
	    child.send("\n")
	    child.send("\n")
        else: # sparc, maybe others
	    child.expect("a: Set sizes of NetBSD partitions")
	    child.send("a\n")

        child.expect("Accept partition sizes")
        # Press cursor-down enough times to get to the end of the list,
	# to the "Accept partition sizes" entry, then press
        # enter to continue.  Previously, we used control-N ("\016"),
        # but if it gets echoed (which has happened), it is interpreted by
        # the terminal as "enable line drawing character set", leaving the
        # terminal in an unusable state.
	if arch == 'sparc':
	    # For unknown reasons, when using a terminal type of "xterm",
	    # sysinst puts the terminal in "application mode", causing the
	    # cursor keys to send a different escape sequence than the default.
	    cursor_down = "\033OB"
	else:
	    # Use the default ANSI cursor-down escape sequence
	    cursor_down = "\033[B"
        child.send(cursor_down * 8 + "\n")

        child.expect("x: Partition sizes ok")
        child.send("\n")
        child.expect("Please enter a name for your NetBSD disk")
        child.send("\n")

        # "This is your last chance to quit this process..."
        child.expect("Shall we continue")
        child.expect("b: Yes")
        child.send("b\n")

	# newfs is run at this point

	# Many different things can happen at this point:
        #
        # Versions older than 2009/08/23 21:16:17 will display a menu
	# for choosing the extraction verbosity
	#
	# Versions older than 2010/03/30 20:09:25 will display a menu for
	# choosing the CD-ROM device (newer versions will choose automatically)
	#
	# At various points, we may or may not get "Hit enter to continue"
	# prompts (and some of them seem to appear nondeterministically)
	#
	# i386/amd64 can ask whether to use normal or serial console bootblocks
        #
	# Try to deal with all of the possible options.
        #
        # We specify a longer timeout than the default here, because the
        # set extraction can take a long time on slower machines.
	#
        # It has happened (at least with NetBSD 3.0.1) that sysinst paints the
	# screen twice.  This can cause problem because we will then respond
	# twice, and the second response will be interpreted as a response to
	# a subsequent prompt.  Therefore, we check whether the match is the
	# same as the previous one and ignore it if so.
	#
	prevmatch = []
	loop = 0
        while True:
	    loop = loop + 1
	    if loop == 10:
	        raise RuntimeError("loop detected")
	    child.expect("(a: Progress bar)|(a: CD-ROM)|(([cx]): Continue)|" +
	        "(Hit enter to continue)|(b: Use serial port com0)|" +
		"(Please choose the timezone)", 1200)
            print "GROUPS", child.match.groups()
	    if child.match.groups() == prevmatch:
	        print "PREVMATCH"
	        continue
	    prevmatch = child.match.groups()
	    if child.match.group(1):
	        # (a: Progress bar)
		child.send("\n")
	    elif child.match.group(2):
	        # (a: CD-ROM)
		child.send("\n")
            elif child.match.group(3):
	        # CDROM device selection
	        # (([cx]): Continue)
		# In 3.0.1, you type "c" to continue, whereas in -current,
		# you type "x".  Handle both cases.
		child.send(child.match.group(4) + "\n")
	    elif child.match.group(5):
	        # (Hit enter to continue)
		child.send("\n")
            elif child.match.group(6):
	        # (b: Use serial port com0)
                child.send("bx\n")
	    elif child.match.group(7):
	        # (Please choose the timezone)
		break
	    else:
	        raise AssertionError

        # "Press 'x' followed by RETURN to quit the timezone selection"
        child.send("x\n")
        child.expect("([a-z]): DES")
        child.send(child.match.group(1) + "\n")
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
	# On i386 and amd64, you get a root shell; sparc halts.
        child.expect("(#)|(halting machine)")
	if child.match.group(1):
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

    # Boot the virtual machine (installing it first if it's not
    # installed already).  The qemu_args argument applies when
    # booting, but not when installing.
    def boot(self, qemu_args = None):
        if qemu_args is None:
            qemu_args = []
        self.install()
        child = self.start_qemu(qemu_args, snapshot_system_disk = True)
        # "-net", "nic,model=ne2k_pci", "-net", "user"
        child.expect("login:")
        # Can't close child here because we still need it if called from
	# interact()
	self.child = child
        return child

    # Deprecated
    def interact(self):
        child = self.boot()
        console_interaction(child)

    def run_atf_tests(self):
	# Create a scratch disk image for exporting test results from the VM.
        # The results are stored in tar format because that is more portable
        # and easier to manipulate than a file system image, especially if the
        # host is a non-NetBSD system.
	scratch_disk_path = os.path.join(self.workdir, "atf-results.img")
	export_files = ['test.atfraw', 'test.atfxml']
        # not yet: 'test-results.xsl', 'test-results.css'
        spawn(qemu_img, ["qemu-img", "create", scratch_disk_path, '10M'])
        child = self.boot(["-drive",
                           "file=%s,index=1,media=disk,snapshot=off" %
                           scratch_disk_path])
	login(child)
        exit_status = shell_cmd(child,
	    "cd /usr/tests && " +
            "{ atf-run; echo $? >/tmp/test.status; } | " +
	    "tee /tmp/test.atfraw | " +
	    "atf-report -o ticker:- -o xml:/tmp/test.atfxml; " +
	    "{ cd /tmp && " +
                # To guard against accidentally overwriting the wrong
                # disk image, check that the disk contains nothing
                # but nulls.
                "test `</dev/rwd1d tr -d '\\000' | wc -c` = 0 && " +
                # "disklabel -W /dev/rwd1d && " +
                "tar cf /dev/rwd1d %s; " % " ".join(export_files) +
            "}; " +
	    "sh -c 'exit `cat /tmp/test.status`'",
            3600)
	# We give tar an explicit list of files to extract to eliminate
	# the possibility of an arbitrary file overwrite attack if
	# anita is used to test an untrusted virtual machine.
        subprocess.call(["tar", "xf", scratch_disk_path] + export_files,
	    cwd = self.workdir)
        return exit_status

def console_interaction(child):
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

def shell_cmd(child, cmd, timeout = -1):
    child.send(cmd + "\n")
    child.expect("# ", timeout)
    child.send("echo $?\n")
    child.expect("(\d+)")
    return int(child.match.group(1))

# Deprecated, use Anita.run_atf_tests
def test(child):
    login(child)
    # We go through some contortions here to return the meaningful exit status
    # from atf-run rather than the meaningless one from atf-report.
    return shell_cmd(child, "cd /usr/tests && " +
        "{ atf-run && :>/tmp/test.ok; } | atf-report && test -f /tmp/test.ok",
        3600)

#############################################################################
