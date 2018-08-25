#!/bin/python3

### sparsebak
### Christopher Laprise / tasket@github.com



import re
import os
import time
import mmap
import subprocess
import xml.etree.ElementTree
from optparse import OptionParser
#import qubesadmin.tools

bkset = "set01"
setdir = "/baktest/"+bkset
vgname = "qubes_dom0"
poolname = "pool00"

volfile = "/tmp/sparsebak-volumes.txt"
deltafile = "/tmp/sparsebak-delta."
dtree = None
dblocksize = None
allvols = {}
bkdir = setdir+"/"+vgname+"%"+poolname
bksession = time.strftime("S_%Y%m%d-%H%M%S")
bs = 512
#bkchunksize = 1024 * 512 # 512k
bkchunksize = 1024 * 256 # 256k
#bkchunksize = 256 * bs # 128k same as thin_delta chunk


usage = "usage: %prog [options] path-to-backup-set"
parser = OptionParser(usage)
parser.add_option("-f", "--full", action="store_true", dest="full", default=False,
                  help="Perform initial full backup when necessary")
parser.add_option("-s", "--send", action="store_true", dest="send", default=False,
                help="Perform backup and send to destination")
parser.add_option("-u", "--unattended", action="store_true", dest="unattended", default=False,
                help="Non-interactive, supress prompts")
(options, args) = parser.parse_args()

monitor_only = not options.send # gather metadata without backing up if True


## TICK - process metadata and compile delta info
def prepare_snapshots():

    # Normal precondition will have a snap1vol already in existence in addition
    # to the source datavol. Here we create a fresh snap2vol so we can compare
    # it to the older snap1vol. Then, depending on monitor or backup mode, we'll
    # accumulate delta info and possibly use snap2vol as source for a
    # backup session.

    print("Preparing snapshots...")

    for datavol in datavols:
        snap1vol = datavol + ".tick"
        snap2vol = datavol + ".tock"
        try:
            p = subprocess.check_output( ["lvs", vgname+"/"+datavol],
                                        stderr=subprocess.STDOUT )
        except:
            # FIX: Remove non-existent volume from list...........
            print("ERROR:", datavol, "does not exist!")
            exit(1) #fix

        # Make initial snapshot if necessary: ##FIX - this also means creating a new set!
        try:
            p = subprocess.check_output( ["lvs", vgname+"/"+snap1vol],
                                        stderr=subprocess.STDOUT)
        except:
            p = subprocess.check_output(["lvcreate", "-pr", "-kn", "-ay", "-s",
                vgname+"/"+datavol, "-n", snap1vol], stderr=subprocess.STDOUT)
            print("Initial snapshot created:", snap1vol)

        # Check for stale snap2vol
        try:
            p = subprocess.check_output( ["lvs", vgname+"/"+snap2vol],
                                        stderr=subprocess.STDOUT)
        except:
            pass
        else:
            p = subprocess.check_output(["lvremove", "-f",vgname+"/"+snap2vol],
                                        stderr=subprocess.STDOUT)
            print("Stale snapshot removed.")
            # also cleanup other data from aborted backup...

        # Make current snapshot
        p = subprocess.check_output( ["lvcreate", "-pr", "-kn", "-ay", \
            "-s", vgname+"/"+datavol, "-n",snap2vol], stderr=subprocess.STDOUT)
        print("Tracking snapshot created:", snap2vol)


# Load lvm metadata
def get_lvm_metadata():
    print("Scanning volume metadata...")
    p = subprocess.check_output( ["vgcfgbackup", "--reportformat", "json", \
        "-f", volfile ], stderr=subprocess.STDOUT )
    with open(volfile) as f:
        lines = f.readlines()
    scope = 0
    volume = ""
    version = False
    for l in lines:
        if l.strip() == "version = 1":
            version = True
            break
    if not version:
        raise ValueError("Incorrect format from 'vgcfgbackup'!")

    # Parse all volumes and their thinlv ids
    for l in lines:
        refind = re.sub("\s([0-9A-Za-z\-\+\.]+) {\n", r'\1', l)
        scope += l.count('{')
        scope -= l.count('}')
        if scope == 3 and not refind == l:
            volume = refind.strip()
        elif scope == 4 and not volume == "" and "device_id =" in l:
