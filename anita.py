#
# This is the library part of Anita, the Automated NetBSD Installation
# and Test Application.
#

from __future__ import print_function
from __future__ import division

import os
import pexpect
import re
import string
import subprocess
import sys
import time

if sys.version_info[0] >= 3:
    import urllib.request as good_old_urllib
    import urllib.parse as good_old_urlparse
else:
    import urllib as good_old_urllib
    import urlparse as good_old_urlparse

try:
    from shlex import quote as sh_quote
except ImportError:
    from pipes import quote as sh_quote

__version__='2.0'

# Your preferred NetBSD FTP mirror site.
# This is used only by the obsolete code for getting releases
# by number, not by the recommended method of getting them by URL.
# See http://www.netbsd.org/mirrors/#ftp for the complete list.

netbsd_mirror_url = "ftp://ftp.netbsd.org/pub/NetBSD/"
#netbsd_mirror_url = "ftp://ftp.fi.NetBSD.org/pub/NetBSD/"

# The supported architectures, and their properties.

# If an 'image_name' property is present, installation is done
# using a pre-built image of that name and a kernel from the
# 'kernel_name' list, rather than using sysinst.  If multiple
# kernel names are listed, the first one present in the release
# is used.

arch_props = {
    'i386': {
        'qemu': {
            'executable': 'qemu-system-i386',
        },
        'scratch_disk': 'wd1d',
    },
    'amd64': {
        'qemu': {
            'executable': 'qemu-system-x86_64',
        },
        'scratch_disk': 'wd1d',
        'memory_size': '128M',
    },
    'sparc': {
        'qemu': {
            'executable': 'qemu-system-sparc',
        },
        'scratch_disk': 'sd1c',
    },
    'sparc64': {
        'qemu': {
            'executable': 'qemu-system-sparc64',
        },
        'scratch_disk': 'wd1c',
        'memory_size': '128M',
    },
    'evbarm-earmv7hf': {
        'qemu': {
            'executable': 'qemu-system-arm',
        },
        'image_name': 'armv7.img.gz',
        'kernel_name': ['netbsd-VEXPRESS_A15.ub.gz', 'netbsd-GENERIC.ub.gz'],
        'scratch_disk': None,
        'memory_size': '128M',
        'disk_size': '2G',
    },
    'evbarm-aarch64': {
        'qemu': {
            'executable': 'qemu-system-aarch64',
        },
        'image_name': 'arm64.img.gz',
        'kernel_name': ['netbsd-GENERIC64.img.gz'],
        'reverse_virtio_drives': True,
        'scratch_disk': 'ld5c',
        'memory_size': '512M',
        'disk_size': '2G',
    },
    'pmax': {
        'gxemul': {
        },
        'scratch_disk': 'sd1c',
        'memory_size': '128M',
    },
    'hpcmips': {
        'gxemul': {
        },
        'scratch_disk': None,
    },
    'landisk': {
        'gxemul': {
        },
        'scratch_disk': 'wd1d'
    },
    'vax': {
        'simh': {
        },
        'scratch_disk': None,
    },
    'hppa': {
        'qemu': {
            'executable': 'qemu-system-hppa',
        },
        'scratch_disk': 'sd1c',
    },
     # The following ones don't actually work
    'macppc': {
        'qemu': {
            'executable': 'qemu-system-ppc',
        },
        'scratch_disk': None,
    },
}

set_exts = ['.tgz', '.tar.xz']

# External commands we rely on

if os.uname()[0] == 'NetBSD':
    makefs = ["/usr/sbin/makefs", "-t", "cd9660", "-o", "rockridge"]
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

# Quote a shell command.  This is intended to make it possible to
# manually cut and paste logged command into a shell.

def quote_shell_command(v):
    return " \\\n    ".join([sh_quote(w) for w in v])

# Run a shell command safely and with error checking

def spawn(command, args):
    print(quote_shell_command(args))
    sys.stdout.flush()
    ret = os.spawnvp(os.P_WAIT, command, args)
    if ret != 0:
        raise RuntimeError("could not run " + command)

# Subclass pexpect.spawn to add logging of expect() calls

class pexpect_spawn_log(pexpect.spawn):
    def __init__(self, logf, *args, **kwargs):
        self.structured_log_f = logf
        return super(pexpect_spawn_log, self).__init__(*args, **kwargs)
    def expect(self, pattern, *args, **kwargs):
        slog(self.structured_log_f, "expect", pattern, timestamp = False);
        r = pexpect.spawn.expect(self, pattern, *args, **kwargs)
        slog(self.structured_log_f, "match", self.match.group(0), timestamp = False);
        return r

# Subclass urllib.FancyURLopener so that we can catch
# HTTP 404 errors

class MyURLopener(good_old_urllib.FancyURLopener):
    def http_error_default(self, url, fp, errcode, errmsg, headers):
        raise IOError('HTTP error code %d' % errcode)

def my_urlretrieve(url, filename):
    r = MyURLopener().retrieve(url, filename)
    if sys.version_info >= (2, 7, 12):
        # Work around https://bugs.python.org/issue27973
        good_old_urllib.urlcleanup()
    return r

# Download a file, cleaning up the partial file if the transfer
# fails or is aborted before completion.

def download_file(file, url, optional = False):
    try:
        print("Downloading", url + "...", end=' ')
        sys.stdout.flush()
        my_urlretrieve(url, file)
        print("OK")
        sys.stdout.flush()
    except IOError as e:
        if optional:
            print("missing but optional, so that's OK")
        else:
            print(e)
        sys.stdout.flush()
        if os.path.exists(file):
            os.unlink(file)
        raise

# Create a file of the given size, containing NULs, without holes.

