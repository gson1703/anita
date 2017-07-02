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

__version__='1.41'

# Your preferred NetBSD FTP mirror site.
# This is used only by the obsolete code for getting releases
# by number, not by the recommended method of getting them by URL.
# See http://www.netbsd.org/mirrors/#ftp for the complete list.

netbsd_mirror_url = "ftp://ftp.netbsd.org/pub/NetBSD/"
#netbsd_mirror_url = "ftp://ftp.fi.NetBSD.org/pub/NetBSD/"

arch_qemu_map = {
    'i386': 'qemu-system-i386',
    'amd64': 'qemu-system-x86_64',
    'sparc': 'qemu-system-sparc',
    'evbarm-earmv7hf': 'qemu-system-arm',
     # The following ones don't actually work
    'sparc64': 'qemu-system-sparc64',
    'macppc': 'qemu-system-ppc',
}
arch_gxemul_list = ['pmax', 'hpcmips']

# External commands we rely on

if os.uname()[0] == 'NetBSD':
    makefs = ["makefs", "-t", "cd9660", "-o", "rockridge"]
elif os.uname()[0] == 'FreeBSD':
    makefs = ["mkisofs", "-r", "-o"]
elif os.uname()[0] == 'Darwin':
    makefs = ["hdiutil", "makehybrid", "-iso", "-o"]
else:
    # Linux distributions differ.  Ubuntu has genisoimage
    # and mkisofs (as an alias of genisoimage); CentOS has
    # mkisofs only.  Debian 7 has genisoimage only.
    if os.path.isfile('/usr/bin/genisoimage'):
       makefs = ["genisoimage", "-r", "-o"]
    else:
       makefs = ["mkisofs", "-r", "-o"]

fnull = open(os.devnull, 'w')

# Return true if the given program (+args) can be successfully run

def try_program(argv):
   try:
       result = subprocess.call(argv, stdout = fnull, stderr = fnull)
       return result == 0
   except OSError:
       return False

# Create a directory if missing

def mkdir_p(dir):
    if not os.path.isdir(dir):
        os.makedirs(dir)

# Run a shell command safely and with error checking

def spawn(command, args):
    print command, ' '.join(args[1:])
    ret = os.spawnvp(os.P_WAIT, command, args)
    if ret != 0:
        raise RuntimeError("could not run " + command)

# Subclass pexpect.spawn to add logging of expect() calls

class pexpect_spawn_log(pexpect.spawn):
    def __init__(self, logf, *args, **kwargs):
        self.structured_log_f = logf
        return super(pexpect_spawn_log, self).__init__(*args, **kwargs)
    def expect(self, pattern, *args, **kwargs):
        print >>self.structured_log_f, "expect(" + repr(pattern) + ")"
        r = pexpect.spawn.expect(self, pattern, *args, **kwargs)
        print >>self.structured_log_f, "match(" + repr(self.match.group(0)) + ")"
        return r

# Subclass urllib.FancyURLopener so that we can catch
# HTTP 404 errors

class MyURLopener(urllib.FancyURLopener):
    def http_error_default(self, url, fp, errcode, errmsg, headers):
        raise IOError, 'HTTP error code %d' % errcode

def my_urlretrieve(url, filename):
    r = MyURLopener().retrieve(url, filename)
    if sys.version_info >= (2, 7, 12):
        # Work around https://bugs.python.org/issue27973
        urllib.urlcleanup()
    return r

# Download a file, cleaning up the partial file if the transfer
# fails or is aborted before completion.

def download_file(file, url, optional = False):
    try:
        print "Downloading", url + "...",
        sys.stdout.flush()
        my_urlretrieve(url, file)
        print "OK"
        sys.stdout.flush()
    except IOError, e:
        if optional:
            print "missing but optional, so that's OK"
        else:
            print e
        sys.stdout.flush()
        if os.path.exists(file):
            os.unlink(file)
        raise

# Create a file of the given size, containing NULs, without holes.

def make_dense_image(fn, size):
    f = open(fn, "w")
    blocksize = 64 * 1024
    while size > 0:
        chunk = min(size, blocksize)
        f.write("\000" * chunk)
        size = size - chunk
    f.close()

# Parse a size with optional k/M/G/T suffix and return an integer

def parse_size(size):
    m = re.match(r'(\d+)([kMGT])?$', size)
    if not m:
        raise RuntimeError("%s: invalid size" % size)
    size, suffix = m.groups()
    mult = dict(k=1024, M=1024**2, G=1024**3, T=1024**4).get(suffix, 1)
    return int(size) * mult

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
        download_file(file, url, optional)
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

def download_if_missing_3(urlbase, dirbase, relpath, optional = False):
    url = urlbase + "/".join(relpath)
    file = os.path.join(*([dirbase] + relpath))
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
    if arch_qemu_map.get(arch) is None and not arch in arch_gxemul_list:
        raise RuntimeError(("'%s' is not the name of a " + \
        "supported NetBSD port") % arch)
    if (arch == 'i386' or arch == 'amd64') and dist_type != 'reltree':
        raise RuntimeError(("NetBSD/%s must be installed from " +
            "a release tree, not an ISO") % arch)
    if (arch == 'sparc') and dist_type != 'iso':
        raise RuntimeError(("NetBSD/%s must be installed from " +
        "an ISO, not a release tree") % arch)

# Expect any of a set of alternatives.  The *args are alternating
# patterns and actions; an action can be a string to be sent
# or a function to be called with no arguments.  The alternatives
# will be expected repeatedly until the last one in the list has
# been selected.

def expect_any(child, *args):
    # http://stackoverflow.com/questions/11702414/split-a-list-into-half-by-even-and-odd-elements
    patterns = args[0:][::2]
    actions = args[1:][::2]
    while True:
        r = child.expect(list(patterns))
        action = actions[r]
        if isinstance(action, str):
            child.send(action)
        else:
            action()
        if r == len(actions) - 1:
            break

#############################################################################

# A NetBSD version.
#
# Subclasses should define:
#
#    dist_url(self)
#       the top-level URL for the machine-dependent download tree where
#       the version can be downloaded, for example,
#       ftp://ftp.netbsd.org/pub/NetBSD/NetBSD-5.0.2/i386/
#
#    mi_url(self)
#       The top-level URL for the machine-independent download tree,
#       for example, ftp://ftp.netbsd.org/pub/NetBSD/NetBSD-5.0.2/
#
#    default_workdir(self)
#        a file name component identifying the version, for use in
#        constructing a unique, version-specific working directory
#
#    arch(self)
#        the name of the machine architecture the version is for,
#        e.g., i386

def make_item(t):
    d = dict(zip(['filename', 'label', 'install'], t[0:3]))
    if isinstance(t[3], list):
        d['group'] = make_set_dict_list(t[3])
    else:
        d['optional'] = t[3]
    return d

def make_set_dict_list(list_):
    return [make_item(t) for t in list_]

def flatten_set_dict_list(list_):
    def item2list(item):
        group = item.get('group')
        if group:
            return group
        else:
            return [item]
    return sum([item2list(item) for item in list_], [])

