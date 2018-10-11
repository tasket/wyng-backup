#!/bin/python3

### sparsebak
### Christopher Laprise / tasket@github.com



import sys, os, shutil, subprocess, time
#from pathlib import Path
import re, mmap, gzip, tarfile, io, fcntl
import xml.etree.ElementTree
from optparse import OptionParser
import configparser
#import qubesadmin.tools


config = None
topdir = "/sparsebak" # must be absolute path
tmpdir = "/tmp/sparsebak"
volfile = tmpdir+"/volumes.txt"
deltafile = tmpdir+"/delta."
allvols = {}
bs = 512
#bkchunksize = 1024 * 256 # 256k
bkchunksize = 256 * bs # 128k same as thin_delta chunk

if os.getuid() > 0:
    print("sparsebak must be run as root/sudo user.")
    exit(1)
lockpath = "/var/lock/sparsebak"
try:
    lockf = open(lockpath, "w")
    fcntl.lockf(lockf, fcntl.LOCK_EX|fcntl.LOCK_NB)
except IOError:
    print("ERROR: sparsebak is already running.")
    exit(1)


usage = "usage: %prog [options]"
parser = OptionParser(usage)
parser.add_option("-s", "--send", action="store_true", dest="send", default=False,
                help="Perform backup and send to destination")
parser.add_option("--tarfile", action="store_true", dest="tarfile", default=False,
                help="Store backup session as a tarfile")
parser.add_option("-u", "--unattended", action="store_true", dest="unattended", default=False,
                help="Non-interactive, supress prompts")
(options, args) = parser.parse_args()

monitor_only = not options.send # gather metadata without backing up if True


class BkSet:
    class Volume:
        class Ses:
            def  __init__(self, name):
                self.time = 0 # parse name here
                self.vsize = 0
                self.chunksize = 0
                self.Bsent = 0
                self.Zsent = 0
                self.prev = ""
                self.finalized = False
                # get info file
        def __init__(self, name):
            self.sessions = []
            self.vsize = self.sessions[-1].vsize
            self.name = ""

    def __init__(self, name):
        self.name = name
        self.vgname = None
        self.poolname = None
        self.destvm = None
        self.destmountpoint = None
        self.destdir = None
        self.vols = []


def get_configs():
    config = configparser.ConfigParser()
    config.read(topdir+"/sparsebak.ini")
    c = config["var"]
    dvs = []
    print("Volume selections:")
    for key in config["volumes"]:
        if config["volumes"][key] != "disable":
            dvs.append(key)
            print(" ", key)

    return c['vgname'], c['poolname'], c['destvm'], c['destmountpoint'], \
           c['destdir'], dvs


# Check run environment and determine previous session, and if it completed.
# Example: if .deltamap-tmp exists, then perform checks on
# which snapshots exist.
def detect_state():
    vm_run_args = {"none":[],
                   "qubes":["qvm-run", "-p", destvm]
                  }
    if os.path.exists("/etc/qubes-release") and destvm != None:
        vmtype = "qubes"
    else:
        vmtype = "none" # no virtual machine

    if not monitor_only and destvm != None:
        try:
            t = subprocess.check_output(vm_run_args[vmtype]+["mountpoint " \
                +destmountpoint+" && mkdir -p "+destmountpoint+"/"+destdir \
                +" && touch "+destmountpoint+"/"+destdir+" && sync"])
        except:
            print("Destination VM not ready to receive backup; Exiting.")
            exit(1)

    for cmd in ["vgcfgbackup","thin_delta","lvdisplay","lvcreate"]:
        if not shutil.which(cmd):
            print("ERROR: Command not found,", cmd)
            exit(1)

    return vmtype, vm_run_args