def make_dense_image(fn, size):
    f = open(fn, "wb")
    blocksize = 64 * 1024
    while size > 0:
        chunk = min(size, blocksize)
        f.write(b"\000" * chunk)
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
#
# Returns true iff the file is present.

def download_if_missing_2(url, file, optional = False):
    if os.path.exists(file):
        return True
    if os.path.exists(file + ".MISSING"):
        return False
    dir = os.path.dirname(file)
    mkdir_p(dir)
    try:
        download_file(file, url, optional)
        return True
    except IOError:
        if optional:
            f = open(file + ".MISSING", "w")
            f.close()
            return False
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
        index = "/:+-".find(match.group())
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
    if not arch in arch_props:
        raise RuntimeError(("'%s' is not the name of a " + \
        "supported NetBSD port") % arch)
    if arch in ['i386', 'amd64'] and dist_type != 'reltree':
        raise RuntimeError(("NetBSD/%s must be installed from " +
            "a release tree, not an ISO") % arch)
    if (arch in ['sparc', 'sparc64', 'vax']) and dist_type != 'iso':
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

# Receive and discard (but log) input from the child or a time
# period of "seconds".  This is effectively a delay like
# time.sleep(seconds), but generates more useful log output.

def gather_input(child, seconds):
    try:
        # This regexp will never match
        child.expect("(?!)", seconds)
    except pexpect.TIMEOUT:
        pass

# Reverse the order of sublists of v of length sublist_len
# for which the predicate pred is true.

def reverse_sublists(v, sublist_len, pred):
    # Build a list of indices in v in where a sublist satisfying
    # pred begins
    indices = []
    for i in range(len(v) - (sublist_len - 1)):
        if pred(v[i:i+sublist_len]):
            indices.append(i)
    # Swap list element pairs, working outside in
    for i in range(len(indices) >> 1):
        a = indices[i]
        b = indices[-i - 1]
        def swap(a, b):
            v[a], v[b] = v[b], v[a]
        for j in range(sublist_len):
            swap(a + j, b + j)

# Reverse the order of any "-drive ... -device virtio-blk-device,..."
# option pairs in v

def reverse_virtio_drives(v):
    def is_virtio_blk(sublist):
        return sublist[0] == '-drive' and sublist[2] == '-device' \
            and sublist[3].startswith('virtio-blk-device')
    reverse_sublists(v, 4, is_virtio_blk)

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
    d = dict(list(zip(['filename', 'label', 'install'], t[0:3])))
    if isinstance(t[3], list):
        d['group'] = make_set_dict_list(t[3])
    else:
        d['optional'] = t[3]
    d['label'] = d['label'].encode('ASCII')
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

class Version(object):
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
          # The lack of an "es" after "sourc" is deliberate.
          # The source sets are displayed in a pop-up box atop
          # the main distribution set list, and as of source
          # date 2019.09.12.06.19.47, the "es" in "Share sources"
          # happens to land exactly on top of an existing "es"
          # from the word "Yes" in the underlying window.
          # Curses, eager to to optimize, will reuse that
          # existing "es" instead of outputting it anew, causing
          # the pattern not to match if it includes the "es".
          ['syssrc', 'Kernel sourc', 0, 1],
          ['src', 'Base sourc', 0, 1],
          ['sharesrc', 'Share sourc', 0, 1],
          ['gnusrc', 'GNU sourc', 0, 1],
          ['xsrc', 'X11 sourc', 0, 1],
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
        return arch_props[self.arch()].get('scratch_disk')

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
            try:
                os.unlink(fn)
            except:
                pass

    def set_path(self, setname, ext):
        if re.match(r'.*src$', setname):
            return ['source', 'sets', setname + ext]
        else:
            return [self.arch(), 'binary', 'sets', setname + ext]

    # Download this release
    # The ISO class overrides this to download the ISO only
    def download(self):
        # Optimization of file:// URLs is disabled for now; it doesn't
        # work for the source sets.
        #if hasattr(self, 'url') and self.url[:7] == 'file://':
        #    mkdir_p(os.path.join(self.workdir, 'download'))
        #    if not os.path.lexists(os.path.join(self.workdir, 'download', self.arch())):
        #        os.symlink(self.url[7:], os.path.join(self.workdir, 'download', self.arch()))
        #    return

        # Deal with architectures that we don't know how to install
        # using sysinst, but instead use a pre-installed image
        if 'image_name' in arch_props[self.arch()]:
            download_if_missing_3(self.dist_url(), self.download_local_arch_dir(), ["binary", "gzimg", arch_props[self.arch()]['image_name']])
            for file in arch_props[self.arch()]['kernel_name']:
                if download_if_missing_3(self.dist_url(), self.download_local_arch_dir(), ["binary", "kernel", file], True):
                    break
            # Nothing more to do as we aren't doing a full installation
            return

        if self.arch() == 'hpcmips':
            download_if_missing_3(self.dist_url(), self.download_local_arch_dir(), ["installation", "netbsd.gz"])
        if self.arch() in ['hpcmips', 'landisk']:
            download_if_missing_3(self.dist_url(), self.download_local_arch_dir(), ["binary", "kernel", "netbsd-GENERIC.gz"])
        i = 0
        # Depending on the NetBSD version, there may be two or more
        # boot floppies.  Treat any floppies past the first two as
        # optional files.
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
                present = [
                    download_if_missing_3(self.mi_url(),
                                          self.download_local_mi_dir(),
                                          self.set_path(set['filename'],
                                                        ext),
                                          True)
                    for ext in set_exts
                ]
                if not set['optional'] and not any(present):
                    raise RuntimeError('install set %s does not exist with extension %s' %
                                       (set['filename'], ' nor '.join(set_exts)))

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
# Deprecated, use anita.URL instead

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
# Deprecated, use anita.URL instead