class Version:
    # Information about the available installation file sets.  As the
    # set of sets (sic) has evolved over time, this actually represents
    # the union of those sets of sets, in other words, this list should
    # contain all currently and historically known sets.
    #
    # This list is used for to determine
    # - Which sets we should attempt to download
    # - Which sets we should install by default
    #
    # Each array element is a tuple of four fields:
    #   - the file name
    #   - a regular expression matching the label used by sysinst
    #     (taking into account that it may differ between sysinst versions)
    #   - a flag indicating that the set should be installed by default
    #   - a flag indicating that the set is not present in all versions
    #

    sets = make_set_dict_list([
      [ 'kern-GENERIC', 'Kernel (GENERIC)', 1, 0 ],
      [ 'kern-GENERIC.NOACPI', 'Kernel \(GENERIC\.NOACPI\)', 0, 1 ],
      [ 'modules', 'Kernel [Mm]odules', 1, 1 ],
      [ 'base', 'Base', 1, 0 ],
      [ 'etc', '(System)|(System configuration files)|(Configuration files) \(/etc\)', 1, 0 ],
      [ 'comp', 'Compiler [Tt]ools', 1, 0 ],
      [ 'games', 'Games', 0, 0 ],
      [ 'man', '(Online )?Manual [Pp]ages', 0, 0 ],
      [ 'misc', 'Miscellaneous', 1, 0 ],
      [ 'tests', 'Test programs', 1, 1 ],
      [ 'text', 'Text [Pp]rocessing [Tt]ools', 0, 0 ],
      [ '_x11', 'X11 sets', 0, [
          ['xbase',   'X11 base and clients', 0, 1 ],
          ['xcomp',   'X11 programming', 0, 1 ],
          ['xetc',    'X11 configuration', 0, 1 ],
          ['xfont',   'X11 fonts', 0, 1 ],
          ['xserver', 'X11 servers', 0, 1 ],
      ]],
      [ '_src', 'Source (and debug )?sets', 0, [
          ['syssrc', 'Kernel sources', 0, 1],
          ['src', 'Base sources', 0, 1],
          ['sharesrc', 'Share sources', 0, 1],
          ['gnusrc', 'GNU sources', 0, 1],
          ['xsrc', 'X11 sources', 0, 1],
          ['debug', '(debug sets)|(Debug symbols)', 0, 1],
          ['xdebug', '(debug X11 sets)|(X11 debug symbols)', 0, 1],
      ]]
    ])

    flat_sets = flatten_set_dict_list(sets)

    def __init__(self, sets = None):
        self.tempfiles = []
        if sets is not None:
            if not any([re.match('kern-', s) for s in sets]):
                raise RuntimeError("no kernel set specified")
            # Create a Python set containing the names of the NetBSD sets we
            # want for O(1) lookup.  Yes, the multiple meansings of the word
            # "set" here are confusing.
            sets_wanted = set(sets)
            for required in ['base', 'etc']:
                if not required in sets_wanted:
                    raise RuntimeError("the '%s' set is required", required)
            for s in self.flat_sets:
                s['install'] = (s['filename'] in sets_wanted)
                sets_wanted.discard(s['filename'])
            if len(sets_wanted):
                raise RuntimeError("no such set: " + sets_wanted.pop())

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
    def boot_iso_dir(self):
        return os.path.join(self.download_local_arch_dir(),
            "installation/cdrom")
    def boot_from_default(self):
        return None
    def scratch_disk(self):
        arch = self.arch()
        if arch == 'i386' or arch == 'amd64':
            return "wd1d"
        else:
            return "sd1c"

    def xen_kernel(self):
        arch = self.arch()
        if arch == 'i386':
            return 'netbsd-XEN3PAE_DOMU.gz'
        elif arch == 'amd64':
            return 'netbsd-XEN3_DOMU.gz'
        else:
            return None

    def xen_install_kernel(self):
        arch = self.arch()
        if arch == 'i386':
            return 'netbsd-INSTALL_XEN3PAE_DOMU.gz'
        elif arch == 'amd64':
            return 'netbsd-INSTALL_XEN3_DOMU.gz'
        else:
            return None

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

    def boot_isos(self):
        return ['boot-com.iso']

    def cleanup(self):
        for fn in self.tempfiles:
            os.unlink(fn)

    def set_path(self, setname):
        if re.match(r'.*src$', setname):
            return ['source', 'sets', setname + '.tgz']
        else:
            return [self.arch(), 'binary', 'sets', setname + '.tgz']

    # Download this release
    # The ISO class overrides this to download the ISO only
    def download(self):
        # Depending on the NetBSD version, there may be two or more
        # boot floppies.  Treat any floppies past the first two as
        # optional files.
        if hasattr(self, 'url') and self.url[:7] == 'file://':
            mkdir_p(os.path.join(self.workdir, 'download'))
            if not os.path.lexists(os.path.join(self.workdir, 'download', self.arch())):
                os.symlink(self.url[7:], os.path.join(self.workdir, 'download', self.arch()))
            return
        if self.arch() == 'evbarm-earmv7hf':
            for file in ['netbsd-VEXPRESS_A15.ub.gz']:
                download_if_missing_3(self.dist_url(), self.download_local_arch_dir(), ["binary", "kernel", file])
            download_if_missing_3(self.dist_url(), self.download_local_arch_dir(), ["binary", "gzimg", "armv7.img.gz"])
            return
        if self.arch() == 'hpcmips':
            download_if_missing_3(self.dist_url(), self.download_local_arch_dir(), ["installation", "netbsd.gz"])
            download_if_missing_3(self.dist_url(), self.download_local_arch_dir(), ["binary", "kernel", "netbsd-GENERIC.gz"])
        i = 0
        for floppy in self.potential_floppies():
            download_if_missing_3(self.dist_url(),
                self.download_local_arch_dir(),
                ["installation", "floppy", floppy],
                True)
            i = i + 1

        for bootcd in (self.boot_isos()):
            download_if_missing_3(self.dist_url(),
                self.download_local_arch_dir(),
                ["installation", "cdrom", bootcd],
                True)

        # These are used with noemu only
        download_if_missing_3(self.dist_url(),
            self.download_local_arch_dir(),
            ["installation", "misc", "pxeboot_ia32.bin"],
            True)
        download_if_missing_3(self.dist_url(),
            self.download_local_arch_dir(),
            ["binary", "kernel", "netbsd-INSTALL.gz"],
            True)

        for set in self.flat_sets:
            if set['install']:
                download_if_missing_3(self.mi_url(),
                                      self.download_local_mi_dir(),
                                      self.set_path(set['filename']),
                                      set['optional'])

    # Create an install ISO image to install from
    def make_iso(self):
        self.download()
        spawn(makefs[0], makefs + \
            [self.iso_path(), os.path.dirname(os.path.realpath(os.path.join(self.download_local_mi_dir(), self.arch())))])
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
    def __init__(self, ver, **kwargs):
        Version.__init__(self, **kwargs)
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
    def __init__(self, ver, **kwargs):
        NumberedVersion.__init__(self, ver, **kwargs)
        pass
    def mi_url(self):
        return netbsd_mirror_url + "NetBSD-" + self.ver + "/"
    def dist_url(self):
        return self.mi_url() + self.arch() + "/"

