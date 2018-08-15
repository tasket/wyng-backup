#!/bin/python3

### sparsebak
### Christopher Laprise / tasket@github.com



import re
import os
import time
import mmap
import subprocess
import xml.etree.ElementTree

datavol = "vm-untrusted-private"
snap1vol = datavol + "-tick"
snap2vol = datavol + "-tock"
#datavol = "test"
#snap1vol = "test1"
#snap2vol = "test3"
snap1size = None
snap2size = None
allvols = {}
vgname = "qubes_dom0"
poolname = "pool00"
volfile = "/tmp/sparsebak-volumes.txt"
deltafile = "/tmp/sparsebak-delta.xml"
dtree = None
dblocksize = None
bkset = "set01"
bkdir = "/baktest/"+bkset+"/"+vgname+"%"+poolname
bksession = datavol+time.strftime("-%Y%m%d-%H%M%S")
bkchunksize = 1024 * 1024 * 2 # megabytes
bs = 512

monitor_only = False # gather metadata without backing up if True

## TICK - process metadata and compile delta info
def prepare_snapshots():

    # Normal precondition will have a snap1vol already in existence in addition
    # to the source datavol. Here we create a fresh snap2vol so we can compare
    # it to the older snap1vol. Then, depending on gather or backup mode, we'll
    # accumulate delta info and possibly use snap2vol as source for a
    # backup session.

    print("Preparing snapshots...")

    # Make initial snapshot if necessary: ##FIX - this also means creating a new set!
    try:
        subprocess.check_call( ["lvs", vgname+"/"+snap1vol] )
    except:
        subprocess.check_call( ["lvcreate", "-pr", "-kn", "-ay", \
            "-s", vgname+"/"+datavol, "-n", snap1vol] )
        print("Initial tick snapshot created.")
        exit(0) ##FIX - Ask to do initial backup.

    # Check for stale snap2vol
    try:
        subprocess.check_call( ["lvs", vgname+"/"+snap2vol] )
    except:
        pass
    else:
        subprocess.check_call( ["lvremove", vgname+"/"+snap2vol] )
        print("Stale snapshot removed.")
        # also cleanup other data from aborted backup...

    # Make current snapshot
    subprocess.check_call( ["lvcreate", "-pr", "-kn", "-ay", \
        "-s", vgname+"/"+datavol, "-n", snap2vol] )
    print("Tock snapshot created.")


# Load lvm metadata
def get_lvm_metadata():
    print("Scanning volume metadata...")
    subprocess.check_output( ["vgcfgbackup", "--reportformat", "json", \
        "-f", volfile ] )
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

    for l in lines:
        refind = re.sub("\s([0-9A-Za-z-]+) {\n", r'\1', l)
        if not refind == l and scope == 2:
            volume = refind.strip()
        if '{' in l: ## fix to handle multiple braces/line
            scope += 1
        if '}' in l:
            scope -= 1
            if scope == 0:
                break
        if scope == 4 and not volume == "" and "device_id =" in l:
            allvols[volume] = re.sub("device_id = ([0-9]+)", r'\1', l).strip()
            volume = ""

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
def get_lvm_delta():
    print("Acquiring LVM delta info...")
    subprocess.check_call( ["dmsetup", "message", vgname+"-"+poolname+"-tpool", \
        "0", "reserve_metadata_snap"] )
    try:
        with open(deltafile, "w") as f:
            subprocess.check_call( ["thin_delta -m" \
                + " --thin1 " + allvols[snap1vol] \
                + " --thin2 " + allvols[snap2vol] \
                + " /dev/mapper/"+vgname+"-"+poolname+"_tmeta" \
                + " | grep -v '<same .*\/>$'" ], shell=True, stdout=f)
    except:
        raise
    finally:
        subprocess.check_call(["dmsetup","message", vgname+"-"+poolname+"-tpool", \
            "0", "release_metadata_snap"] )


