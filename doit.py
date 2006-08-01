#!/usr/bin/python

import pexpect
import sys
import os

dist="/usr/build/136/release/i386/installation"

os.system("qemu-img create hd 512M");

# ktrace -f qemu.kt 
child = pexpect.spawn("qemu -m 32 -hda hd -fda %s/floppy/boot-com1.fs -cdrom %s/cdrom/netbsd-i386.iso -boot a -serial stdio -nographic" % (dist, dist))
#child.setecho(True)
child.log_file = sys.stdout

child.expect("insert disk 2, and press return...")
child.send("\001c")
child.expect("(qemu)")
child.send("change fda %s/floppy/boot2.fs\n" % dist)
child.expect("(qemu)")
child.send("\001c\n")
# set timeout -1
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
#child.#expec( "a: Set sizes of NetBSD partitions")
# XXX if you select "b: Use existing partition sizes" here, things go wrong
child.send("\n")
child.expect("Accept partition sizes")
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
# Here, sysinst runs /bin/cp /usr/mdec/boot /targetroot/boot
#child.#expec( "Hit enter to continue")
#child.#sen( "\n")
child.expect("a: Progress bar")
child.send("\n")
child.expect("a: CD-ROM")
child.send("\n")
child.expect("x: Continue")
child.send("x\n")
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

# interact