# A daily build

class DailyBuild(NumberedVersion):
    def __init__(self, branch, timestamp, **kwargs):
        ver = re.sub("^netbsd-", "", branch)
        NumberedVersion.__init__(self, ver, **kwargs)
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
    def __init__(self, ver, release_path, **kwargs):
        NumberedVersion.__init__(self, ver, **kwargs)
        self.release_path = release_path
    def dist_url(self):
        return "file://" + self.release_path + "/i386/"

# The top-level URL of a release tree

class URL(Version):
    def __init__(self, url, **kwargs):
        Version.__init__(self, **kwargs)
        self.url = url
        match = re.match(r'(^.*/)([^/]+)/$', url)
        if match is None:
            raise RuntimeError(("URL '%s' doesn't look like the URL of a " + \
            "NetBSD distribution") % url)
        self.url_mi_part = match.group(1)
        self.m_arch = match.group(2)
        check_arch_supported(self.m_arch, 'reltree')
    def dist_url(self):
        return self.url
    def mi_url(self):
        return self.url_mi_part
    def iso_name(self):
        return "install_tmp.iso"
    def default_workdir(self):
        return url2dir(self.url)
    def arch(self):
        return self.m_arch

# A local release directory

class LocalDirectory(URL):
    def __init__(self, dir, **kwargs):
        # This could be optimized to avoid copying the files
        URL.__init__(self, "file://" + dir, **kwargs)

# An URL or local file name pointing at an ISO image

class ISO(Version):
    def __init__(self, iso_url, **kwargs):
        Version.__init__(self, **kwargs)
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
        m = re.match(r"(.*)cd.*iso|NetBSD-[0-9\._A-Z]+-(.*).iso", self.m_iso_basename)
        if m is None:
            raise RuntimeError("cannot guess architecture from ISO name '%s'"
                % self.m_iso_basename)
        if m.group(1) is not None:
            self.m_arch = m.group(1)
        if m.group(2) is not None:
            self.m_arch = m.group(2)
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
    def boot_from_default(self):
        return 'cdrom-with-sets'

#############################################################################

# Helper class for killing the DomU when the last reference to the
# child process is dropped

class DomUKiller:
    def __init__(self, frontend, name):
        self.name = name
        self.frontend = frontend
    def __del__(self):
        print "destroying domU", self.name
        spawn(self.frontend, [self.frontend, "destroy", self.name])

def vmm_is_xen(vmm):
    return vmm == 'xm' or vmm == 'xl'

def slog(fd, tag, data):
    print >>fd, "%s(%.3f, %s)" % (tag, time.time(), repr(data))

def slog_info(fd, data):
    slog(fd, 'info', data)

# A file-like object that escapes unprintable data and prefixes each
# line with a tag, for logging I/O.

class Logger:
    def __init__(self, tag, fd):
        self.tag = tag
        self.fd = fd
    def write(self, data):
        slog(self.fd, self.tag, data)
    def __getattr__(self, name):
        return getattr(self.fd, name)

# http://stackoverflow.com/questions/616645/how-do-i-duplicate-sys-stdout-to-a-log-file-in-python
class multifile(object):
    def __init__(self, files):
        self._files = files
    def __getattr__(self, attr, *args):
        return self._wrap(attr, *args)
    def _wrap(self, attr, *args):
        def g(*a, **kw):
            for f in self._files:
                res = getattr(f, attr, *args)(*a, **kw)
            return res
        return g