class Release(NumberedVersion):
    def __init__(self, ver, **kwargs):
        NumberedVersion.__init__(self, ver, **kwargs)
        pass
    def mi_url(self):
        return netbsd_mirror_url + "NetBSD-" + self.ver + "/"
    def dist_url(self):
        return self.mi_url() + self.arch() + "/"

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
            good_old_urllib.url2pathname(good_old_urlparse.urlparse(iso_url)[2]))
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

# Virtual constructior that accepts a release URL, ISO, or local path
# and constructs an URL, ISO, or LocalDirectory object as needed.

def distribution(distarg, **kwargs):
    if re.search(r'\.iso$', distarg):
        return ISO(distarg, **kwargs)
    elif re.match(r'/', distarg):
        if not re.search(r'/$', distarg):
            raise RuntimeError("distribution directory should end in a slash")
        return LocalDirectory(distarg, **kwargs)
    elif re.match(r'[a-z0-9\.0-]+:', distarg):
        if not re.search(r'/$', distarg):
            raise RuntimeError("distribution URL should end in a slash")
        return URL(distarg, **kwargs)
    else:
        raise RuntimeError("expected distribution URL or directory, got " + distarg)

#############################################################################

# Helper class for killing the DomU when the last reference to the
# child process is dropped

class DomUKiller(object):
    def __init__(self, frontend, name):
        self.name = name
        self.frontend = frontend
    def __del__(self):
        print("destroying domU", self.name)
        spawn(self.frontend, [self.frontend, "destroy", self.name])

def vmm_is_xen(vmm):
    return vmm == 'xm' or vmm == 'xl'

# Log a message to the structured log file "fd".

def slog(fd, tag, data, timestamp = True):
    if timestamp:
        print("%s(%.3f, %s)" % (tag, time.time(), repr(data)), file=fd)
    else:
        print("%s(%s)" % (tag, repr(data)), file=fd)
    fd.flush()

def slog_info(fd, data):
    slog(fd, 'info', data)

# A file-like object that escapes unprintable data and prefixes each
# line with a tag, for logging I/O.

class Logger(object):
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

class BytesWriter(object):
    def __init__(self, fd):
        self.fd = fd
    def write(self, data):
        self.fd.buffer.write(data)
    def __getattr__(self, name):
        return getattr(self.fd, name)