## TICK - process metadata and compile delta info
def prepare_snapshots():

    ''' Normal precondition will have a snap1vol already in existence in addition
    to the source datavol. Here we create a fresh snap2vol so we can compare
    it to the older snap1vol. Then, depending on monitor or backup mode, we'll
    accumulate delta info and possibly use snap2vol as source for a
    backup session.
    '''

    ''' Todo: Check snap1 creation time to make sure it isn't newer
    than snap2 from previous session. Move info file creation to
    the update_delta_digest function.
    Associated rule: Latest session cannot
    be simply pruned; an earlier target must first be restored to system
    then snap1 and info file synced (possibly by adding an empty session on
    top of the target session in the archive); alternative is to save deltamaps
    to the archive and when deleting the latest session import its deltamap.
    '''

    print("Preparing snapshots...")
    dvs = []
    nvs = []
    for datavol in datavols:
        snap1vol = datavol + ".tick"
        snap2vol = datavol + ".tock"
        if datavol[0] == "#":
            continue
        elif not lv_exists(vgname, datavol):
            print("Warning:", datavol, "does not exist!")
            continue

        # Remove stale snap2vol
        if lv_exists(vgname, snap2vol):
            p = subprocess.check_output(["lvremove", "-f",vgname+"/"+snap2vol],
                                        stderr=subprocess.STDOUT)

        # Make initial snapshot if necessary:
        if not os.path.exists(bkdir+"/"+datavol+".deltamap") \
        and not os.path.exists(bkdir+"/"+datavol+".deltamap-tmp"):
            if not monitor_only and not lv_exists(vgname, snap1vol):
                p = subprocess.check_output(["lvcreate", "-pr", "-kn", \
                    "-ay", "-s", vgname+"/"+datavol, "-n", snap1vol], \
                    stderr=subprocess.STDOUT)
                print("  Initial snapshot created for", datavol)
            nvs.append(datavol)
        elif os.path.exists(bkdir+"/"+datavol+".deltamap-tmp"):
            raise Exception("ERROR: Previous delta map not finalized for " \
                            +datavol+" (needs recovery)")
            # Fix: ask to recover/use the tmp file
        elif not lv_exists(vgname, snap1vol):
            raise Exception("ERROR: Map and snapshots in inconsistent state, "
                            +snap1vol+" is missing!")

        # Make current snapshot
        p = subprocess.check_output( ["lvcreate", "-pr", "-kn", "-ay", \
            "-s", vgname+"/"+datavol, "-n",snap2vol], stderr=subprocess.STDOUT)
        print("  Current snapshot created:", snap2vol)

        if datavol not in nvs:
            dvs.append(datavol)

    return dvs, nvs


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
    print("\nScanning volume metadata...")
    p = subprocess.check_output( ["vgcfgbackup", "--reportformat", "json", \
        "-f", volfile ], stderr=subprocess.STDOUT )
    with open(volfile) as f:
        lines = f.readlines()
    scope = 0
    volume = devid = ""
    version = False
    for l in lines:
        if l.strip() == "version = 1":
            version = True
            break
    if not version:
        raise ValueError("Incorrect format from 'vgcfgbackup'!")

    # Parse all volumes and their thinlv ids
    for l in lines:
        refind = re.sub("\s([0-9A-Za-z\_\-\+\.]+) {\n", r'\1', l)
        scope += l.count('{')
        scope -= l.count('}')
        if scope == 3 and not refind == l:
            volume = refind.strip()
            allvols[volume] = [None]
        elif scope == 4 and volume > "" and None in allvols[volume]:
            if "device_id =" in l:
                devid = re.sub("device_id = ([0-9]+)", r'\1', l).strip()
            #elif "transaction_id =" in l:
            #    trans = re.sub("transaction_id = ([0-9]+)", r'\1', l).strip()
        elif scope == 0 and '}' in l:
            break
        if devid > "":
            allvols[volume] = [devid]
            volume = devid = ""


def get_lvm_size(vol):
    line = subprocess.check_output( ["lvdisplay --units=b " \
        + " /dev/mapper/"+vgname+"-"+vol.replace("-","--") \
        +  "| grep 'LV Size'"], shell=True).decode("UTF-8").strip()
    return int(re.sub("^.+ ([0-9]+) B", r'\1', line))


# Get delta between snapshots
def get_lvm_deltas():
    print("Acquiring LVM delta info.")
    subprocess.call(["dmsetup","message", vgname+"-"+poolname+"-tpool", \
        "0", "release_metadata_snap"], stderr=subprocess.DEVNULL)
    subprocess.check_call(["dmsetup", "message", vgname+"-"+poolname+"-tpool", \
        "0", "reserve_metadata_snap"])
    td_err = False
    for datavol in datavols:
        snap1vol = datavol + ".tick"
        snap2vol = datavol + ".tock"
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

    if datavol in newvols:
        return False, False
    os.rename(mapstate, mapstate+"-tmp")

    print("Updating block change map", end="")
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
            else: # superfluous tag
                continue