class Anita:
    def __init__(self, dist, workdir = None, vmm = None, vmm_args = None,
        disk_size = None, memory_size = None, persist = False, boot_from = None,
        structured_log = None, structured_log_file = None, no_install = False, tests = 'atf', dtb = ''):
        self.dist = dist
        if workdir:
            self.workdir = workdir
        else:
            self.workdir = dist.default_workdir()

        self.structured_log = structured_log
        self.structured_log_file = structured_log_file

        if self.structured_log_file:
            self.structured_log_f = open(self.structured_log_file, "w")
            self.unstructured_log_f = sys.stdout
        else:
            if self.structured_log:
                self.structured_log_f = sys.stdout
                self.unstructured_log_f = open("/dev/null", "w")
            else:
                self.structured_log_f = open("/dev/null", "w")
                self.unstructured_log_f = sys.stdout

        # Set the default disk size if none was given.
        if disk_size is None:
            if self.dist.arch() == 'evbarm-earmv7hf':
                disk_size = '2G'
            else:
                disk_size = '1536M'
        self.disk_size = disk_size

        # Set the default memory size if none was given.
        if memory_size is None:
            if dist.arch() in ['amd64', 'evbarm-earmv7hf', 'pmax']:
                memory_size = "128M"
            else:
                memory_size = "32M"
        self.memory_size_bytes = parse_size(memory_size)

        self.persist = persist
        self.boot_from = boot_from
        self.no_install = no_install

        self.qemu = arch_qemu_map.get(dist.arch())
        if self.qemu is None and not self.dist.arch() in arch_gxemul_list:
            raise RuntimeError("NetBSD port '%s' is not supported" %
                dist.arch())

        if self.qemu == 'qemu-system-i386' and \
           not try_program(['qemu-system-i386', '--version']) \
           and try_program(['qemu', '--version']): \
               self.qemu = 'qemu'

        # Backwards compatibility
        if vmm == 'xen':
            vmm = 'xm'
        elif not vmm and self.qemu:
            vmm = 'qemu'
        else:
            vmm = 'gxemul'

        self.vmm = vmm

        if vmm_args is None:
            vmm_args = []
        if self.dist.arch() == 'pmax':
            vmm_args += ["-e3max"]
        elif self.dist.arch() == 'hpcmips':
            vmm_args += ["-emobilepro880"]
        if dist.arch() == 'evbarm-earmv7hf':
            vmm_args += ['-M', 'vexpress-a15', '-kernel', os.path.join(self.workdir, 'netbsd-VEXPRESS_A15.ub'),
            '-append', "root=ld0a", '-dtb', dtb]
        self.extra_vmm_args = vmm_args

        self.is_logged_in = False
        self.tests = tests
        if dist.arch() == 'evbarm-earmv7hf':
            self.boot_from = 'sd'

    def slog(self, message):
        slog_info(self.structured_log_f, message)

    # Wrapper around pexpect.spawn to let us log the command for
    # debugging.  Note that unlike os.spawnvp, args[0] is not
    # the name of the command.

    def pexpect_spawn(self, command, args):
        print command, " \\\n    ".join(args)
        return pexpect_spawn_log(self.structured_log_f, command, args)

    # The path to the NetBSD hard disk image
    def wd0_path(self):
        return os.path.join(self.workdir, "wd0.img")

    # Return the memory size rounded up to whole megabytes
    def memory_megs(self):
        megs = (self.memory_size_bytes + 2 ** 20 - 1) / 2 ** 20
        if megs != self.memory_size_bytes / 2 **20:
            print >>sys.stderr, \
                "warning: rounding up memory size of %i bytes to %i megabytes" \
                % (self.memory_size_bytes, megs)
        return megs

    def configure_child(self, child):
        # Log reads from child
        child.logfile_read = multifile([self.unstructured_log_f, Logger('recv', self.structured_log_f)])
        # Log writes to child
        child.logfile_send = multifile([self.unstructured_log_f, Logger('send', self.structured_log_f)])
        child.timeout = 600
        child.setecho(False)
        # Xen installs sometimes fail if we don't increase this
        # from the default of 0.1 seconds.  And powering down noemu
        # using iLO3 over ssh takes more than 5 seconds.
        child.delayafterclose = 30.0
        # Also increase this just in case
        child.delayafterterminate = 30.0
        self.child = child

    def start_gxemul(self, vmm_args):
        child = self.pexpect_spawn('gxemul', ["-M", str(self.memory_megs()) + 'M',
         "-d", os.path.abspath(self.wd0_path())] + self.extra_vmm_args + vmm_args)
        self.configure_child(child)
        return child
    def start_qemu(self, vmm_args, snapshot_system_disk):
        # Log the qemu version to stdout
        subprocess.call([self.qemu, '--version'])
        # Start the actual qemu child process
        child = self.pexpect_spawn(self.qemu, [
            "-m", str(self.memory_megs()),
            "-drive", ("file=%s,format=raw,media=disk,snapshot=%s" %
                (self.wd0_path(), ("off", "on")[snapshot_system_disk])) + ("",",if=sd")[self.dist.arch() == 'evbarm-earmv7hf'],
            "-nographic"
            ] + vmm_args + self.extra_vmm_args)
        self.configure_child(child)
        return child

    def xen_disk_arg(self, path, devno = 0, writable = True):
        if self.vmm == 'xm':
            return "disk=file:%s,0x%x,%s" % (path, devno, "rw"[writable])
        else: # xl
            return "disk=file:%s,xvd%s,%s" % (path, chr(ord('a') + devno), "rw"[writable])

    def qemu_disk_args(self, path, devno = 0, writable = True, snapshot = False):
        return ["-drive", "file=%s,format=raw,media=disk,snapshot=%s" % (path, ["off", "on"][snapshot])]

    def qemu_cdrom_args(self, path, devno):
        return ["-drive", "file=%s,format=raw,media=cdrom,readonly=on" % (path)]
    def gxemul_cdrom_args(self):
        return self.dist.iso_path()
    def gxemul_disk_args(self, path):
        return ["-d", path]

    def string_arg(self, name, value):
        if self.vmm == 'xm':
            return '%s=%s' % (name, value)
        else: # xl
            return '%s="%s"' % (name, value)

    def start_xen_domu(self, vmm_args):
        frontend = self.vmm
        name = "anita-%i" % os.getpid()
        args = [
            frontend,
            "create",
            "-c",
            "/dev/null",
            self.xen_disk_arg(os.path.abspath(self.wd0_path()), 0, True),
            "memory=" + str(self.memory_megs()),
            self.string_arg('name', name)
        ] + vmm_args + self.extra_vmm_args

        # Multiple "disk=" arguments are no longer supported with xl;
        # combine them
        if self.vmm == 'xl':
            disk_args = []
            no_disk_args = []
            for arg in args:
                if arg.startswith('disk='):
                    disk_args.append(arg[5:])
                else:
                    no_disk_args.append(arg)
            args = no_disk_args + [ "disk=[%s]" % (','.join(["'%s'" % arg for arg in disk_args]))]

        child = self.pexpect_spawn(args[0], args[1:])
        self.configure_child(child)
        # This is ugly; we reach into the child object and set an
        # additional attribute.  The name of the attribute,
        # "garbage_collector" below, is arbitrary, but must not
        # conflict with any existing attribute of the child
        # object.  Its purpose is only to hold a reference to the
        # DomUKiller object, such that when the child object is
        # destroyed, the destructor of the DomUKiller object
        # is also invoked.
        child.garbage_collector = DomUKiller(frontend, name)
        return child

    def start_noemu(self, vmm_args):
        noemu_always_args = [
            '--workdir', self.workdir,
            '--releasedir', os.path.join(self.workdir, 'download'),
            '--arch', self.dist.arch()
        ]
        child = self.pexpect_spawn('sudo', ['noemu'] +
            noemu_always_args + vmm_args + self.extra_vmm_args)
        self.configure_child(child)
        return child

    def _install(self):
        # Download or build the install ISO
        self.dist.set_workdir(self.workdir)
        if self.dist.arch() == 'evbarm-earmv7hf':
            self.dist.download()
        else:
            self.dist.make_iso()
        arch = self.dist.arch()
        if self.vmm != 'noemu':
            print "Creating hard disk image...",
            sys.stdout.flush()
            make_dense_image(self.wd0_path(), parse_size(self.disk_size))
            print "done."
        if self.dist.arch() == 'evbarm-earmv7hf':
            # Unzip the image
            gzimage_fn = os.path.join(self.workdir,
                'download', self.dist.arch(),
                'binary', 'gzimg', 'armv7.img.gz')
            gzimage = open(gzimage_fn, 'r')
            subprocess.call('gunzip | dd of=' + self.wd0_path() + ' conv=notrunc', shell = True, stdin = gzimage)
            gzimage.close()
            # Unzip the kernel
            gzkernel_fn = os.path.join(self.workdir,
                'download', self.dist.arch(), 'binary', 'kernel',
                'netbsd-VEXPRESS_A15.ub.gz')
            gzkernel = open(gzkernel_fn, 'r')
            kernel_fn = os.path.join(self.workdir, "netbsd-VEXPRESS_A15.ub")
            kernel = open(kernel_fn, 'w')
            subprocess.call('gunzip', stdin = gzkernel, stdout = kernel)
            kernel.close()
            gzkernel.close()
            return

        # The name of the CD-ROM device holding the sets
        cd_device = None

        if vmm_is_xen(self.vmm):
            # Download XEN kernels
            xenkernels = [k for k in [self.dist.xen_kernel(), self.dist.xen_install_kernel()] if k]
            for kernel in xenkernels:
                download_if_missing_3(self.dist.dist_url(),
                        self.dist.download_local_arch_dir(),
                        ["binary", "kernel", kernel],
                        True)

            vmm_args = [
                self.string_arg('kernel', os.path.abspath(os.path.join(self.dist.download_local_arch_dir(),
                    "binary", "kernel", self.dist.xen_install_kernel()))),
                self.xen_disk_arg(os.path.abspath(self.dist.iso_path()), 1, False)
            ]
            child = self.start_xen_domu(vmm_args)
            cd_device = 'xbd1d'
        elif self.vmm == 'qemu':
            # Determine what kind of media to boot from.
            floppy_paths = [ os.path.join(self.dist.floppy_dir(), f) \
                for f in self.dist.floppies() ]
            boot_cd_path = os.path.join(self.dist.boot_iso_dir(), self.dist.boot_isos()[0])
            if self.boot_from is None:
                self.boot_from = self.dist.boot_from_default()
            if self.boot_from is None and len(floppy_paths) == 0:
                self.boot_from = 'cdrom'
            if self.boot_from is None:
                self.boot_from = 'floppy'

            # Set up VM arguments based on the chosen boot media
            if self.boot_from == 'cdrom':
                vmm_args = self.qemu_cdrom_args(boot_cd_path, 1)
                vmm_args += self.qemu_cdrom_args(self.dist.iso_path(), 2)
                vmm_args += ["-boot", "d"]
                cd_device = 'cd1a'
            elif self.boot_from == 'floppy':
                vmm_args = self.qemu_cdrom_args(self.dist.iso_path(), 1)
                if len(floppy_paths) == 0:
                    raise RuntimeError("found no boot floppies")
                vmm_args += ["-drive", "file=%s,format=raw,if=floppy,readonly=on" % floppy_paths[0], "-boot", "a"]
                cd_device = 'cd0a';
            elif self.boot_from == 'cdrom-with-sets':
                # Single CD
                vmm_args = self.qemu_cdrom_args(self.dist.iso_path(), 1)
                vmm_args += ["-boot", "d"]
                cd_device = 'cd0a'

            child = self.start_qemu(vmm_args, snapshot_system_disk = False)
        elif self.vmm == 'noemu':
            child = self.start_noemu(['--boot-from', 'net'])
        elif self.vmm == 'gxemul':
            cd_device = 'cd0a'
            if self.dist.arch() == 'hpcmips':
                cd_device = 'cd0d'
            vmm_args = ["-d", self.gxemul_cdrom_args()]
            if self.dist.arch() == 'pmax':
                vmm_args += [os.path.abspath(os.path.join(self.dist.download_local_arch_dir(),
                 "binary", "kernel", "netbsd-INSTALL.gz"))]
            elif self.dist.arch() == 'hpcmips':
                vmm_args += [os.path.abspath(os.path.join(self.dist.download_local_arch_dir(),
                 "installation", "netbsd.gz"))]
            child = self.start_gxemul(vmm_args)
        else:
            raise RuntimeError('unknown vmm %s' % self.vmm)

        term = None
        if self.dist.arch() == 'hpcmips':
            term = 'vt100'

        # Do the floppy swapping dance and other pre-sysinst interaction
        floppy0_name = None
        while True:
            # NetBSD/i386 will prompt for a terminal type if booted from a
            # CD-ROM, but not when booted from floppies.  Sigh.
            child.expect(
                # Group 1-2
                "(insert disk (\d+), and press return...)|" +
                # Group 3
                "(a: Installation messages in English)|" +
                # Group 4
                "(Terminal type)|" +
                # Group 5
                "(Installation medium to load the additional utilities from: )|"
                # Group 6
                "(1. Install NetBSD)"
                )
            if child.match.group(1):
                # We got the "insert disk" prompt
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
                    # compatibility.  Deal with it.  Also deal with the fact
                    # that as of qemu 0.15, "info block" no longer prints
                    # "type=floppy" for floppy drives.  And in qemu 2.5.0,
                    # the format changed again from "floppy0: " to
                    # "floppy0 (#block544): ", so we no longer match the
                    # colon and space.
                    child.send("info block\n")
                    child.expect(r'\n(fda|floppy0)')
                    floppy0_name = child.match.group(1)
                # Now we can change the floppy
                child.send("change %s %s\n" %
                    (floppy0_name, floppy_paths[floppy_index]))
                # Exit qemu command mode
                child.send("\001c\n")
            elif child.match.group(3):
                # "Installation messages in English"
                break
            elif child.match.group(4):
                # "Terminal type"
                child.send("xterm\n")
                term = "xterm"
                continue
            elif child.match.group(5):
                # "Installation medium to load the additional utilities from"
                # (SPARC)
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
                term = "xterm"
                child.expect("nstall/Upgrade")
                child.send("I\n")
            elif child.match.group(6):
                # "1. Install NetBSD"
                child.send("1\n")

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
        # "found only one disk" followed by "Hit enter to continue",
        # or "On which disk do you want to install".
        child.expect("(Hit enter to continue)|" +
            "(On which disk do you want to install)")
        if child.match.group(1):
            child.send("\n")
        elif child.match.group(2):
            child.send("a\n")
        else:
            raise AssertionError

        def choose_no():
            child.expect("([a-z]): No")
            child.send(child.match.group(1) + "\n")
        def choose_yes():
            child.expect("([a-z]): Yes")
            child.send(child.match.group(1) + "\n")

        # Keep track of sets we have already handled, by label.
        # This is needed so that parsing a pop-up submenu is not
        # confused by earlier output echoing past choices.
        labels_seen = set()

        def choose_sets(set_list):
            sets_this_screen = []
            # First parse the set selection screen or popup; it's messy.
            while True:
                # Match a letter-label pair, like "h: Compiler Tools",
                # followed by an installation status of Yes, No, All,
                # or None.  The label can be separated from the "Yes/No"
                # field either by spaces (at least two, so that there can
                # be single spaces within the label), or by a cursor
                # positioning escape sequence.  In the case of the
                # "X11 fonts" set, we strangely get both a single space
                # and an escape sequence, which seems disoptimal.
                #
                # Alternatively, match the special letter "x: " which
                # is not followed by an installation status.
                child.expect(
                    "(?:([a-z]): ([^ \x1b]+(?: [^ \x1b]+)*)(?:(?:\s\s+)|(?:\s?\x1b\[\d+;\d+H))(Yes|No|All|None))|(x: )")
                (letter, label, yesno, exit) = child.match.groups()
                if exit:
                    if not self.dist.arch() == 'hpcmips':
                        if len(sets_this_screen) != 0:
                            break
                    else:
                        #while installing hpcmips, the option 'm' is repeated (only when run via anita)
                        #It is appended to sets_this_screen only once. So, we need to select exit once
                        #more, otherwise, we'll get stuck.
                        if len(sets_this_screen) >= 0:
                            break
                else:
                    for set in set_list:
                        if re.match(set['label'], label) and label not in labels_seen:
                            sets_this_screen.append({
                                'set': set,
                                'letter': letter,
                                'state': yesno
                            })
                            labels_seen.add(label)

            # Then make the actual selections
            for item in sets_this_screen:
                set = item['set']
                enable = set['install']
                state = item['state']
                group = set.get('group')
                if (enable and state == "No" or \
                       not enable and state == "Yes") \
                       or group:
                    child.send(item['letter'] + "\n")
                if group:
                    # Recurse to handle sub-menu
                    choose_sets(group)

            # Exit the set selection menu
            child.send("x\n")

        # Older NetBSD versions show a prompt like [re0] and ask you
        # to type in the interface name (or enter for the default);
        # newer versions show a menu.

        def choose_interface_oldstyle():
            self.slog('old-style interface list')
            # Choose the first non-fwip interface
            while True:
                child.expect(r"([a-z]+)([0-9]) ")
                ifname = child.match.group(1)
                ifno = child.match.group(2)
                self.slog('old-style interface: <%s,%s>' % (ifname, ifno))
                if ifname != 'fwip':
                    # Found an acceptable interface
                    child.send("%s%s\n" % (ifname, ifno))
                    break

        def choose_interface_newstyle():
            self.slog('new-style interface list')
            child.expect('Available interfaces')
            # Choose the first non-fwip interface
            while True:
                # Make sure to match the digit after the interface
                # name so that we don't accept a partial interface
                # name like "fw" from "fwip0".
                child.expect(r"([a-z]): ([a-z]+)[0-9]")
                if child.match.group(2) != 'fwip':
                    # Found an acceptable interface
                    child.send(child.match.group(1) + "\n")
                    break

        def configure_network():
            child.expect("Network media type")
            child.send("\n")
            child.expect("Perform (DHCP )?autoconfiguration")
            child.expect("([a-z]): No")
            child.send(child.match.group(1) + "\n")

            def choose_a():
                child.send("a\n")
            def choose_dns_server():
                child.expect("([a-z]): other")
                child.send(child.match.group(1) + "\n")
                child.send("10.0.1.1\n")

            expect_any(child,
                r"Your host name", "anita-test\n",
                r"Your DNS domain", "netbsd.org\n",
                r"Your IPv4 (number)|(address)", "10.169.0.2\n",
                r"IPv4 Netmask", "255.255.255.0\n",
                r"IPv4 gateway", "10.169.0.1\n",
                r"IPv4 name server", "10.0.1.1\n",
                r"Perform IPv6 autoconfiguration", choose_no,
                r"Select (IPv6 )?DNS server", choose_dns_server,
                r"Are they OK", choose_yes)
            self.network_configured = True

        self.network_configured = False

        # Many different things can happen at this point:
        #
        # Versions older than 2009/08/23 21:16:17 will display a menu
        # for choosing the extraction verbosity
        #
        # Versions older than 2010/03/30 20:09:25 will display a menu for
        # choosing the CD-ROM device (newer versions will choose automatically)
        #
        # Versions older than Fri Apr 6 23:48:53 2012 UTC will ask
        # you to "Please choose the timezone", wheras newer ones will
        # instead as you to "Configure the additional items".
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
        # OTOH, -current as of 2009.08.23.20.57.40 will issue the message "Hit
        # enter to continue" twice in a row, first as a result of MAKEDEV
        # printing a warning messages "MAKEDEV: dri0: unknown device", and
        # then after "sysinst will give you the opportunity to configure
        # some essential things first".  We match the latter text separately
        # so that the "Hit enter to continue" matches are not consecutive.
        #
        # The changes of Apr 6 2012 broght with them a new redraw problem,
        # which is worked around using the seen_essential_things variable.
        #
        prevmatch = []
        seen_essential_things = 0
        loop = 0
        while True:
            loop = loop + 1
            if loop == 20:
                raise RuntimeError("loop detected")
            child.expect(
                         # Group 1
                         "(a: Progress bar)|" +
                         # Group 2
                         "(a: CD-ROM)|" +
                         # Group 3-4
                         "(([cx]): Continue)|" +
                         # Group 5
                         "(Hit enter to continue)|" +
                         # Group 6
                         "(b: Use serial port com0)|" +
                         # Group 7
                         "(Please choose the timezone)|" +
                         # Group 8
                         "(essential things)|" +
                         # Group 9
                         "(Configure the additional items)|" +
                         # Group 10
                         "(Multiple CDs found)|" +
                         # Group 11
                         "(The following are the http site)|" +
                         # Group 12
                         "(Is the network information you entered accurate)|" +
                         # Group 13-14 (old-style / new-style)
                         "(I have found the following network interfaces)|(Which network device would you like to use)|" +
                         # Group 15
                         "(No allows you to continue anyway)|" +
                         # Group 16
                         r"(Can't connect to)|" +
                         # Group 17
                         "(not-in-use)|" +
                         # Group 18
                         "(not-in-use)|" +
                         # Group 19
                         "(not-in-use)|" +
                         # Group 20-21
                         "(([a-z]): Custom installation)|" +
                         # Group 22
                         "(a: This is the correct geometry)|" +
                         # Group 23
                         "(a: Use one of these disks)|" +
                         # Group 24
                         "(a: Set sizes of NetBSD partitions)|" +
                         # Group 25
                         "(Sysinst could not automatically determine the BIOS geometry of the disk)",
                         10800)

            if child.match.groups() == prevmatch:
                self.slog('ignoring repeat match')
                continue
            prevmatch = child.match.groups()
            if child.match.group(1):
                # (a: Progress bar)
                child.send("\n")
            elif child.match.group(2):
                # (a: CD-ROM)
                if self.vmm == 'noemu':
                    child.send("c\n") # install from HTTP
                    # We next end up at either "Which device shall I"
                    # or "The following are the http site" depending on
                    # the NetBSD version.
                else:
                    child.send("a\n") # install from CD-ROM
            elif child.match.group(3):
                # CDROM device selection
                if cd_device != 'cd0a':
                    child.send("a\n" + cd_device + "\n")
                # (([cx]): Continue)
                # In 3.0.1, you type "c" to continue, whereas in -current,
                # you type "x".  Handle both cases.
                child.send(child.match.group(4) + "\n")
            elif child.match.group(5):
                # (Hit enter to continue)
                if seen_essential_things >= 2:
                    # This must be a redraw
                    pass
                else:
                    child.send("\n")
            elif child.match.group(6):
                # (b: Use serial port com0)
                child.send("bx\n")
            elif child.match.group(7):
                # (Please choose the timezone)
                # "Press 'x' followed by RETURN to quit the timezone selection"
                child.send("x\n")
                # The strange non-deterministic "Hit enter to continue" prompt has
                # also been spotted after executing the sed commands to set the
                # root password cipher, with 2010.10.27.10.42.12 source.
                while True:
                    child.expect("(([a-z]): DES)|(root password)|(Hit enter to continue)")
                    if child.match.group(1):
                        # DES
                        child.send(child.match.group(2) + "\n")
                    elif child.match.group(3):
                        # root password
                        break
                    elif child.match.group(4):
                        # (Hit enter to continue)
                        child.send("\n")
                    else:
                        raise AssertionError
                # Don't set a root password
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
                #
                # We are supposed to get a single "Hit enter to continue"
                # prompt here, but sometimes we get a weird spurious one
                # after running chpass above.

                while True:
                    child.expect("(Hit enter to continue)|(x: Exit)")
                    if child.match.group(1):
                        child.send("\n")
                    elif child.match.group(2):
                        child.send("x\n")
                        break
                    else:
                        raise AssertionError
                break
            elif child.match.group(8):
                # (essential things)
                seen_essential_things += 1
            elif child.match.group(9):
                # (Configure the additional items)
                child.expect("x: Finished configuring")
                child.send("x\n")
                break
            elif child.match.group(10):
                # (Multiple CDs found)
                # This happens if we have a boot CD and a CD with sets;
                # we need to choose the latter.
                child.send("b\n")
            elif child.match.group(11):
                # (The following are the http site)
                # \027 is control-w, which clears the field
                child.send("a\n\02710.169.0.1\n") # IP address
                child.send("b\n\027\n") # Directory = empty string
                if not self.network_configured:
                    child.send("j\n") # Configure network
                    choose_interface_newstyle()
                    configure_network()
                # We get 'Hit enter to continue' if this sysinst
                # version tries ping6 even if we have not configured
                # IPv6
                expect_any(child,
                    r'Hit enter to continue', '\r',
                    r'x: Get Distribution', 'x\n')
                r = child.expect(["Install from", "/usr/bin/ftp"])
                if r == 0:
                    # ...and I'm back at the "Install from" menu?
                    # Probably the same bug reported as install/49440.
                    child.send("c\n") # HTTP
                    # And again...
                    child.expect("The following are the http site")
                    child.expect("x: Get Distribution")
                    child.send("x\n")
                elif r == 1:
                    pass
                else:
                    assert(0)
            elif child.match.group(12):
                # "Is the network information you entered accurate"
                child.expect("([a-z]): Yes")
                child.send(child.match.group(1) + "\n")
            elif child.match.group(13):
                 # "(I have found the following network interfaces)"
                choose_interface_oldstyle()
                configure_network()
            elif child.match.group(14):
                # "(Which network device would you like to use)"
                choose_interface_newstyle()
                configure_network()
            elif child.match.group(15):
                choose_no()
                child.expect("No aborts the install process")
                choose_yes()
            elif child.match.group(16):
                self.slog("network problems detected")
                child.send("\003") # control-c
                def gather_input(seconds):
                    try:
                        child.expect("timeout", seconds)
                    except pexpect.TIMEOUT:
                        pass
                gather_input(666)
                for i in range(60):
                    child.send("ifconfig -a\n")
                    gather_input(1)
                # would run netstat here but it's not on the install media
                gather_input(30)
                sys.exit(1)
            elif child.match.group(20):
                # Custom installation is choice "d" in 6.0,
                # but choice "c" or "b" in older versions
                # We could use "Minimal", but it doesn't exist in
                # older versions.
                child.send(child.match.group(21) + "\n")
                # Enable/disable sets.
                choose_sets(self.dist.sets)
            # On non-Xen i386/amd64 we first get group 22 or 23,
            # then group 24; on sparc and Xen, we just get group 24.
            elif (child.match.group(22) or child.match.group(23)):
                if child.match.group(22):
                    child.send("\n")
                elif child.match.group(23):
                    child.send("a\n")
                    child.expect("Choose disk")
                    child.send("0\n")
                child.expect("b: Use the entire disk")
                child.send("b\n")
                while True:
                    child.expect(r'(Your disk currently has a non-NetBSD partition)|' +
                        r'(Do you want to install the NetBSD bootcode)|' +
                        r'(Do you want to update the bootcode)')
                    if child.match.group(1):
                        # Your disk currently has a non-NetBSD partition
                        child.expect("a: Yes")
                        child.send("\n")
                    elif child.match.group(2) or child.match.group(3):
                        # Install or replace bootcode
                        child.expect("a: Yes")
                        child.send("\n")
                        break
            elif child.match.group(24):
                # (a: Set sizes of NetBSD partitions)
                child.send("a\n")
                child.expect("Accept partition sizes")
                # Press cursor-down enough times to get to the end of the list,
                # to the "Accept partition sizes" entry, then press
                # enter to continue.  Previously, we used control-N ("\016"),
                # but if it gets echoed (which has happened), it is interpreted by
                # the terminal as "enable line drawing character set", leaving the
                # terminal in an unusable state.
                if term in ['xterm', 'vt100']:
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
            elif child.match.group(25):
                #We need to enter these values in cases where sysinst could not
                #determine disk geometry. Currently, this happens for NetBSD/hpcmips
                child.expect("sectors")
                child.send("\n")
                child.expect("heads")
                child.send("\n")
                child.expect("b: Use the entire disk")
                child.send("b\n")
            else:
                raise AssertionError

        # Installation is finished, halt the system.
        # Historically, i386 and amd64, you get a root shell,
        # while sparc just halts.
        # Since Fri Apr 6 23:48:53 2012 UTC, you are kicked
        # back into the main menu.

        while True:
            child.expect("(Hit enter to continue)|(x: Exit Install System)|(#)|(halting machine)|(halted by root)")
            if child.match.group(1):
                child.send("\n")
            elif child.match.group(2):
                # Back in menu
                child.send("x\n")
            elif child.match.group(3):
                # Root shell prompt
                child.send("halt\n")
            else:
                # group 4 or 5: halted
                break

        child.close()
        # Make sure all refs go away
        child = None
        self.child = None
        self.dist.cleanup()

    # Install NetBSD if not installed already

    def install(self):
        # This is needed for Xen and noemu, where we get the kernel
        # from the dist rather than the installed image
        self.dist.set_workdir(self.workdir)
        if self.vmm == 'noemu':
            self.dist.download()
            self._install()
        else:
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
    # installed already).  The vmm_args argument applies when
    # booting, but not when installing.  Does not wait for
    # a login prompt.

    def start_boot(self, vmm_args = None):
        if vmm_args is None:
            vmm_args = []

        if not self.no_install:
            self.install()
            if self.dist.arch() == 'hpcmips':
                vmm_args += [os.path.abspath(os.path.join(self.dist.download_local_arch_dir(),
                 "binary", "kernel", "netbsd-GENERIC.gz"))]

        if self.vmm == 'qemu':
            child = self.start_qemu(vmm_args, snapshot_system_disk = not self.persist)
            # "-net", "nic,model=ne2k_pci", "-net", "user"
        elif vmm_is_xen(self.vmm):
            child = self.start_xen_domu(vmm_args + [self.string_arg('kernel',
                os.path.abspath(os.path.join(self.dist.download_local_arch_dir(),
                             "binary", "kernel", self.dist.xen_kernel())))])
        elif self.vmm == 'noemu':
            child = self.start_noemu(vmm_args + ['--boot-from', 'disk'])
        elif self.vmm == 'gxemul':
            child = self.start_gxemul(vmm_args)
        else:
            raise RuntimeError('unknown vmm %s' % vmm)
        self.child = child
        return child

    # Like start_boot(), but wait for a login prompt.
    def boot(self, vmm_args = None):
        self.start_boot(vmm_args)
        self.child.expect("login:")
        # Can't close child here because we still need it if called from
        # interact()
        return self.child

    # Deprecated
    def interact(self):
        child = self.boot()
        console_interaction(child)

    def run_tests(self, timeout = 10800):
        results_by_net = (self.vmm == 'noemu')

        # Create a scratch disk image for exporting test results from the VM.
        # The results are stored in tar format because that is more portable
        # and easier to manipulate than a file system image, especially if the
        # host is a non-NetBSD system.
        #
        # If we are getting the results back by tftp, this file will
        # be overwritten.
        scratch_disk_path = os.path.join(self.workdir, "tests-results.img")
        if vmm_is_xen(self.vmm):
            scratch_disk = 'xbd1d'
        else:
            scratch_disk = self.dist.scratch_disk()
        mkdir_p(self.workdir)

        scratch_image_megs = 100
        make_dense_image(scratch_disk_path, parse_size('%dM' % scratch_image_megs))
        # Leave a 10% safety margin
        max_result_size_k = scratch_image_megs * 900

        if vmm_is_xen(self.vmm):
            scratch_disk_args = [self.xen_disk_arg(os.path.abspath(scratch_disk_path), 1, True)]
        elif self.vmm == 'qemu':
            scratch_disk_args = self.qemu_disk_args(os.path.abspath(scratch_disk_path), 1, True, False)
        elif self.vmm == 'noemu':
            scratch_disk_args = []
        elif self.vmm == 'gxemul':
            scratch_disk_args = self.gxemul_disk_args(os.path.abspath(scratch_disk_path))
        else:
            raise RuntimeError('unknown vmm')

        child = self.boot(scratch_disk_args)
        self.login()

        if self.tests == "kyua":
            if self.shell_cmd("grep -q 'MKKYUA.*=.*yes' /etc/release") != 0:
                raise RuntimeError("kyua is not installed.")
            test_cmd = (
                "kyua " +
                    "--loglevel=error " +
                    "--logfile=/tmp/tests/kyua-test.log " +
                    "test " +
                    "--store=/tmp/tests/store.db; " +
                "echo $? >/tmp/tests/test.status; " +
                "kyua " +
                    "report " +
                    "--store=/tmp/tests/store.db " +
                    "| tail -n 3; " +
                "kyua " +
                    "--loglevel=error " +
                    "--logfile=/tmp/tests/kyua-report-html.log " +
                    "report-html " +
                    "--store=/tmp/tests/store.db " +
                    "--output=/tmp/tests/html; ")
        elif self.tests == "atf":
            atf_aux_files = ['/usr/share/xsl/atf/tests-results.xsl',
                             '/usr/share/xml/atf/tests-results.dtd',
                             '/usr/share/examples/atf/tests-results.css']
            test_cmd = (
                "{ atf-run; echo $? >/tmp/tests/test.status; } | " +
                "tee /tmp/tests/test.tps | " +
                "atf-report -o ticker:- -o xml:/tmp/tests/test.xml; " +
                "(cd /tmp && for f in %s; do cp $f tests/; done;); " % ' '.join(atf_aux_files))
        else:
            raise RuntimeError('unknown testing framework %s' % self.test)

        exit_status = self.shell_cmd(
            "df -k | sed 's/^/df-pre-test /'; " +
            "mkdir /tmp/tests && " +
            "cd /usr/tests && " +
            test_cmd +
            ("{ cd /tmp && " +
                # Make sure the files will fit on the scratch disk
                "test `du -sk tests | awk '{print $1}'` -lt %d && " % max_result_size_k +
                # To guard against accidentally overwriting the wrong
                # disk image, check that the disk contains nothing
                # but nulls.
                "test `</dev/r%s tr -d '\\000' | wc -c` = 0 && " % scratch_disk +
                # "disklabel -W /dev/rwd1d && " +
                "tar cf /dev/r%s tests; " % scratch_disk +
            "}; " if not results_by_net else \
            "{ cd /tmp && tar cf tests-results.img tests && echo put tests-results.img | tftp 10.169.0.1; };") +
            "df -k | sed 's/^/df-post-test /'; " +
            "ps -glaxw | sed 's/^/ps-post-test /'; " +
            "vmstat -s; " +
            "sh -c 'exit `cat /tmp/tests/test.status`'",
            timeout)

        # We give tar an explicit path to extract to guard against
        # the possibility of an arbitrary file overwrite attack if
        # anita is used to test an untrusted virtual machine.
        tarfile = open(scratch_disk_path, "r")
        subprocess.call(["tar", "xf", "-", "tests"],
                        cwd = self.workdir, stdin = tarfile)

        # For backwards compatibility, point workdir/atf to workdir/tests.
        compat_link = os.path.join(self.workdir, 'atf')
        if not os.path.lexists(compat_link):
            os.symlink('tests', compat_link)

        return exit_status

    # Backwards compatibility
    run_atf_tests = run_tests

    # Log in, if not logged in already
    def login(self):
        if self.is_logged_in:
            return
        login(self.child)
        self.is_logged_in = True

    # Run a shell command
    def shell_cmd(self, cmd, timeout = -1):
        self.login()
        return shell_cmd(self.child, cmd, timeout)

    # Halt the VM
    def halt(self):
        self.login()
        self.child.send("halt\n")
        try:
            # Wait for text confirming the halt, or EOF
            self.child.expect("(The operating system has halted)|(entering state S5)", timeout = 60)
        except pexpect.EOF:
            # Didn't see the text but got an EOF; that's OK.
            print "EOF"
        except pexpect.TIMEOUT, e:
            # This is unexpected but mostly harmless
            print "timeout waiting for halt confirmation:", e

