#!/bin/python3

### sparsebak
### Christopher Laprise / tasket@github.com



import os, shutil, subprocess, time
from pathlib import Path
import re, mmap, lzma
import xml.etree.ElementTree
from optparse import OptionParser
#import qubesadmin.tools

bkset = "set04"
setdir = "/baktest/"+bkset
vgname = "qubes_dom0"
poolname = "pool00"

tmpdir = "/tmp/sparsebak"
volfile = tmpdir+"/volumes.txt"
deltafile = tmpdir+"/delta."
allvols = {}
datavols = []
newvols = []
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

if options.full and not options.send:
    print("ERROR: --full option requires --send.")
    exit(1)

monitor_only = not options.send # gather metadata without backing up if True



def get_configs():
    with open(setdir+"/sparsebak.conf", "r") as f:
        datavols = f.read().splitlines()
    return datavols


# Determine previous session, and if it completed.
# Example: if .deltamap-tmp exists, then perform checks on
# which snapshots exist.
def detect_state():
    pass


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
        if not lv_exists(vgname, datavol):
            # FIX: Remove non-existent volume from list...........
            print("ERROR:", datavol, "does not exist!")
            exit(1) #fix

        # Remove stale snap2vol
        if lv_exists(vgname, snap2vol):
            p = subprocess.check_output(["lvremove", "-f",vgname+"/"+snap2vol],
                                        stderr=subprocess.STDOUT)

        # Make initial snapshot if necessary:
        if not os.path.exists(bkdir+"/"+datavol+".deltamap") \
            and not os.path.exists(bkdir+"/"+datavol+".deltamap-tmp"):
            if options.full and not lv_exists(vgname, snap1vol):
                p = subprocess.check_output(["lvcreate", "-pr", "-kn", "-ay", "-s",
                    vgname+"/"+datavol, "-n", snap1vol], stderr=subprocess.STDOUT)
                print("Initial snapshot created:", snap1vol)
            newvols.append(datavol)
        elif os.path.exists(bkdir+"/"+datavol+".deltamap-tmp"):
            raise Exception("ERROR - Previous delta map was not finalized. Rename "
                +mapstate+"-tmp without -tmp to recover.")
            # Fix: ask to recover/use the tmp file
        elif not lv_exists(vgname, snap1vol):
            raise Exception("ERROR: Map and snapshots in inconsistent state, "
                +snap1vol+" is missing!")


def lv_exists(vgname, lvname):
    try:
        p = subprocess.check_output( ["lvs", vgname+"/"+lvname],
                                    stderr=subprocess.STDOUT )
    except:
        return False
    else:
        return True


# Load lvm metadata
def get_lvm_metadata():
    print("Scanning volume metadata...")
    p = subprocess.check_output( ["vgcfgbackup", "--reportformat", "json", \
        "-f", volfile ], stderr=subprocess.STDOUT )
    with open(volfile) as f:
        lines = f.readlines()
    scope = 0
    volume = devid = trans = ""
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
            allvols[volume] = [None, None]
        elif scope == 4 and volume > "" and None in allvols[volume] and "device_id =" in l:
            devid = re.sub("device_id = ([0-9]+)", r'\1', l).strip()
        elif scope == 4 and volume > "" and None in allvols[volume] and "transaction_id =" in l:
            trans = re.sub("transaction_id = ([0-9]+)", r'\1', l).strip()
        elif scope == 0 and '}' in l:
            break
        if devid > "" and trans > "":
            allvols[volume] = [devid, trans]
            volume = devid = trans = ""


def get_lvm_size(vol):
    line = subprocess.check_output( ["lvdisplay --units=b " \
        + " /dev/mapper/"+vgname+"-"+vol.replace("-","--") \
        +  "| grep 'LV Size'"], shell=True).decode("UTF-8").strip()
    return int(re.sub("^.+ ([0-9]+) B", r'\1', line))


# Compare transaction ids, include only vols with new or doing first backup
def find_changed_vols():
    dvs = []
    for datavol in datavols:
        snap1vol = datavol + ".tick"
        snap2vol = datavol + ".tock"
        reason = ""
        if datavol in newvols and options.full:
            pass
        elif datavol in newvols:
            reason = "- needs initial full backup"
        elif int(allvols[datavol][1]) <= int(allvols[snap1vol][1]) \
        and monitor_only:
            reason = "- no new transactions"
        else:
            dvs.append(datavol)

        if reason > "":
            print("  Skipping", datavol, reason)
        else:
            # Make current snapshot
            p = subprocess.check_output( ["lvcreate", "-pr", "-kn", "-ay", \
                "-s", vgname+"/"+datavol, "-n",snap2vol], stderr=subprocess.STDOUT)
            print("  Current snapshot created:", snap2vol)

    return dvs


# Get delta between snapshots
def get_lvm_deltas():
    print("\nAcquiring LVM delta info...")
    subprocess.run(["dmsetup","message", vgname+"-"+poolname+"-tpool", \
        "0", "release_metadata_snap"], check=False, stderr=subprocess.DEVNULL)
    subprocess.check_call(["dmsetup", "message", vgname+"-"+poolname+"-tpool", \
        "0", "reserve_metadata_snap"])
    td_err = False
    for datavol in datavols:
        snap1vol = datavol + ".tick"
        snap2vol = datavol + ".tock"
        if int(allvols[datavol][1]) <= int(allvols[snap1vol][1]):
            continue
        try:
            with open(deltafile+datavol, "w") as f:
                cmd = ["thin_delta -m" \
                    + " --thin1 " + allvols[snap1vol][0] \
                    + " --thin2 " + allvols[snap2vol][0] \
                    + " /dev/mapper/"+vgname+"-"+poolname+"_tmeta" \
                    + " | grep -v '<same .*\/>$'" ]
                #print(cmd[0])
                subprocess.check_call(cmd, shell=True, stdout=f)
        except:
            td_err = True
    subprocess.check_call(["dmsetup","message", vgname+"-"+poolname+"-tpool", \
        "0", "release_metadata_snap"] )
    if td_err:
        print("ERROR running thin_delta process!")
        exit(1)


