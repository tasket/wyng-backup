#!/bin/python3

###/sparsebak/###
### Christopher Laprise / tasket@github.com



import re
import os
import nmap
import subprocess
import xml.etree.ElementTree

datavol = "vm-untrusted-private"
snap1vol = datavol + "-tick"
snap2vol = datavol + "-tock"
vols = {}
vgname = "qubes_dom0"
poolname = "pool00"
volfile = "/tmp/sparsebak-volumes.txt"
deltafile = "/tmp/sparsebak-delta.xml"
dtree = None
dblocksize = None
bkdir = "/baktest/"+vgname+"%"+poolname
bkchunksize = 1024 * 1024 * 1 # megabytes
bs = 512


## TICK - process metadata and compile delta info
def prepare_snapshots():
    # Make initial snapshot if necessary
    try:
        subprocess.check_call( ["lvs", vgname+"/"+snap1vol] )
    except:
        subprocess.check_call( ["lvcreate", "-pr", "-kn", "-ay", \
            "-s", vgname+"/"+datavol, "-n", snap1vol] )
        print("Initial tick snapshot created.")
        exit(0)

    # Check for stale snapshot
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
    print("Tock snapshot created...")


# Load lvm metadata
def get_lvm_metadata():
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
        raise ValueError("Incorrect format or version")

    for l in lines:
        refind = re.sub("\s([0-9A-Za-z-]+) {\n", r'\1', l)
        if not refind == l and scope == 2:
            volume = refind.strip()
        if '{' in l: # fix to handle multiple braces/line
            scope += 1
        if '}' in l:
            scope -= 1
            if scope == 0:
                break
        if scope == 4 and not volume == "" and "device_id =" in l:
            vols[volume] = re.sub("device_id = ([0-9]+)", r'\1', l).strip()
            volume = ""

    #print(len(vols))
    #for i, j in vols.items():
    #    print(i, j)


# Get delta between snapshots
def get_lvm_delta():
    subprocess.check_call( ["dmsetup", "message", vgname+"-"+poolname+"-tpool", \
        "0", "reserve_metadata_snap"] )
    try:
        with open(deltafile, "w") as f:
            subprocess.check_call( ["thin_delta -m" \
                + " --thin1 " + vols[snap1vol] \
                + " --thin2 " + vols[snap2vol] \
                + " /dev/mapper/"+vgname+"-"+poolname+"_tmeta" \
                + " | grep -v '<same .*\/>$'" ], shell=True, stdout=f)
    except:
        raise
    finally:
        subprocess.check_call(["dmsetup","message", vgname+"-"+poolname+"-tpool", \
            "0", "release_metadata_snap"] )




################### Process delta here:

def update_delta_digest():
    dtree = xml.etree.ElementTree.parse(deltafile).getroot()
    dblocksize = int(dtree.get("data_block_size"))

    icount = 0 #diagnostic counter
    dtotalblocks = 0
    abyte = bytes(1)
    for delta in dtree.find("diff"):
        #if delta.tag == "same":
        #    continue
        #elif delta.tag in ["different", "left_only", "right_only"]:

        blockbegin = int(delta.get("begin")) * dblocksize
        blocklen   = int(delta.get("length")) * dblocksize
        dtotalblocks += blocklen

        seg = 0
        lastindex = 0
        for blockpos in range(blockbegin, blockbegin + blocklen):
            volsegment = int(blockpos / (bkchunksize / bs))
            indexbyte = int(volsegment / 8)
            indexbit  = 2** (volsegment % 8)
            #print(delta.tag, blockpos, volsegment, indexbyte, indexbit)
            #if seg > 0 and seg != volsegment: # crossed into next segment!
            #    print("JUMP")
            #seg = volsegment

            if indexbyte != lastindex:
                pass # write abyte to nmap file, then zero
            
            abyte |= indexbit
            lastindex = indexbyte

        icount += 1
        if icount > 50: #diagnostic sample
            break
#    for i in dtree.find("diff").findall("right_only"):
#        print(i.tag, i.get("begin"), i.get("length"))



## TOCK - Run backup session

#def record_to_bkdir():
    #os.mkdir
    #with open("/dev/mapper/"+snap2vol.replace("-","--"), "r") as f:
    #bandfile = format(i, "04x")
    #with open(bandfile, "w")



## Main
# Check root user, thinp commands, etc.
# Detect/make process lock
# Check dir/file presence, volume sizes, deltabmap size
# Check for modulus bkchunksize/(bs * dblocksize) == 0

#prepare_snapshots()
get_lvm_metadata()
get_lvm_delta()

update_delta_digest()
#record_to_bkdir()
#finalize_bk_session() #add metadata to bkdir and rename tock to tick