def console_interaction(child):
    # We need this in pexpect 2.x or everything will be printed twice
    child.logfile_read = None
    child.logfile_send = None
    child.interact()

# Calling this directly is deprecated, use Anita.login()

def login(child):
    child.send("\n")
    child.expect("login:")
    child.send("root\n")
    # This used to be "\n# ", but that doesn't work if the machine has
    # a hostname
    child.expect("# ")

def net_setup(child):
    child.send("dhclient ne2\n")
    child.expect("bound to.*\n# ")

# Generate a root shell prompt string that is less likely to appear in
# the console output by accident than the default of "# ".  Must end with "# ".

def gen_shell_prompt():
    return 'anita-root-shell-prompt-%s# ' % str(time.time())

# Quote a prompt in /bin/sh syntax, with some extra quotes
# in the middle so that an echoed command to set the prompt is not
# mistaken for the prompt itself.

def quote_prompt(s):
    midpoint = len(s) / 2
    return "".join("'%s'" % part for part in (s[0:midpoint], s[midpoint:]))

# Calling this directly is deprecated, use Anita.shell_cmd()

def shell_cmd(child, cmd, timeout = -1):
    child.send("exec /bin/sh\n")
    child.expect("# ")
    prompt = gen_shell_prompt()
    child.send("PS1=" + quote_prompt(prompt) + "\n")
    prompt_re = prompt
    child.expect(prompt_re)
    child.send(cmd + "\n")
    # Catch EOF to log the signalstatus, to help debug qemu crashes
    try:
        child.expect(prompt_re, timeout)
    except pexpect.EOF:
        print "pexpect reported EOF - VMM exited unexpectedly"
        child.close()
        print "exitstatus", child.exitstatus
        print "signalstatus", child.signalstatus
        raise
    except:
        raise
    child.send("echo exit_status=$?=\n")
    child.expect("exit_status=(\d+)=")
    r = int(child.match.group(1))
    child.expect(prompt_re, timeout)
    return r

def test(child):
    raise RuntimeError("global test() function is gone, use Anita.run_tests()")

#############################################################################