def update_delta_digest():

    if not os.path.exists(mapstate):
        print("Skipping map update.")
        return False, False
    os.rename(mapstate, mapstate+"-tmp")

    if int(allvols[datavol][1]) <= int(allvols[snap1vol][1]):
        return True, False

    print("Updating block change map...")
    dtree = xml.etree.ElementTree.parse(deltafile+datavol).getroot()
    dblocksize = int(dtree.get("data_block_size"))
    bmap_byte = 0
    lastindex = 0
    dnewblocks = 0
    dfreedblocks = 0

    with open(mapstate+"-tmp", "r+b") as bmapf:
        os.ftruncate(bmapf.fileno(), bmap_size)
        bmap_mm = mmap.mmap(bmapf.fileno(), 0)

        for delta in dtree.find("diff"):
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
    #os.rename(mapstate+"-tmp", mapstate)
    print("  New changes  :", dnewblocks * bs, "bytes")
    print("  New Discards :", dfreedblocks * bs, "bytes")
    return True, dnewblocks+dfreedblocks > 0


## TOCK - Run backup session

def record_to_bkdir(send_all = False):
    # Refactor for realistic 'send' use cases
    # Add a stat file for each vol/session showing vol size and previous session

    destdir=bkdir+"/"+datavol+"/"+bksession
    print("Backing up to", destdir)
    os.makedirs(destdir+"-tmp")
    zeros = bytes(bkchunksize)
    bcount = 0

    with open("/dev/mapper/"+vgname+"-"+snap2vol.replace("-","--"),"rb") as vf:
        with open("/dev/zero" if send_all else mapstate+"-tmp","r+b") as bmapf:
            bmap_mm = bytes(1) if send_all else mmap.mmap(bmapf.fileno(), 0)
            for addr in range(0, snap2size, bkchunksize):
                bmap_pos = int(addr / bkchunksize / 8)
                b = int((addr / bkchunksize) % 8)
                print(bmap_pos, b, hex(addr), end=" ")
                if send_all or bmap_mm[bmap_pos] & (2** b):
                    ## REVIEW int math vs large vol sizes . . .
                    vf.seek(addr)
                    buf = vf.read(bkchunksize)
                    destfile = destdir+"-tmp/"+format(addr,"016x")
                    #subdir = destfile[:-7] ???
                    if buf != zeros: # write only non-empty
                        # Performance fix: move compression into separate processes
                        with lzma.open(destfile, "wb", preset=0) as segf:
                            segf.write(buf)
                        bcount += len(buf)
                        print("DATA", end="")
                    else:
                        Path(destfile).touch()
                print("     ", end="\x0d")
    os.rename(destdir+"-tmp", destdir)
    print("Bytes sent:", bcount)
    return bcount


def init_deltamap(bmfile):
    if os.path.exists(bmfile):
        os.remove(bmfile)
    if os.path.exists(bmfile+"-tmp"):
        os.remove(bmfile+"-tmp")
    with open(bmfile, "wb") as bmapf:
        os.ftruncate(bmapf.fileno(), bmap_size)


def rotate_snapshots():
    print("Rotating snapshots for", datavol)
    # Review: this should be atomic
    p = subprocess.check_output( ["lvremove", "--force", vgname+"/"+snap1vol ])
    p = subprocess.check_output( ["lvrename", vgname+"/"+snap2vol, snap1vol ])


def finalize_monitor_session():
    if map_updated:
        rotate_snapshots()
    os.rename(mapstate+"-tmp", mapstate)


def finalize_bk_session(bcount):
    if bcount > 0:
        rotate_snapshots()
    init_deltamap(mapstate)



## Main ###########################################################
# ToDo: Check root user, thinp commands, etc.
# Detect/make process lock
# Check dir/file presence, volume sizes, deltabmap size
# Check for modulus bkchunksize/(bs * dblocksize) == 0 and mod 4096
#
# Make separate /var (local) and dest (remote) directories

print("\nStarting", ["backup","monitor-only"][int(monitor_only)],"session:\n")

shutil.rmtree(tmpdir+"-old", ignore_errors=True)
if os.path.exists(tmpdir):
    os.rename(tmpdir, tmpdir+"-old")
os.makedirs(tmpdir)
if not os.path.exists(bkdir):
    os.makedirs(bkdir)

datavols = get_configs()
detect_state()
prepare_snapshots()
get_lvm_metadata()
datavols = find_changed_vols()

if not options.full:
    newvols = []
if len(datavols)+len(newvols) == 0:
    print("No new data.")
    exit(0)
    
# get metadata again after find_changed_vols:
get_lvm_metadata()

if len(datavols) > 0:
    get_lvm_deltas()

for datavol in datavols+newvols:
    print("\n** Starting", datavol)
    snap1vol = datavol + ".tick"
    snap2vol = datavol + ".tock"
    snap1size = get_lvm_size(snap1vol)
    snap2size = get_lvm_size(snap2vol)
    bmap_size = int(snap2size / bkchunksize / 8) + 1

    mapstate = bkdir+"/"+datavol+".deltamap"
    map_exists, map_updated = update_delta_digest()

    if not monitor_only:
        bcount = record_to_bkdir(send_all = datavol in newvols)
        finalize_bk_session(bcount)
    else:
        finalize_monitor_session()


print("\nDone.\n")