#            seg = 0
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
#                seg = volsegment
#        print("WRITE:")
        bmap_mm[lastindex] |= bmap_byte
    if dnewblocks+dfreedblocks > 0:
        print(", added", dnewblocks * bs, "changes,",
              dfreedblocks * bs, "discards.")
    else:
        print()
    return True, dnewblocks+dfreedblocks > 0


## TOCK - Run backup session

def record_to_vm(send_all = False):
    sessions = sorted([e for e in os.listdir(bkdir+"/"+datavol) \
                        if e[:2]=="S_" and e[-3:]!="tmp"])
    sdir=bkdir+"/"+datavol+"/"+bksession
    zeros = bytes(bkchunksize)
    bcount = zcount = 0
    thetime = time.time()
    if send_all:
        # sends all from this address forward
        sendall_addr = 0
    else:
        sendall_addr = snap2size + 1

    print("Backing up to VM", destvm)

    # Check volume size vs prior backup session
    if len(sessions) > 0 and not send_all:
        with open(bkdir+"/"+datavol+"/"+sessions[-1]+"/info", "r") as sf:
            lines = sf.readlines()
        for l in lines:
            if l.strip()[:7] == "volsize":
                prior_size = int(l.split()[2])
                break
        next_chunk_addr = (prior_size-1) - ((prior_size-1) % bkchunksize) \
                        + bkchunksize
        if prior_size > snap2size:
            print("  Volume size has shrunk.")
        elif snap2size-1 >= next_chunk_addr:
            print("  Volume size has increased.")
            sendall_addr = next_chunk_addr

    # Use tar to stream files to destination
    stream_started = False
    if options.tarfile:
        # don't untar at destination
        untar_cmd = ["cd "+destmountpoint+"/"+destdir+" && mkdir -p ."+sdir \
                    +" && cat >."+sdir+"/"+bksession+".tar"]
    else:
        untar_cmd = ["cd "+destmountpoint+"/"+destdir+" && tar -xf -"]

    with open("/dev/mapper/"+vgname+"-"+snap2vol.replace("-","--"),"rb") as vf:
        with open("/dev/zero" if send_all else mapstate+"-tmp","r+b") as bmapf:
            bmap_mm = bytes(1) if send_all else mmap.mmap(bmapf.fileno(), 0)

            for addr in range(0, snap2size, bkchunksize):
                bmap_pos = int(addr / bkchunksize / 8)
                b = int((addr / bkchunksize) % 8)
                if addr >= sendall_addr or bmap_mm[bmap_pos] & (2** b):
                    vf.seek(addr)
                    buf = vf.read(bkchunksize)
                    destfile = format(addr,"016x")
                    print(" ",int((bmap_pos/bmap_size)*100),"%  ",bmap_pos, \
                            destfile, end=" ")

                    # write only non-empty and last chunks
                    if buf != zeros or addr >= snap2size-bkchunksize:
                        # Performance fix: move compression into separate processes
                        bcount += len(buf)
                        buf = gzip.compress(buf, compresslevel=4)
                        print(" DATA ", end="\x0d")
                    else:
                        print("______", end="\x0d")
                        buf = bytes(0)
                        zcount += 1

                    if not stream_started:
                        untar = subprocess.Popen(vm_run_args[vmtype] + untar_cmd, \
                                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, \
                                stderr=subprocess.DEVNULL)
                        tarf = tarfile.open(mode="w|", fileobj=untar.stdin)
                        stream_started = True

                    tar_info = tarfile.TarInfo(sdir+"-tmp/"+destfile[:-7] \
                                +"/x"+destfile)
                    tar_info.size = len(buf)
                    tar_info.mtime = thetime
                    tarf.addfile(tarinfo=tar_info, fileobj=io.BytesIO(buf))

    if stream_started:
        print("  100%")

        os.makedirs(sdir+"-tmp")
        with open(sdir+"-tmp/info", "w") as f:
            print("volsize =", snap2size, file=f)
            print("chunksize =", bkchunksize, file=f)
            print("sent =", bcount, file=f)
            print("zeros =", zcount, file=f)
            print("format =", "tar" if options.tarfile else "folders", file=f)
            print("previous =", "none" if send_all else sessions[-1], file=f)
        tarf.add(sdir+"-tmp/info")

        #print("Ending tar process ", end="")
        tarf.close()
        untar.stdin.close()
        for i in range(10):
            time.sleep(1)
            if untar.poll() != None:
                break
        if untar.poll() == None:
            time.sleep(5)
            if untar.poll() == None:
                untar.terminate()
                print("terminated untar process!")
                # fix: verify archive dir contents here

        p = subprocess.check_output(vm_run_args[vmtype]+ \
            ["cd "+destmountpoint+"/"+destdir \
            +(" && mv ."+sdir+"-tmp ."+sdir if not options.tarfile else "") \
            +" && sync"])

    print(" ", bcount, "bytes sent.")
    return bcount+zcount > 0