def update_delta_digest():
    print("Updating block change map...")
    dtree = xml.etree.ElementTree.parse(deltafile).getroot()
    dblocksize = int(dtree.get("data_block_size"))
    bmap_byte = 0
    lastindex = 0
    dtotalblocks = 0
    icount = 0 #diagnostic counter

    bmap_size = int((snap1size if snap2size <= snap1size else snap2size) \
        / bkchunksize / 8) + 1
    if not os.access(bkdir+"/"+datavol+"_deltamap.dat", os.F_OK):
        with open(bkdir+"/"+datavol+"_deltamap.dat", "wb") as f: #move to prepare_snapshots()
            pass
    with open(bkdir+"/"+datavol+"_deltamap.dat", "r+b") as bmap_file:
        os.ftruncate(bmap_file.fileno(), bmap_size)
        bmap_mm = mmap.mmap(bmap_file.fileno(), 0)

        for delta in dtree.find("diff"):
            #for i in dtree.find("diff").findall("right_only"):
            #if delta.tag == "same":
            #    continue
            #elif delta.tag in ["different", "left_only", "right_only"]:

            blockbegin = int(delta.get("begin")) * dblocksize
            blocklen   = int(delta.get("length")) * dblocksize
            dtotalblocks += blocklen

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
#                print(icount, delta.tag, hex(blockpos*bs), volsegment, bmap_pos, bmap_byte, \
#                    "JUMP" if seg > 0 and seg != volsegment else "")
                seg = volsegment
                icount += 1
#               if icount > 257: #diagnostic sample
#                   break
#        print("WRITE:")
        bmap_mm[lastindex] |= bmap_byte


## TEST changed addr 0x5FFFF1

def rotate_snapshots():
    print("Rotating snapshots...")
    ##FIX - Make this atomic:
    subprocess.check_call( ["lvremove", "--force", vgname+"/"+snap1vol ])
    subprocess.check_call( ["lvrename", vgname+"/"+snap2vol, snap1vol ])


## TOCK - Run backup session

def record_to_bkdir(send_all = False): #add volume and session params

    # Refactor for realistic 'send' use cases
    print("Backing up to", bkdir+"/"+bksession)
    with open("/dev/mapper/"+vgname+"-"+snap2vol.replace("-","--"), "rb") as vf:
        with open(bkdir+"/"+datavol+"_deltamap.dat", "r+b") as bmap_file:
            bmap_mm = mmap.mmap(bmap_file.fileno(), 0)
            for addr in range(0, snap2size, bkchunksize):
                bmap_pos = int(addr / bkchunksize / 8)
                b = int((addr / bkchunksize) % 8)
                print(bmap_pos, b, hex(addr), end=" ")
                if bmap_mm[bmap_pos] & (2** b) or send_all:
                    ## REVIEW int math vs large vol sizes . . .
                    vf.seek(addr)
                    buf = vf.read(bkchunksize)
                    with open(bkdir+"/"+bksession+"/" \
                         + format(addr,"016x"), "wb") as segf:
                        if len(buf) > buf.count(b"\x00"): # write only non-empty
                            segf.write(buf)
                            print("WRITE", end="")
                print("")


def finalize_monitor_session():
    rotate_snapshots()


def finalize_bk_session():
    os.remove(bkdir+"/"+datavol+"_deltamap.dat")
    rotate_snapshots()


## Main
# Check root user, thinp commands, etc.
# Detect/make process lock
# Check dir/file presence, volume sizes, deltabmap size
# Check for modulus bkchunksize/(bs * dblocksize) == 0

print("\nStarting", ["backup","monitor-only"][int(monitor_only)],"session:\n")
if not os.access(bkdir+"/"+bksession, os.F_OK):
    os.makedirs(bkdir+"/"+bksession) ##FIX - change nesting to set/session/pool/vol?

prepare_snapshots()

snap1size, snap2size = get_lvm_metadata()
get_lvm_delta()
update_delta_digest()

if not monitor_only:
    record_to_bkdir()
    finalize_bk_session()
else:
    finalize_monitor_session()

print("\nDone.\n")
