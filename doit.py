#!/usr/pkg/bin/python

import pexpect
import sys
import os
import time
import re

def send_slowly(child, str):
    for char in str:
        child.send(char)
        child.expect(char)

def run_netbsd(iso, boot1, boot2, hd):

    os.system("qemu-img create %s 1500M" % hd)

    child = pexpect.spawn("ktrace -f qemu.kt qemu -m 32 -hda %s -fda %s -cdrom %s -boot a -serial stdio -nographic" % (hd, boot1, iso))

    child.log_file = sys.stdout
    child.timeout = 3600

    child.expect("insert disk 2, and press return...")
    # Escape into qemu command mode to switch floppies
    child.send("\001c")
    child.expect('\(qemu\)')
    send_slowly(child, "change fda %s" % boot2)
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

# 3.0.1
run_netbsd("i386cd-3.0.1.iso", "boot-com1.fs", "boot2.fs", "hd-3.0.1")

# current
#dist="/usr/build/136/release/i386/installation"
#run_netbsd(dist + "/cdrom/netbsd-i386.iso", dist + "/floppy/boot-com1.fs", dist + "/floppy/boot2.fs", "hd-current")