def init_deltamap(bmfile):
    if os.path.exists(bmfile):
        os.remove(bmfile)
    if os.path.exists(bmfile+"-tmp"):
        os.remove(bmfile+"-tmp")
    with open(bmfile, "wb") as bmapf:
        os.ftruncate(bmapf.fileno(), bmap_size)


def rotate_snapshots(rotate=True):
    if rotate:
        print("Rotating snapshots for", datavol)
        # Review: this should be atomic
        p = subprocess.check_output(["lvremove","--force", vgname+"/"+snap1vol])
        p = subprocess.check_output(["lvrename",vgname+"/"+snap2vol, snap1vol])
    else:
        p = subprocess.check_output(["lvremove","--force",vgname+"/"+snap2vol])


def finalize_monitor_session():
    rotate_snapshots(map_updated)
    os.rename(mapstate+"-tmp", mapstate)
    os.sync()


def finalize_bk_session(sent):
    rotate_snapshots(sent)
    init_deltamap(mapstate)
    os.sync()



##  Main  #####################################################################

''' ToDo:
Config management
Encryption and manifests
Restore and verify
Separate threads for encoding tasks
Option for live Qubes volumes (*-private-snap)
Gracefully abort send during interruption
Auto-resume aborted backup session
Auto-pruning/rotation
Check dir/file presence, volume sizes, deltabmap size
Check for modulus bkchunksize/(bs * dblocksize) == 0 and mod 4096
Make separate /var (local) and dest (remote) directories
'''

vgname, poolname, destvm, destmountpoint, destdir, datavols \
= get_configs()
#print(vgname, poolname, destvm, destmountpoint, destdir, datavols)

bkdir = topdir+"/"+vgname+"%"+poolname
bksession = time.strftime("S_%Y%m%d-%H%M%S")

print("\nStarting", ["backup","monitor-only"][monitor_only], \
      "session", [bksession,""][monitor_only])

shutil.rmtree(tmpdir+"-old", ignore_errors=True)
if os.path.exists(tmpdir):
    os.rename(tmpdir, tmpdir+"-old")
os.makedirs(tmpdir)
if not os.path.exists(bkdir):
    os.makedirs(bkdir)

vmtype, vm_run_args \
= detect_state()

datavols, newvols \
= prepare_snapshots()

get_lvm_metadata()

if monitor_only:
    newvols = []
if len(datavols)+len(newvols) == 0:
    print("No new data.")
    exit(0)

if len(datavols) > 0:
    get_lvm_deltas()

for datavol in datavols+newvols:
    print("\nProcessing Volume :", datavol)
    snap1vol = datavol + ".tick"
    snap2vol = datavol + ".tock"
    snap1size = get_lvm_size(snap1vol)
    snap2size = get_lvm_size(snap2vol)
    bmap_size = int(snap2size / bkchunksize / 8) + 1

    mapstate = bkdir+"/"+datavol+".deltamap"
    map_exists, map_updated \
    = update_delta_digest()

    if not monitor_only:
        sent \
        = record_to_vm(send_all = datavol in newvols)
        finalize_bk_session(sent)
    else:
        finalize_monitor_session()


print("\nDone.\n")