## Also pull transaction_id and compare datavol vs snap1 freshness b4 analyzing ##
            allvols[volume] = re.sub("device_id = ([0-9]+)", r'\1', l).strip()
            volume = ""
        elif scope == 0 and '}' in l:
            break

def get_lvm_sizes():
    line = subprocess.check_output( ["lvdisplay --units=b " \
        + " /dev/mapper/"+vgname+"-"+snap1vol.replace("-","--") \
        +  "| grep 'LV Size'"], shell=True).decode("UTF-8").strip()
    snap1size = int(re.sub("^.+ ([0-9]+) B", r'\1', line))
    line = subprocess.check_output( ["lvdisplay --units=b " \
        + " /dev/mapper/"+vgname+"-"+snap2vol.replace("-","--") \
        +  "| grep 'LV Size'"], shell=True).decode("UTF-8").strip()
    snap2size = int(re.sub("^.+ ([0-9]+) B", r'\1', line))
    return snap1size, snap2size


# Get delta between snapshots
def get_lvm_deltas():
    print("Acquiring LVM delta info...")
    subprocess.check_call( ["dmsetup", "message", vgname+"-"+poolname+"-tpool", \
        "0", "reserve_metadata_snap"] )
    td_err = False
    for datavol in datavols:
        snap1vol = datavol + ".tick"
        snap2vol = datavol + ".tock"
        try:
            with open(deltafile+datavol, "w") as f:
                cmd = ["thin_delta -m" \
                    + " --thin1 " + allvols[snap1vol] \
                    + " --thin2 " + allvols[snap2vol] \
                    + " /dev/mapper/"+vgname+"-"+poolname+"_tmeta" \
                    + " | grep -v '<same .*\/>$'" ]
                #print(cmd[0])
                subprocess.check_call(aaa, shell=True, stdout=f)
        except:
            td_err = True
    subprocess.check_call(["dmsetup","message", vgname+"-"+poolname+"-tpool", \
        "0", "release_metadata_snap"] )
    if td_err:
        print("ERROR running thin_delta process!")
        exit(1)


def update_delta_digest():
    print("Updating block change map...")
    dtree = xml.etree.ElementTree.parse(deltafile+datavol).getroot()
    dblocksize = int(dtree.get("data_block_size"))
    bmap_byte = 0
    lastindex = 0
    dnewblocks = 0
    dfreedblocks = 0

    dest = bkdir+"/"+datavol+"_deltamap.dat"
    #bmap_size = int(snap2size / bkchunksize / 8) + 1
    if not os.access(dest, os.F_OK):
        print("Volume", datavol, "not initialized; Skipping map update.")
        return False
    os.rename(dest, dest+"-tmp")

    with open(dest+"-tmp", "r+b") as bmapf:
        os.ftruncate(bmapf.fileno(), bmap_size)
        bmap_mm = mmap.mmap(bmapf.fileno(), 0)

        for delta in dtree.find("diff"):
            #for i in dtree.find("diff").findall("right_only"):
            #if delta.tag == "same":
            #    continue
            #elif delta.tag in ["different", "left_only", "right_only"]:

            blockbegin = int(delta.get("begin")) * dblocksize
            blocklen   = int(delta.get("length")) * dblocksize
            if delta.tag in ["different", "right_only"]:
                dnewblocks += blocklen
            elif delta.tag == "left_only":
                dfreedblocks += blocklen

            seg = 0
            for blockpos in range(blockbegin, blockbegin + blocklen):
                volsegment = int(blockpos / (bkchunksize / bs))
                bmap_pos = int(volsegment / 8)
                if bmap_pos != lastindex: ##REVIEW
#                    print("WRITE:")
                    bmap_mm[lastindex] |= bmap_byte
                    bmap_byte = 0
                bmap_byte |= 2** (volsegment % 8)
                lastindex = bmap_pos