class Anita(object):
    def __init__(self, dist, workdir = None, vmm = None, vmm_args = None,
        disk_size = None, memory_size = None, persist = False, boot_from = None,
        structured_log = None, structured_log_file = None, no_install = False,
        tests = 'atf', dtb = '', xen_type = 'pv'):
        self.dist = dist
        if workdir:
            self.workdir = workdir
        else:
            self.workdir = dist.default_workdir()

        self.structured_log = structured_log
        self.structured_log_file = structured_log_file

        out = sys.stdout
        null = open("/dev/null", "w")
        if sys.version_info[0] >= 3:
            out = BytesWriter(out)
            null = BytesWriter(null)

        if self.structured_log_file:
            self.structured_log_f = open(self.structured_log_file, "w")
            self.unstructured_log_f = out
        else:
            if self.structured_log:
                self.structured_log_f = sys.stdout
                self.unstructured_log_f = null
            else:
                self.structured_log_f = open("/dev/null", "w")
                self.unstructured_log_f = out

        # Set the default disk size if none was given.
        disk_size = disk_size or \
            arch_props[self.dist.arch()].get('disk_size') or \
            '1536M'
        self.disk_size = disk_size

        # Set the default memory size if none was given.
        memory_size = memory_size or \
            arch_props[self.dist.arch()].get('memory_size') or \
            '32M'
        self.memory_size_bytes = parse_size(memory_size)

        self.persist = persist
        self.boot_from = boot_from
        self.no_install = no_install

        props = arch_props.get(dist.arch())
        if not props:
            raise RuntimeError("NetBSD port '%s' is not supported" %
                dist.arch())

        # Get name of qemu executable (if applicable)
        if 'qemu' in props:
            self.qemu = props['qemu']['executable']
            # Support old versions of qemu where qemu-system-i386 was
            # simply called qemu
            if self.qemu == 'qemu-system-i386' and \
               not try_program(['qemu-system-i386', '--version']) \
               and try_program(['qemu', '--version']): \
                   self.qemu = 'qemu'
        else:
            self.qemu = None

        # Choose a default vmm if none was explicitly requested
        if not vmm:
            if self.qemu:
                vmm = 'qemu'
            elif 'simh' in props:
                vmm = 'simh'
            elif 'gxemul' in props:
                vmm = 'gxemul'
            else:
                raise RuntimeError("%s has no default VMM" % self.dist.arch())

        # Backwards compatibility
        if vmm == 'xen':
            vmm = 'xm'

        self.vmm = vmm
        if vmm_args is None:
            vmm_args = []
        self.extra_vmm_args = vmm_args

        self.dtb = dtb
        self.xen_type = xen_type

        self.is_logged_in = False
        self.halted = False
        self.tests = tests

    # Get the name of the actual uncompressed kernel file, out of
    # potentially multiple alternative kernels.  Used with images.
    def actual_kernel(self):
        for kernel_name in self.get_arch_prop('kernel_name'):
            kernel_name_nogz = kernel_name[:-3]
            kernel_fn = os.path.join(self.workdir, kernel_name_nogz)
            if os.path.exists(kernel_fn):
                return kernel_fn
        raise RuntimeError("missing kernel")

    def arch_vmm_args(self):
        if self.dist.arch() == 'pmax':
            return ["-e3max"]
        elif self.dist.arch() == 'landisk':
            return ["-Elandisk"]
        elif self.dist.arch() == 'hpcmips':
            return ["-emobilepro880"]
        elif self.dist.arch() == 'evbarm-earmv7hf':
            return [
                '-M', 'vexpress-a15',
                '-kernel', self.actual_kernel(),
                '-append', 'root=ld0a',
                '-dtb', self.dtb
            ]
        elif self.dist.arch() == 'evbarm-aarch64':
            return [
                '-M', 'virt',
                '-cpu', 'cortex-a57',
                '-kernel', self.actual_kernel(),
                '-append', 'root=ld4a'
            ]
        return []

    def slog(self, message):
        slog_info(self.structured_log_f, message)

    # Wrapper around pexpect.spawn to let us log the command for
    # debugging.  Note that unlike os.spawnvp, args[0] is not
    # the name of the command.

    def pexpect_spawn(self, command, args):
        print(quote_shell_command([command] + args))
        child = pexpect_spawn_log(self.structured_log_f, command, args)
        print("child pid is %d" % child.pid)
        return child

    # The path to the NetBSD hard disk image
    def wd0_path(self):
        return os.path.join(self.workdir, "wd0.img")

    # Return the memory size rounded up to whole megabytes
    def memory_megs(self):
        megs = (self.memory_size_bytes + 2 ** 20 - 1) // 2 ** 20
        if megs != self.memory_size_bytes // 2 **20:
            print("warning: rounding up memory size of %i bytes to %i megabytes" \
                % (self.memory_size_bytes, megs), file=sys.stderr)
        return megs

    def configure_child(self, child):
        # Log reads from child
        child.logfile_read = multifile([self.unstructured_log_f, Logger('recv', self.structured_log_f)])
        # Log writes to child
        child.logfile_send = Logger('send', self.structured_log_f)
        child.timeout = 3600
        child.setecho(False)
        # Xen installs sometimes fail if we don't increase this
        # from the default of 0.1 seconds.  And powering down noemu
        # using iLO3 over ssh takes more than 5 seconds.
        child.delayafterclose = 30.0
        # Also increase this just in case
        child.delayafterterminate = 30.0
        # pexpect 4.3.1 needs this, too
        ptyproc = getattr(child, 'ptyproc')
        if ptyproc:
            ptyproc.delayafterclose = child.delayafterclose
            ptyproc.delayafterterminate = child.delayafterterminate
        self.child = child

    def start_simh(self, vmm_args = []):
        f = open(os.path.join(self.workdir, 'netbsd.ini'), 'w')
        f.write('set cpu ' + str(self.memory_megs()) + 'm\n' +
                'set rq0 ra92\n' +
                'set rq3 cdrom\n' +
                '\n'.join(vmm_args) + '\n' +
                'attach rq0 ' + self.wd0_path() + '\n' +
                'attach -r rq3 ' + self.dist.iso_path() + '\n' +
                'boot cpu')
        f.close()
        child = self.pexpect_spawn('simh-vax', [os.path.join(self.workdir, 'netbsd.ini')])
        self.configure_child(child)
        return child

    def start_gxemul(self, vmm_args):
        child = self.pexpect_spawn('gxemul', ["-M", str(self.memory_megs()) + 'M',
         "-d", os.path.abspath(self.wd0_path())] + self.extra_vmm_args + self.arch_vmm_args() + vmm_args)
        self.configure_child(child)
        return child

    def start_qemu(self, vmm_args, snapshot_system_disk):
        # Log the qemu version to stdout
        subprocess.call([self.qemu, '--version'])
        try:
            # Identify the exact qemu version in pkgsrc if applicable,
            # ignoring exceptions that may be raised if qemu was not
            # installed from pkgsrc
            qemu_path = subprocess.check_output(['which', self.qemu]).rstrip()
            print("qemu path:", qemu_path)
            sys.stdout.flush()
            qemu_package = subprocess.check_output(['pkg_info', '-Fe', qemu_path]).rstrip()
            print("qemu package:", qemu_package)
            sys.stdout.flush()
            glib2_package = subprocess.check_output(['pkg_info', '-e', 'glib2']).rstrip()
            print("glib2 package:", glib2_package)
            sys.stdout.flush()
        except:
            pass
        qemu_args = [
                "-m", str(self.memory_megs())
            ] + self.qemu_disk_args(self.wd0_path(), 0, True, snapshot_system_disk) + [
                "-nographic"
            ] + vmm_args + self.extra_vmm_args + self.arch_vmm_args()
        # Deal with virtio device ordering issues
        if self.dist.arch() in arch_props and arch_props[self.dist.arch()].get('reverse_virtio_drives'):
            print("reversing virtio devices")
            reverse_virtio_drives(qemu_args)
        else:
            print("not reversing virtio devices")
        # Start the actual qemu child process
        child = self.pexpect_spawn(self.qemu, qemu_args)
        self.configure_child(child)
        return child

    def xen_disk_arg(self, path, devno = 0, cdrom = False):
        writable = not cdrom
        if self.vmm == 'xm':
            dev = "0x%x" % devno
        else: # xl
            if self.xen_type == 'hvm':
                devtype = 'hd'
            else:
                devtype = 'xvd'
            dev = devtype + chr(ord('a') + devno)
        s = "disk=file:%s,%s,%s" % (path, dev, "rw"[writable])
        if cdrom:
            s += ",cdrom"
        return s

    def qemu_disk_args(self, path, devno = 0, writable = True, snapshot = False):
        drive_attrs = [
            ('file', path),
            ('format', 'raw'),
            ('media', 'disk'),
            ('snapshot', ["off", "on"][snapshot])
        ]
        dev_args = []
        if self.dist.arch() == 'evbarm-earmv7hf':
            drive_attrs += [('if', 'sd')]
        elif self.dist.arch() == 'evbarm-aarch64':
            drive_attrs += [('if', 'none'), ('id', 'hd%d' % devno)]
            dev_args += ['-device', 'virtio-blk-device,drive=hd%d' % devno]
        else:
            pass
        def format_attrs(attrs):
            return ','.join(["%s=%s" % pair for pair in attrs])
        return ["-drive", format_attrs(drive_attrs)] + dev_args

    def qemu_cdrom_args(self, path, devno):
        return ["-drive", "file=%s,format=raw,media=cdrom,readonly=on" % (path)]
    def gxemul_cdrom_args(self):
        return ('', 'd:')[self.dist.arch() == 'landisk'] + self.dist.iso_path()
    def gxemul_disk_args(self, path):
        return ["-d", path]

    def xen_string_arg(self, name, value):
        if self.vmm == 'xm':
            return '%s=%s' % (name, value)
        else: # xl
            return '%s="%s"' % (name, value)

    def xen_args(self, install):
        if self.xen_type == 'pv':
            if install:
                k = self.dist.xen_install_kernel()
            else:
                k = self.dist.xen_kernel()
            return [self.xen_string_arg('kernel',
                os.path.abspath(os.path.join(self.dist.download_local_arch_dir(),
                                "binary", "kernel", k)))]
        else:
            return  [
                self.xen_string_arg('type', 'hvm'),
                self.xen_string_arg('serial', 'pty'),
            ]

    def start_xen_domu(self, vmm_args):
        frontend = self.vmm
        name = "anita-%i" % os.getpid()
        args = [
            frontend,
            "create",
            "-c",
            "/dev/null",
            self.xen_disk_arg(os.path.abspath(self.wd0_path()), 0),
            "memory=" + str(self.memory_megs()),
            self.xen_string_arg('name', name)
        ] + vmm_args + self.extra_vmm_args + self.arch_vmm_args()

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
            noemu_always_args + vmm_args + self.extra_vmm_args + self.arch_vmm_args())
        self.configure_child(child)
        return child

    def get_arch_prop(self, key):
        return arch_props[self.dist.arch()].get(key)

    def _install(self):
        # Download or build the install ISO
        self.dist.set_workdir(self.workdir)
        if self.get_arch_prop('image_name'):
            self.dist.download()
        else:
            self.dist.make_iso()
        if self.vmm != 'noemu':
            print("Creating hard disk image...", end=' ')
            sys.stdout.flush()
            make_dense_image(self.wd0_path(), parse_size(self.disk_size))
            print("done.")
            sys.stdout.flush()
        if self.get_arch_prop('image_name'):
            self._install_from_image()
        else:
            self._install_using_sysinst()

    def _install_from_image(self):
        image_name = self.get_arch_prop('image_name')
        # Unzip the image
        gzimage_fn = os.path.join(self.workdir,
            'download', self.dist.arch(),
            'binary', 'gzimg', image_name)
        gzimage = open(gzimage_fn, 'r')
        subprocess.call('gunzip | dd of=' + self.wd0_path() + ' conv=notrunc', shell = True, stdin = gzimage)
        gzimage.close()
        # Unzip the kernel, whatever its name
        for kernel_name in self.get_arch_prop('kernel_name'):
            gzkernel_fn = os.path.join(self.workdir,
                'download', self.dist.arch(), 'binary', 'kernel', kernel_name)
            if not os.path.exists(gzkernel_fn):
                continue
            kernel_name_nogz = kernel_name[:-3]
            gzkernel = open(gzkernel_fn, 'r')
            kernel_fn = os.path.join(self.workdir, kernel_name_nogz)
            kernel = open(kernel_fn, 'w')
            subprocess.call('gunzip', stdin = gzkernel, stdout = kernel)
            kernel.close()
            gzkernel.close()
        # Boot the system to let it resize the image.
        self.start_boot(install = False, snapshot_system_disk = False)
        # The system will resize the image and then reboot.
        # Waith for the login prompt and shut down cleanly.
        self.child.expect("login:")
        self.halt()

    def _install_using_sysinst(self):
        # The name of the CD-ROM device holding the sets
        cd_device = None

        arch = self.dist.arch()

        if vmm_is_xen(self.vmm):
            if self.xen_type == 'pv':
                # Download XEN kernels
                xenkernels = [k for k in [self.dist.xen_kernel(), self.dist.xen_install_kernel()] if k]
                for kernel in xenkernels:
                    download_if_missing_3(self.dist.dist_url(),
                            self.dist.download_local_arch_dir(),
                            ["binary", "kernel", kernel],
                            True)
            vmm_args = []
            vmm_args += self.xen_args(install = True)
            if self.xen_type == 'pv':
                vmm_args += [self.xen_disk_arg(os.path.abspath(self.dist.iso_path()), 1, cdrom = True)]
                cd_device = 'xbd1d'
            else:
                # HVM, similar the qemu boot_from == 'cdrom' case below
                boot_cd_path = os.path.join(self.dist.boot_iso_dir(), self.dist.boot_isos()[0])
                vmm_args += [self.xen_disk_arg(os.path.abspath(boot_cd_path), 1, cdrom = True)]
                vmm_args += [self.xen_disk_arg(os.path.abspath(self.dist.iso_path()), 2, cdrom = True)]
                cd_device = 'cd1a'
            child = self.start_xen_domu(vmm_args)
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
                vmm_args += ["-drive", "file=%s,format=raw,if=floppy,readonly=on"
                             % floppy_paths[0], "-boot", "a"]
                cd_device = 'cd0a';
            elif self.boot_from == 'cdrom-with-sets':
                # Single CD
                if not self.dist.arch() == 'sparc64':
                    vmm_args = self.qemu_cdrom_args(self.dist.iso_path(), 1)
                else:
                    vmm_args = ['-cdrom', self.dist.iso_path()]
                vmm_args += ["-boot", "d"]
                cd_device = 'cd0a'

            child = self.start_qemu(vmm_args, snapshot_system_disk = False)
        elif self.vmm == 'noemu':
            child = self.start_noemu(['--boot-from', 'net'])
        elif self.vmm == 'gxemul':
            cd_device = 'cd0a'
            if self.dist.arch() == 'hpcmips':
                cd_device = 'cd0d'
            elif self.dist.arch() == 'landisk':
                cd_device = 'wd1a'
            vmm_args = ["-d", self.gxemul_cdrom_args()]
            if self.dist.arch() in ['pmax', 'landisk']:
                vmm_args += [os.path.abspath(os.path.join(self.dist.download_local_arch_dir(),
                 "binary", "kernel", "netbsd-INSTALL.gz"))]
            elif self.dist.arch() == 'hpcmips':
                vmm_args += [os.path.abspath(os.path.join(self.dist.download_local_arch_dir(),
                 "installation", "netbsd.gz"))]
            child = self.start_gxemul(vmm_args)
        elif self.vmm == 'simh':
            cd_device = 'cd0a'
            child = self.start_simh()
            child.expect(">>>")
            child.send("boot dua3\r\n")
        else:
            raise RuntimeError('unknown vmm %s' % self.vmm)

        term = None
        if self.dist.arch() in ['hpcmips', 'landisk', 'hppa']:
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
                # Match either the English or the German text.
                # This is a kludge to deal with kernel messages
                # like "ciss0: normal state on 'ciss0:1'" that
                # sometimes appear in the middle of one or the
                # other, but are unlikely to appear in the middle of
                # both.  The installation is done in English no
                # matter which one we happen to match.
                "(Installation messages in English|Installation auf Deutsch)|" +
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
                child.send(b"change " + floppy0_name + b" " +
                           floppy_paths[floppy_index].encode('ASCII') + b"\n")
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

        if self.vmm == 'noemu':
            self.slog("wait for envsys to settle down")
            time.sleep(30)

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
            child.send(child.match.group(1) + b"\n")
        def choose_yes():
            child.expect("([a-z]): Yes")
            child.send(child.match.group(1) + b"\n")

        # Keep track of sets we have already handled, by label.
        # This is needed so that parsing a pop-up submenu is not
        # confused by earlier output echoing past choices.
        labels_seen = set()

        def choose_sets(set_list, level = 0):
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
                    "(?:([a-z]): ([^ \x1b]+(?: [^ \x1b]+)*)(?:(?:\s\s+)|(?:\s?\x1b\[\d+;\d+H\x00*))(Yes|No|All|None))|(x: )")
                (letter, label, yesno, exit) = child.match.groups()
                if exit:
                    if len(sets_this_screen) != 0:
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
                if (enable and state == b"No" or \
                       not enable and state == b"Yes") \
                       or group:
                    child.send(item['letter'] + b"\n")
                if group:
                    # Recurse to handle sub-menu
                    choose_sets(group, level + 1)

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
                self.slog('old-style interface: <%s,%s>' % (repr(ifname), repr(ifno)))
                if ifname != 'fwip':
                    # Found an acceptable interface
                    child.send(ifname + ifno + b"\n")
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
                    child.send(child.match.group(1) + b"\n")
                    break

        def configure_network():
            child.expect("Network media type")
            child.send("\n")
            child.expect("Perform (DHCP )?autoconfiguration")
            child.expect("([a-z]): No")
            child.send(child.match.group(1) + b"\n")

            def choose_a():
                child.send("a\n")
            def choose_dns_server():
                child.expect("([a-z]): other")
                child.send(child.match.group(1) + b"\n")
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

        def choose_install_media():
            # Noemu installs from HTTP, otherwise we use the CD-ROM
            media = ['CD-ROM', 'HTTP'][self.vmm == 'noemu']
            child.expect('([a-h]): ' + media)
            child.send(child.match.group(1) + b"\n")

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
            if loop == 40:
                raise RuntimeError("loop detected")
            child.expect(
                         # Group 1
                         r"(a: Progress bar)|" +
                         # Group 2
                         r"(Select medium|Install from)|" +
                         # Group 3-4
                         r"(([cx]): Continue)|" +
                         # Group 5
                         r"(Hit enter to continue)|" +
                         # Group 6
                         r"(b: Use serial port com0)|" +
                         # Group 7
                         r"(Please choose the timezone)|" +
                         # Group 8
                         r"(essential things)|" +
                         # Group 9
                         r"(Configure the additional items)|" +
                         # Group 10
                         r"(Multiple CDs found)|" +
                         # Group 11
                         r"(The following are the http site)|" +
                         # Group 12
                         r"(Is the network information you entered accurate)|" +
                         # Group 13-14 (old-style / new-style)
                         r"(I have found the following network interfaces)|(Which network device would you like to use)|" +
                         # Group 15
                         r"(No allows you to continue anyway)|" +
                         # Group 16
                         r"(Can't connect to)|" +
                         # Group 17
                         r"(/sbin/newfs)|" +
                         # Group 18
                         r"(Do you want to install the NetBSD bootcode)|" +
                         # Group 19
                         r"(Do you want to update the bootcode in the Master Boot Record to the latest)|" +
                         # Group 20-21
                         r"(([a-z]): Custom installation)|" +
                         # Group 22
                         r"(a: This is the correct geometry)|" +
                         # Group 23
                         r"(a: Use one of these disks)|" +
                         # Group 24-25
                         r"(([a-z]): Set sizes of NetBSD partitions)|" +
                         # Group 26
                         r"(a partitioning scheme)|" +
                         # Group 27-28
                         r"(([a-z]): Use the entire disk)|" +
                         # Group 29
                         r'(Do you want to install the NetBSD bootcode)|' +
                         # Group 30
                         r'(Do you want to update the bootcode)|' +
                         # Group 31
                         r"(Please enter a name for your NetBSD disk)|" +
                         # Group 32
                         # Matching "This is your last chance" will not work
                         r"(ready to install NetBSD on your hard disk)|" +
                         # Group 33
                         r"(We now have your (?:BSD.|GPT.)?(?:disklabel )?partitions)|" +
                         # Group 34 (formerly 28)
                         r'(Your disk currently has a non-NetBSD partition)|' +
                         # Group 35 (formerly 25)
                         r"(Sysinst could not automatically determine the BIOS geometry of the disk)|" +
                         # Group 36
                         r"(Do you want to re-edit the disklabel partitions)",
                         10800)

            if child.match.groups() == prevmatch:
                self.slog('ignoring repeat match')
                continue
            prevmatch = child.match.groups()
            if child.match.group(1):
                # (a: Progress bar)
                child.send("\n")
            elif child.match.group(2):
                # (Install from)
                choose_install_media()
            elif child.match.group(3):
                # CDROM device selection
                if cd_device != 'cd0a':
                    child.send(b"a\n" + cd_device.encode('ASCII') + b"\n")
                # (([cx]): Continue)
                # In 3.0.1, you type "c" to continue, whereas in -current,
                # you type "x".  Handle both cases.
                child.send(child.match.group(4) + b"\n")
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
                        child.send(child.match.group(2) + b"\n")
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
                gather_input(child, 1)
                # (The following are the http site)
                # \027 is control-w, which clears the field
                child.send("a\n") # IP address
                child.send("\02710.169.0.1\n")
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
                    choose_install_media()
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
                child.send(child.match.group(1) + b"\n")
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
                gather_input(child, 666)
                for i in range(60):
                    child.send("ifconfig -a\n")
                    gather_input(child, 1)
                # would run netstat here but it's not on the install media
                gather_input(child, 30)
                sys.exit(1)
            elif child.match.group(17):
                self.slog("matched newfs to defeat repeat match detection")
            elif child.match.group(18):
                # "Do you want to install the NetBSD bootcode"
                choose_yes()
            elif child.match.group(19):
                # "Do you want to update the bootcode in the Master Boot Record to the latest"
                choose_yes()
            elif child.match.group(20):
                # Custom installation is choice "d" in 6.0,
                # but choice "c" or "b" in older versions
                # We could use "Minimal", but it doesn't exist in
                # older versions.
                child.send(child.match.group(21) + b"\n")
                # Enable/disable sets.
                choose_sets(self.dist.sets)
            # On non-Xen i386/amd64 we first get group 22 or 23,
            # then group 24; on sparc and Xen, we just get group 24.
            elif child.match.group(22):
                # "This is the correct geometry"
                child.send("\n")
            elif child.match.group(23):
                # "a: Use one of these disks"
                child.send("a\n")
                child.expect("Choose disk")
                child.send("0\n")
            elif child.match.group(24):
                # "(([a-z]): Set sizes of NetBSD partitions)"
                child.send(child.match.group(25) + b"\n")
                # In 2.1, no letter label like "x: " is printed before
                # "Accept partition sizes", hence the kludge of sending
                # multiple cursor-down sequences.
                child.expect(r"(Accept partition sizes)|(Go on)")
                #child.send(child.match.group(1) + "\n")
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
                    cursor_down = b"\033OB"
                else:
                    # Use the default ANSI cursor-down escape sequence
                    cursor_down = b"\033[B"
                child.send(cursor_down * 8 + b"\n")
            elif child.match.group(26):
                # "a partitioning scheme"
                #child.expect("([a-z]): Master Boot Record")
                #child.send(child.match.group(1) + "\n")
                # Sparc asks the question but does not have MBR as an option,
                # only disklabel.  Just use the first choice, whatever that is.
                child.send("a\n")
            elif child.match.group(27):
                # "([a-z]): use the entire disk"
                child.send(child.match.group(28) + b"\n")
            elif child.match.group(29) or child.match.group(30):
                # Install or replace bootcode
                child.expect("a: Yes")
                child.send("\n")
            elif child.match.group(31):
                # "Please enter a name for your NetBSD disk"
                child.send("\n")
            elif child.match.group(32):
                # "ready to install NetBSD on your hard disk"
                child.expect("Shall we continue")
                child.expect("b: Yes")
                child.send("b\n")
                # newfs is run at this point
            elif child.match.group(33):
                # "We now have your BSD disklabel partitions"
                child.expect("x: Partition sizes ok")
                child.send("x\n")
            elif child.match.group(34):
                # Your disk currently has a non-NetBSD partition
                child.expect("a: Yes")
                child.send("\n")
            elif child.match.group(35):
                # We need to enter these values in cases where sysinst could not
                # determine disk geometry. Currently, this happens for NetBSD/hpcmips
                child.expect("sectors")
                child.send("\n")
                child.expect("heads")
                child.send("\n")
            elif child.match.group(36):
                raise RuntimeError('setting up partitions did not work first time')
            else:
                raise AssertionError

        # Installation is finished, halt the system.
        # Historically, i386 and amd64, you get a root shell,
        # while sparc just halts.
        # Since Fri Apr 6 23:48:53 2012 UTC, you are kicked
        # back into the main menu.

        x_sent = False
        while True:
            child.expect("(Hit enter to continue)|(x: Exit Install System)|(#)|(halting machine)|(halted by root)")
            if child.match.group(1):
                child.send("\n")
            elif child.match.group(2):
                # Back in menu
                # Menu may get redrawn, so only send this once
                if not x_sent:
                    child.send("x\n")
                    x_sent = True
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

    def start_boot(self, vmm_args = None, install = None, snapshot_system_disk = None):
        if vmm_args is None:
            vmm_args = []
        if install is None:
            install = not self.no_install
        if snapshot_system_disk is None:
            snapshot_system_disk = not self.persist

        if install:
            self.install()

        if self.dist.arch() in ['hpcmips', 'landisk']:
            vmm_args += [os.path.abspath(os.path.join(self.dist.download_local_arch_dir(),
                 "binary", "kernel", "netbsd-GENERIC.gz"))]

        if self.vmm == 'qemu':
            child = self.start_qemu(vmm_args, snapshot_system_disk = snapshot_system_disk)
            # "-net", "nic,model=ne2k_pci", "-net", "user"
        elif vmm_is_xen(self.vmm):
            vmm_args += self.xen_args(install = False)
            child = self.start_xen_domu(vmm_args)
        elif self.vmm == 'noemu':
            child = self.start_noemu(vmm_args + ['--boot-from', 'disk'])
        elif self.vmm == 'gxemul':
            child = self.start_gxemul(vmm_args)
        elif self.vmm == 'simh':
            child = self.start_simh(vmm_args)
            child.expect(">>>")
            child.send("boot dua0\r\n")
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
        self.boot()
        self.console_interaction()

    # Interact with the console of a system that has already been booted
    def console_interaction(self):
        # With pexpect 2.x and newer, we need to disable logging to stdout
        # of data read from the slave, or otherwise everything will be
        # printed twice.  We can still log to the structured log, though.
        self.child.logfile_read = Logger('recv', self.structured_log_f)
        self.slog('entering console interaction')
        self.child.interact()

    # Run the NetBSD ATF test suite on the guest
    def run_tests(self, timeout = 86400):
        mkdir_p(self.workdir)
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

        scratch_disk_args = []
        if scratch_disk:
            scratch_image_megs = 100
            make_dense_image(scratch_disk_path, parse_size('%dM' % scratch_image_megs))
            # Leave a 10% safety margin
            max_result_size_k = scratch_image_megs * 900

            if vmm_is_xen(self.vmm):
                scratch_disk_args = [self.xen_disk_arg(os.path.abspath(scratch_disk_path), 1)]
            elif self.vmm == 'qemu':
                scratch_disk_args = self.qemu_disk_args(os.path.abspath(scratch_disk_path), 1, True, False)
            elif self.vmm == 'noemu':
                pass
            elif self.vmm == 'gxemul':
                scratch_disk_args = self.gxemul_disk_args(os.path.abspath(scratch_disk_path))
            elif self.vmm == 'simh':
                scratch_disk_args = ['set rq1 ra92', 'attach rq1 ' + scratch_disk_path]
            else:
                raise RuntimeError('unknown vmm')

        child = self.boot(scratch_disk_args)
        self.login()

        # Build a shell command to run the tests
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

        # Build a shell command to save the test results
        if results_by_net:
            save_test_results_cmd = (
                "{ cd /tmp && " +
                "tar cf tests-results.img tests && " +
                "(echo blksize 8192; echo put tests-results.img) | tftp 10.169.0.1; }; "
            )
        elif scratch_disk:
            save_test_results_cmd = (
            "{ cd /tmp && " +
                # Make sure the files will fit on the scratch disk
                "test `du -sk tests | awk '{print $1}'` -lt %d && " % max_result_size_k +
                # To guard against accidentally overwriting the wrong
                # disk image, check that the disk contains nothing
                # but nulls.
                "test `</dev/r%s tr -d '\\000' | wc -c` = 0 && " % scratch_disk +
                # "disklabel -W /dev/rwd1d && " +
                "tar cf /dev/r%s tests; " % scratch_disk +
            "}; "
            )
        else:
            save_test_results_cmd = ""

        exit_status = self.shell_cmd(
            "df -k | sed 's/^/df-pre-test /'; " +
            "mkdir /tmp/tests && " +
            "cd /usr/tests && " +
            test_cmd +
            save_test_results_cmd +
            "df -k | sed 's/^/df-post-test /'; " +
            "ps -glaxww | sed 's/^/ps-post-test /'; " +
            "vmstat -s; " +
            "sh -c 'exit `cat /tmp/tests/test.status`'",
            timeout)

        # Halt the VM before reading the scratch disk, to
        # ensure that it has been flushed.  This matters
        # when using gxemul.
        self.halt()

        if scratch_disk:
            # Extract the ATF results from the scratch disk.
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

    # Run a shell command and return its exit status
    def shell_cmd(self, cmd, timeout = -1):
        self.login()
        return shell_cmd(self.child, cmd, timeout)

    # Halt the VM
    def halt(self):
        if self.halted:
            return
        self.login()
        self.child.send("halt\n")
        try:
            # Wait for text confirming the halt, or EOF
            self.child.expect([r'The operating system has halted',
                               r'entering state S5',
                               r'> ', # sparc64 firmware prompt
                               r'System halted!' # hppa
                              ], timeout = 60)
        except pexpect.EOF:
            # Didn't see the text but got an EOF; that's OK.
            print("EOF")
        except pexpect.TIMEOUT as e:
            # This is unexpected but mostly harmless
            print("timeout waiting for halt confirmation:", e)
        self.halted = True

# Calling this directly is deprecated, use Anita.login()

def login(child):
    # Send a newline character to get another login prompt, since boot() consumed one.
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
    midpoint = len(s) // 2
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
        print("pexpect reported EOF - VMM exited unexpectedly")
        child.close()
        print("exitstatus", child.exitstatus)
        print("signalstatus", child.signalstatus)
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