#                print(delta.tag, hex(blockpos*bs), volsegment, bmap_pos, bmap_byte, \
#                    "JUMP" if seg > 0 and seg != volsegment else "")
                seg = volsegment
#        print("WRITE:")
        bmap_mm[lastindex] |= bmap_byte
    os.rename(dest+"-tmp", dest)
    print("Data changes:", dnewblocks * bs, "bytes")
    print("Deallocated :", dfreedblocks * bs, "bytes")
    return True


def rotate_snapshots():
    print("Rotating snapshots for", datavol)
    ##FIX - Make this atomic:
    p = subprocess.check_output( ["lvremove", "--force", vgname+"/"+snap1vol ])
    p = subprocess.check_output( ["lvrename", vgname+"/"+snap2vol, snap1vol ])


## TOCK - Run backup session

def record_to_bkdir(send_all = False):
    # Refactor for realistic 'send' use cases
    # Add a stat file for each vol/session showing vol size and previous session
    bmfile = bkdir+"/"+datavol+"_deltamap.dat"
    if not send_all and not mapped:
        print("Volume", datavol, "not initialized; Skipping backup.")
        return False
        
    destdir=bkdir+"/"+datavol+"/"+bksession
    print("Backing up to", destdir)
    os.makedirs(destdir+"-tmp")
    zeros = bytes(bkchunksize)
    bcount = 0

    with open("/dev/mapper/"+vgname+"-"+snap2vol.replace("-","--"), "rb") as vf:
        with open("/dev/zero" if send_all else bmfile, "r+b") as bmapf:
            bmap_mm = bytes(1) if send_all else mmap.mmap(bmapf.fileno(), 0)
            for addr in range(0, snap2size, bkchunksize):
                bmap_pos = int(addr / bkchunksize / 8)
                b = int((addr / bkchunksize) % 8)
                print(bmap_pos, b, hex(addr), end=" ")
                if send_all or bmap_mm[bmap_pos] & (2** b):
                    ## REVIEW int math vs large vol sizes . . .
                    vf.seek(addr)
                    buf = vf.read(bkchunksize)
                    with open(destdir+"-tmp/" \
                         + format(addr,"016x"), "wb") as segf:
                        if buf != zeros: # write only non-empty
                            segf.write(buf)
                            bcount += len(buf)
                            print("DATA", end="")
                print("     ", end="\x0d")
    os.rename(destdir+"-tmp", destdir)
    print("Bytes sent:", bcount)
    return True


def finalize_monitor_session():
    rotate_snapshots()


def finalize_bk_session():
    init_deltamap(bkdir+"/"+datavol+"_deltamap.dat")
    rotate_snapshots()


def get_configs():
    with open(setdir+"/sparsebak.conf", "r") as f:
        datavols = f.read().splitlines()
    return datavols


def init_deltamap(bmfile):
    try:
        os.remove(bmfile)
    except:
        pass
    with open(bmfile, "wb") as bmapf:
        os.ftruncate(bmapf.fileno(), bmap_size)



## Main ###############################################
# ToDo: Check root user, thinp commands, etc.
# Detect/make process lock
# Check dir/file presence, volume sizes, deltabmap size
# Check for modulus bkchunksize/(bs * dblocksize) == 0
# Make separate /var (local) and dest (remote) directories

print("\nStarting", ["backup","monitor-only"][int(monitor_only)],"session:\n")
if not os.access(bkdir, os.F_OK):
    os.makedirs(bkdir)

datavols = get_configs()
prepare_snapshots()
get_lvm_metadata()
get_lvm_deltas()

for datavol in datavols:
    print("\n** Starting", datavol)
    snap1vol = datavol + ".tick"
    snap2vol = datavol + ".tock"
    snap1size, snap2size = get_lvm_sizes()
    bmap_size = int(snap2size / bkchunksize / 8) + 1

    mapped = update_delta_digest()

    if not monitor_only:
        if record_to_bkdir(send_all = not mapped and options.full):
            finalize_bk_session()
    else:
        finalize_monitor_session()

print("\nDone.\n")
