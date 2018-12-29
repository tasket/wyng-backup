#!/usr/bin/python3


###  sparsebak
###  Copyright Christopher Laprise 2018 / tasket@github.com
###  Licensed under GNU General Public License v3. See file 'LICENSE'.


import sys, os, stat, shutil, subprocess, time, datetime
from os.path import join as pjoin
import re, mmap, gzip, tarfile, io, fcntl, tempfile
import xml.etree.ElementTree
import argparse, configparser, hashlib
#import qubesadmin.tools


class ArchiveSet:
    def __init__(self, name, top, conf):
        cp = configparser.ConfigParser()
        cp.optionxform = lambda option: option
        cp.read(pjoin(top,conf))
        c = cp["var"]

        self.name = name
        self.vgname = c['vgname']
        self.poolname = c['poolname']
        self.path = pjoin(top,self.vgname+"%"+self.poolname)
        self.destvm = c['destvm']
        self.destmountpoint = c['destmountpoint']
        self.destdir = c['destdir']

        self.vols = {}
        for key in cp["volumes"]:
            if cp["volumes"][key] != "disable":
                os.makedirs(pjoin(self.path,key), exist_ok=True)
                self.vols[key] = self.Volume(key, self.path, self.vgname)
                self.vols[key].enabled = True
                self.vols[key].present = True

        #fs_vols = [e.name for e in os.scandir(self.path) if e.is_dir()
        #           and e.name not in self.vols.keys()]
        #for key in fs_vols:
        #    self.vols[key] = self.Volume(key, self.path)

    class Volume:
        def __init__(self, name, path, vgname):
            self.present = lv_exists(vgname, name)

            # Move map to new location
            mapfile = pjoin(path, name, "deltamap")
            if os.path.exists(path+"/"+name+".deltamap"):
                os.rename(path+"/"+name+".deltamap", mapfile)

            self.mapped = os.path.exists(mapfile)
            self.sessions ={e.name: self.Ses(e.name,pjoin(path,name)) for e \
                in os.scandir(pjoin(path,name)) if e.name[:2]=="S_" \
                    and e.name[-3:]!="tmp"} if self.present else {}
            # use latest volsize
            self.volsize = self.sessions[sorted(self.sessions)[-1]].volsize \
                            if len(self.sessions)>0 else 0
            self.name = name
            self.enabled = False

        class Ses:
            def  __init__(self, name, path):
                self.name = name
                self.localtime = None
                self.volsize = None
                self.chunksize = None
                self.chunks = None
                self.bytes = None
                self.zeros = None
                self.format = None
                self.previous = None
                self.manifest = None
                a_ints = ["volsize","chunksize","chunks","bytes","zeros"]

                with open(pjoin(path,name,"info"), "r") as sf:
                    lines = sf.readlines()
                for ln in lines:
                    vname, value = ln.strip().split(" = ")
                    setattr(self, vname, 
                            int(value) if vname in a_ints else value)


class Lvm_VolGroup:
    def __init__(self, name):
        self.name = name
        self.lvs = {}

class Lvm_Volume:
    colnames = ["vg_name","lv_name","lv_attr","lv_size","lv_time",
                "pool_lv","thin_id","lv_path"]
    a_ints = ["lv_size"]

    def __init__(self, members):
        for attr in self.colnames:
            val = members[self.colnames.index(attr)]
            setattr(self, attr, int(re.sub("[^0-9]", "", val)) if attr \
                in self.a_ints else val)


# Retrieves survey of all LVs as vgs[].lvs[] dicts
def get_lvm_vgs():

    p = subprocess.check_call(["lvs --units=b --noheadings --separator ::"
        +" -o " + ",".join(Lvm_Volume.colnames)
        +" >"+tmpdir+"/volumes.lst"], shell=True)

    vgs = {}
    with open(tmpdir+"/volumes.lst", "r") as vlistf:
        for ln in vlistf:
            members = ln.strip().split("::")
            vgname = members[0] # Fix: use colname index
            lvname = members[1]
            if vgname not in vgs.keys():
                vgs[vgname] = Lvm_VolGroup(vgname)
            vgs[vgname].lvs[lvname] = Lvm_Volume(members)

    return vgs


# Get global configuration settings:
def get_configs():
    global aset

    aset = ArchiveSet("", topdir, "sparsebak.ini")
    dvs = []

    print("\nConfigured Volumes:")
    for vn,v in aset.vols.items():
        if v.enabled:
            dvs.append(v.name)
            print(" ",v.name)

    # temporary kludge:
    return aset.vgname, aset.poolname, aset.destvm, aset.destmountpoint, \
        aset.destdir, dvs


# Detect features of internal and destination environments:
def detect_internal_state():
    global destvm

    if os.path.exists("/etc/qubes-release") and destvm[:8] == "qubes://":
        vmtype = "qubes" # Qubes OS guest VM
        destvm = destvm[8:]
    elif destvm[:6] == "ssh://":
        vmtype = "ssh"
        destvm = destvm[6:]
    elif destvm[:12] == "qubes-ssh://":
        vmtype = "qubes-ssh"
        destvm = destvm[12:]
    elif destvm[:11] == "internal:":
        vmtype = "internal" # local shell environment
    else:
        raise ValueError("'destvm' not an accepted type.")

    for prg in ["thin_delta","lvs","lvdisplay","lvcreate","blkdiscard",
                "truncate","ssh" if vmtype=="ssh" else "sh"]:
        if not shutil.which(prg):
            raise RuntimeError("Required command not found: "+prg)

    return vmtype


def detect_dest_state(destvm):

    if options.action in ["send","receive","verify","diff","prune"] \
    and destvm != None:

        if vmtype == "qubes-ssh":
            dargs = vm_run_args["qubes"][:-1] + [destvm.split("|")[0]]

            cmd = ["set -e; rm -rf "+tmpdir+"-old"
                  +" && { if [ -d "+tmpdir+" ]; then mv "+tmpdir
                  +" "+tmpdir+"-old; fi }"
                  +"  && mkdir -p "+tmpdir+"/rpc"
                  ]
            p = subprocess.check_call(dargs + cmd)

        # Fix: get OSTYPE env variable
        try:
            cmd =  \
                ["mountpoint -q '"+destmountpoint
                +"' && mkdir -p '"+destmountpoint+"/"+destdir+topdir
                +"' && cd '"+destmountpoint+"/"+destdir+topdir
                +"' && touch archive.dat"
                +"  && ln -f archive.dat .hardlink"
                +"  && rm -rf '"+tmpdir+"-old"
                +"' && { if [ -d "+tmpdir+" ]; then mv "+tmpdir
                +" "+tmpdir+"-old; fi }"
                +"  && mkdir -p "+tmpdir+"/rpc"
                ]

            p = subprocess.check_call(
                " ".join(dest_run_args(vmtype, cmd)), shell=True)
        except:
            raise RuntimeError("Destination not ready to receive commands.")


# Run system commands
def dest_run(commands, dest_type=None, dest=None):
    if dest_type is None:
        dest_type = vmtype

    cmd = " ".join(dest_run_args(dest_type, commands))
    p = subprocess.check_call(cmd, shell=True)

    #else:
    #    p = subprocess.check_output(cmd, **kwargs)


def dest_run_args(dest_type, commands):

    run_args =  vm_run_args ####

    # shunt commands to tmp file
    with tempfile.NamedTemporaryFile(dir=tmpdir, delete=False) as tmpf:
        tmpf.write(bytes("set -e; "+" ".join(commands) + "\n",
                        encoding="UTF-8"))
        remotetmp = os.path.basename(tmpf.name)

    if dest_type in ["qubes","qubes-ssh"]:

        cmd = ["cat "+pjoin(tmpdir,remotetmp)
              +" | qvm-run -p "
              +(destvm if dest_type == "qubes" else destvm.split("|")[0])
              +" 'mkdir -p "+pjoin(tmpdir,"rpc")
              +" && cat >"+pjoin(tmpdir,"rpc",remotetmp)+"'"
              ]
        p = subprocess.check_call(cmd, shell=True)

        if dest_type == "qubes":
            add_cmd = ["'sh "+pjoin(tmpdir,"rpc",remotetmp)+"'"]
        elif dest_type == "qubes-ssh":
            add_cmd = ["'ssh "+destvm.split("|")[1]
                      +" $(cat "+pjoin(tmpdir,"rpc",remotetmp)+")'"]

    elif dest_type == "ssh":
        add_cmd = [" $(cat "+pjoin(tmpdir,remotetmp)+")"]

    elif dest_type == "internal":
        add_cmd = [pjoin(tmpdir,remotetmp)]

    ret = run_args[dest_type] + add_cmd
    #print("CMD",ret)
    return ret


# Prepare snapshots and check consistency with metadata:

def prepare_snapshots(datavols):

    ''' Normal precondition will have a snap1vol already in existence in addition
    to the source datavol. Here we create a fresh snap2vol so we can compare
    it to the older snap1vol. Then, depending on monitor or backup mode, we'll
    accumulate delta info and possibly use snap2vol as source for a
    backup session.

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
        sessions = get_sessions(datavol)
        snap1vol = datavol + ".tick"
        snap2vol = datavol + ".tock"
        mapfile = pjoin(bkdir, datavol, "deltamap")

        if not lv_exists(vgname, datavol):
            print("Warning:", datavol, "does not exist!")
            continue

        # Remove stale snap2vol
        if lv_exists(vgname, snap2vol):
            p = subprocess.check_output(["lvremove", "-f",vgname+"/"+snap2vol],
                                        stderr=subprocess.STDOUT)

        # Future: Expand recovery to start send-resume
        if os.path.exists(mapfile+"-tmp"):
            print("  Delta map not finalized for",
                  datavol, "...recovering.")
            os.rename(mapfile+"-tmp", mapfile)

        # Make initial snapshot if necessary:
        if not os.path.exists(mapfile):
            if len(sessions) > 0:
                raise RuntimeError("ERROR: Sessions exist but no map for "+datavol)
            if not monitor_only and not lv_exists(vgname, snap1vol):
                p = subprocess.check_output(["lvcreate", "-pr", "-kn",
                    "-ay", "-s", vgname+"/"+datavol, "-n", snap1vol],
                    stderr=subprocess.STDOUT)
                print("  Initial snapshot created for", datavol)
            nvs.append(datavol)

        if not lv_exists(vgname, snap1vol):
            raise RuntimeError("ERROR: Map and snapshots in inconsistent state, "
                            +snap1vol+" is missing!")

        # Make current snapshot
        p = subprocess.check_output( ["lvcreate", "-pr", "-kn", "-ay",
            "-s", vgname+"/"+datavol, "-n",snap2vol], stderr=subprocess.STDOUT)
        print("  Current snapshot created:", snap2vol)

        if datavol not in nvs:
            dvs.append(datavol)

    return dvs, nvs


def lv_exists(vgname, lvname):
    try:
        p = subprocess.check_output( ["lvdisplay", vgname+"/"+lvname],
                                    stderr=subprocess.STDOUT )
    except:
        return False
    else:
        return True


def vg_exists(vgname):
    try:
        p = subprocess.check_output( ["vgdisplay", vgname],
                                    stderr=subprocess.STDOUT )
    except:
        return False
    else:
        return True


def get_lvm_size(volpath):
    line = subprocess.check_output( ["lvdisplay --units=b " + volpath
        +  " | grep 'LV Size'"], shell=True).decode("UTF-8").strip()

    size = int(re.sub("^.+ ([0-9]+) B", r'\1', line))
    if size > max_address + 1:
        raise ValueError("Volume size is larger than", max_address+1)
    return size


def get_info_vol_size(datavol, ses=""):
    if ses == "":
        # Select last session if none specified
        ses = get_sessions(datavol)[-1]

    return aset.vols[datavol].sessions[ses].volsize


# Get raw lvm deltas between snapshots
def get_lvm_deltas(datavols):
    print("Acquiring LVM delta info.")
    subprocess.call(["dmsetup","message", vgname+"-"+poolname+"-tpool",
        "0", "release_metadata_snap"], stderr=subprocess.DEVNULL)
    subprocess.check_call(["dmsetup", "message", vgname+"-"+poolname+"-tpool",
        "0", "reserve_metadata_snap"])
    td_err = False
    for datavol in datavols:
        snap1vol = datavol + ".tick"
        snap2vol = datavol + ".tock"
        try:
            with open(tmpdir+"/delta."+datavol, "w") as f:
                cmd = ["thin_delta -m"
                    + " --thin1 " + lv_vols[snap1vol].thin_id
                    + " --thin2 " + lv_vols[snap2vol].thin_id
                    + " /dev/mapper/"+vgname+"-"+poolname+"_tmeta"
                    + " | grep -v '<same .*\/>$'"
                    ]
                subprocess.check_call(cmd, shell=True, stdout=f)
        except:
            td_err = True
    subprocess.check_call(["dmsetup","message", vgname+"-"+poolname+"-tpool",
        "0", "release_metadata_snap"] )
    if td_err:
        print("ERROR running thin_delta process!")
        exit(1)


# The critical focus of sparsebak: Translates raw lvm delta information
# into a bitmap (actually chunk map) that repeatedly accumulates change status
# for volume block ranges until a send command is successfully performed and
# the mapfile is reinitialzed with zeros.

def update_delta_digest(datavol):

    if datavol in newvols:
        return False, False

    print("Updating block change map: ", end="")
    os.rename(mapfile, mapfile+"-tmp")
    dtree = xml.etree.ElementTree.parse(tmpdir+"/delta."+datavol).getroot()
    dblocksize = int(dtree.get("data_block_size"))
    #if dblocksize % lvm_block_factor != 0:
    #    print("bkchunksize =", bkchunksize)
    #    print("dblocksize  =", dblocksize)
    #    print("bs          =", bs)
    #    raise ValueError("dblocksize error")

    bmap_byte = 0
    lastindex = 0
    dnewblocks = 0
    dfreedblocks = 0

    with open(mapfile+"-tmp", "r+b") as bmapf:
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

            # blockpos iterates over disk blocks, with
            # thin LVM tools constant of 512 bytes/block.
            # dblocksize (source) and and bkchunksize (dest) may be
            # somewhat independant of each other.
            for blockpos in range(blockbegin, blockbegin + blocklen):
                volsegment = blockpos // (bkchunksize // bs)
                bmap_pos = volsegment // 8
                if bmap_pos != lastindex:
                    bmap_mm[lastindex] |= bmap_byte
                    bmap_byte = 0
                bmap_byte |= 2** (volsegment % 8)
                lastindex = bmap_pos

        bmap_mm[lastindex] |= bmap_byte

    if dnewblocks+dfreedblocks > 0:
        print(dnewblocks * bs, "changed,",
              dfreedblocks * bs, "discarded.")
    else:
        print("No changes.")

    return True, dnewblocks+dfreedblocks > 0


def last_chunk_addr(volsize, chunksize):
    return (volsize-1) - ((volsize-1) % chunksize)


def get_sessions(datavol):
    a = sorted(list(aset.vols[datavol].sessions.keys()))
    return a


# Send volume to destination:

def send_volume(datavol):
    if not os.path.exists(bkdir+"/"+datavol):
        os.makedirs(bkdir+"/"+datavol)
    sessions = get_sessions(datavol)
    send_all = len(sessions) == 0

    # Make new session folder
    sdir=bkdir+"/"+datavol+"/"+bksession
    os.makedirs(sdir+"-tmp")
    zeros = bytes(bkchunksize)
    count = bcount = zcount = 0
    thetime = time.time()
    addrsplit = -address_split[1]
    if send_all:
        # sends all from this address forward
        sendall_addr = 0
    else:
        # beyond range; send all is off
        sendall_addr = snap2size + 1

    # Check volume size vs prior backup session
    if len(sessions) > 0 and not send_all:
        prior_size = get_info_vol_size(datavol)
        next_chunk_addr = last_chunk_addr(prior_size, bkchunksize) + bkchunksize
        if prior_size > snap2size:
            print("  Volume size has shrunk.")
        elif snap2size-1 >= next_chunk_addr:
            print("  Volume size has increased.")
            sendall_addr = next_chunk_addr

    # Use tar to stream files to destination
    stream_started = False
    if options.tarfile:
        # don't untar at destination
        untar_cmd = [ destcd
                    +" && mkdir -p ."+sdir+"-tmp"
                    +" && cat >."+pjoin(sdir+"-tmp",bksession+".tar")]
    else:
        untar_cmd = [ destcd + " && tar -xmf -"]

    # Open source volume and its delta bitmap as r, session manifest as w.
    with open(pjoin("/dev",vgname,snap2vol),"rb") as vf:
        with open("/dev/zero" if send_all else mapfile+"-tmp","r+b") as bmapf:
            bmap_mm = bytes(1) if send_all else mmap.mmap(bmapf.fileno(), 0)
            with open(sdir+"-tmp/manifest", "w") as hashf:

                # Cycle over range of addresses in volume.
                checkpt = checkpt_pct = 200 if options.unattended else 1
                percent = 0; status = ""
                for addr in range(0, snap2size, bkchunksize):

                    # Calculate corresponding position in bitmap.
                    bmap_pos = addr // bkchunksize // 8
                    b = (addr // bkchunksize) % 8

                    # Should this chunk be sent?
                    if addr >= sendall_addr or bmap_mm[bmap_pos] & (2** b):
                        count += 1
                        vf.seek(addr)
                        buf = vf.read(bkchunksize)
                        destfile = "x"+format(addr,"016x")

                        percent = int(bmap_pos/bmap_size*1000)
                        status = "  %.1f%%  %dMB  %s " \
                            % (percent/10, bcount//1000000, destfile) \
                            if percent >= checkpt else ""

                        # Compress & write only non-empty and last chunks
                        if buf != zeros or addr >= snap2size-bkchunksize:
                            # Performance fix: move compression into separate processes
                            buf = gzip.compress(buf, compresslevel=4)
                            bcount += len(buf)
                            print(hashlib.sha256(buf).hexdigest(), destfile,
                                  file=hashf)
                        else: # record zero-length file
                            buf = bytes(0)
                            print(0, destfile, file=hashf)
                            zcount += 1

                        if status:
                            print(status, end="\x0d")
                            checkpt += checkpt_pct

                        # Start tar stream
                        if not stream_started:
                            print("Sending to", (vmtype+"://"+destvm) if \
                                destvm != "internal:" else destmountpoint)
                            cmd = " ".join(dest_run_args(vmtype, untar_cmd))
                            untar = subprocess.Popen(cmd,
                                    stdin=subprocess.PIPE,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                    shell=True)
                            tarf = tarfile.open(mode="w|", fileobj=untar.stdin)
                            stream_started = True

                        # Add buffer to stream
                        tar_info = tarfile.TarInfo(sdir+"-tmp/"+destfile[1:addrsplit]
                                                       +"/"+destfile)
                        tar_info.size = len(buf)
                        tarf.addfile(tarinfo=tar_info, fileobj=io.BytesIO(buf))


    # Send session info, end stream and cleanup
    if count > 0:
        print("  100%  ")

        # Make info file and send with hashes
        with open(sdir+"-tmp/info", "w") as f:
            print("localtime =", localtime, file=f)
            print("volsize =", snap2size, file=f)
            print("chunksize =", bkchunksize, file=f)
            print("chunks =", count, file=f)
            print("bytes =", bcount, file=f)
            print("zeros =", zcount, file=f)
            print("format =", "tar" if options.tarfile else "folders", file=f)
            print("previous =", "none" if send_all else sessions[-1], file=f)
        tarf.add(sdir+"-tmp/info")
        tarf.add(sdir+"-tmp/manifest")
        if os.path.exists(mapfile+"-tmp"):
            with open(mapfile+"-tmp", "rb") as f_in:
                with gzip.open(sdir+"-tmp/deltamap.gz", "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            tarf.add(sdir+"-tmp/deltamap.gz")

        #print("Ending tar process ", end="")
        tarf.close()
        untar.stdin.close()
        for i in range(10):
            if untar.poll() != None:
                break
            time.sleep(1)
        if untar.poll() == None:
            time.sleep(5)
            if untar.poll() == None:
                untar.terminate()
                print("terminated untar process!")
                # fix: verify archive dir contents here

        # Cleanup on VM/remote
        dest_run([ destcd
            +" && mv '."+sdir+"-tmp' '."+sdir+"'"
            +" && sync"])
        os.rename(sdir+"-tmp", sdir)
    else:
        shutil.rmtree(sdir+"-tmp")

    print(" ", bcount, "bytes sent.")
    return count > 0


# Controls flow of monitor and send_volume procedures:

def monitor_send(volumes=[], monitor_only=True):
    global datavols, newvols, volgroups, lv_vols
    global bmap_size, snap1size, snap2size, snap1vol, snap2vol
    global map_exists, map_updated, mapfile, bksession, localtime

    localtime = time.strftime("%Y%m%d-%H%M%S")
    bksession = "S_"+localtime

    datavols, newvols \
        = prepare_snapshots(volumes if len(volumes) >0 else datavols)

    volgroups = get_lvm_vgs()
    if vgname not in volgroups.keys():
        raise ValueError("Volume group "+vgname+" not present.")
    lv_vols = volgroups[vgname].lvs

    if monitor_only:
        newvols = []
        volumes = []
    else:
        print("\nStarting backup session", bksession)

    if len(datavols)+len(newvols) == 0:
        print("No new data.")
        exit(0)

    if len(datavols) > 0:
        get_lvm_deltas(datavols)

    for datavol in datavols+newvols:
        print("\nProcessing Volume :", datavol)
        snap1vol = datavol + ".tick"
        snap2vol = datavol + ".tock"
        snap1size = get_lvm_size(pjoin("/dev",vgname,snap1vol))
        snap2size = get_lvm_size(pjoin("/dev",vgname,snap2vol))
        bmap_size = (snap2size // bkchunksize // 8) + 1

        mapfile = pjoin(bkdir,datavol,"deltamap")
        map_exists, map_updated \
        = update_delta_digest(datavol)

        if not monitor_only:
            sent \
            = send_volume(datavol)
            finalize_bk_session(datavol, sent)
        else:
            finalize_monitor_session(datavol, map_updated)


def init_deltamap(bmfile, bmsize):
    if os.path.exists(bmfile):
        os.remove(bmfile)
    if os.path.exists(bmfile+"-tmp"):
        os.remove(bmfile+"-tmp")
    with open(bmfile, "wb") as bmapf:
        os.ftruncate(bmapf.fileno(), bmsize)


def rotate_snapshots(datavol, rotate=True):
    if rotate:
        print("Rotating snapshots for", datavol)
        # Review: this should be atomic
        p = subprocess.check_output(["lvremove","--force", vgname+"/"+snap1vol])
        p = subprocess.check_output(["lvrename",vgname+"/"+snap2vol, snap1vol])
    else:
        p = subprocess.check_output(["lvremove","--force",vgname+"/"+snap2vol])


def finalize_monitor_session(datavol, map_updated):
    rotate_snapshots(datavol, rotate=map_updated)
    os.rename(mapfile+"-tmp", mapfile)
    os.sync()


def finalize_bk_session(datavol, sent):
    rotate_snapshots(datavol, rotate=sent)
    init_deltamap(mapfile, bmap_size)
    os.sync()


# Prune backup sessions from an archive. Basis is a non-overwriting dir tree
# merge starting with newest dirs and working backwards. Target of merge is
# timewise the next session dir after the pruned dirs.
# Specify data volume and one or two member list with start [end] date-time
# in YYYYMMDD-HHMMSS format.

def prune_sessions(datavol, times):
    global destmountpoint, destdir, bkdir

    print("\nPruning Volume :", datavol)
    # Validate date-time params
    for dt in times:
        datetime.datetime.strptime(dt, "%Y%m%d-%H%M%S")

    # t1 alone should be a specific session date-time,
    # t1 and t2 together are a date-time range.
    t1 = "S_"+times[0].strip()
    if len(times) > 1:
        t2 = "S_"+times[1].strip()
    else:
        t2 = ""
    sessions = get_sessions(datavol)

    if len(sessions) < 2:
        print("No extra sessions to prune.")
        return
    if t1 == sessions[-1] or t2 >= sessions[-1]:
        print("Cannot prune most recent session; Skipping.")
        return
    if t2 != "" and t2 <= t1:
        print("Error: second date-time must be later than first.")
        exit(1)

    # Find specific sessions to prune
    to_prune = []
    if t2 == "":
        if t1 in sessions:
            to_prune.append(t1)
    else:
        for ses in sessions:
            if t1 <= ses <= t2:
                to_prune.append(ses)

    if len(to_prune) == 0:
        print("No sessions in this date-time range.")
        return

    # Determine target session where data will be merged.
    target_s = sessions[sessions.index(to_prune[-1]) + 1]

    merge_sessions(datavol, to_prune, target_s, clear_target=False,
                   clear_sources=True)


# Merge sessions together. Starting from first session results in a target
# that contains an updated, complete volume. Other starting points can
# form the basis for a pruning operation.
# Specify the data volume (datavol), source sessions (sources), and
# target dir (can be empty or session dir). Caution: clear_target and
# clear_sources are destructive.

def merge_sessions(datavol, sources, target, clear_target=False,
                   clear_sources=False):
    global destmountpoint, destdir, bkdir

    for ses in sources + [target]:
        if aset.vols[datavol].sessions[ses].format == "tar":
            print("Cannot merge range containing tarfile session.")
            exit(1)

    # Get volume size
    volsize = get_info_vol_size(datavol, target if not clear_target \
                                         else sources[-1])
    last_chunk = "x"+format(last_chunk_addr(volsize,bkchunksize), "016x")

    # Prepare merging of manifests (starting with target session).
    if clear_target:
        open(pjoin(tmpdir,"manifest.tmp"), "wb").close()
        cmd = ["cd '"+pjoin(destmountpoint,destdir,bkdir.strip("/"),datavol)
              +"' && rm -rf "+target+" && mkdir -p "+target
            ]
        dest_run(cmd)
    else:
        shutil.copy(pjoin(bkdir,datavol,target,"manifest"),
                    tmpdir+"/manifest.tmp")

    # Merge each session to be pruned into the target.
    for ses in reversed(sorted(sources)):
        print("  Merging session", ses, "into", target)
        cmd = ["cd '"+pjoin(bkdir,datavol)
            +"' && cat "+ses+"/manifest"+" >>"+tmpdir+"/manifest.tmp"
            ]
        p = subprocess.check_output(cmd, shell=True)

        cmd = ["cd '"+pjoin(destmountpoint,destdir,bkdir.strip("/"),datavol)
              +"' && cp -rlnT "+ses+" "+target
              ]
        dest_run(cmd)

    # Reconcile merged manifest info with sort unique. The reverse date-time
    # ordering in above merge will result in only the newest instance of each
    # filename being retained. Then filter entries beyond current last chunk
    # and send to the archive.
    print("  Merging manifests")
    cmd = ["cd '"+pjoin(bkdir,datavol)
        +"' && sort -u -d -k 2,2 "+tmpdir+"/manifest.tmp"
        +"  |  sed '/ "+last_chunk+"/q' >"+pjoin(target,"manifest")
        +"  && tar -cf - "+pjoin(target,"manifest")
        +"  | "+" ".join(dest_run_args(vmtype,
            ["cd "+'"'+pjoin(destmountpoint,destdir,bkdir.strip("/"),datavol)
            +'" && tar -xmf -'])
        )]

    p = subprocess.check_output(cmd, shell=True)

    # Trim chunks to volume size and remove pruned sessions.
    print("  Trimming volume...", end="")
    cmd = ["cd '"+pjoin(destmountpoint,destdir,bkdir.strip("/"),datavol)
        +"' && find "+target+" -name 'x*' | sort -d"
        +"  |  sed '1,/"+last_chunk+"/d'"
        +"  |  xargs -r rm"
        ]
    p = subprocess.check_call(" ".join(dest_run_args(vmtype, cmd)), shell=True)

    # Remove pruned sessions
    for ses in sources:
        print("..", end="")
        cmd = ["cd '"+pjoin(bkdir,datavol)
            +"' && rm -r "+ses
            +"  && "+" ".join(dest_run_args(vmtype,
                ["cd "+'"'+pjoin(destmountpoint,destdir,bkdir.strip("/"),datavol)
                +'" && rm -r '+ses])
            )]
        p = subprocess.check_call(cmd, shell=True)
    print()


# Receive volume from archive. If no same_path specified, then verify only.
# If diff specified, compare with current source volume and record any
# differences in the volume's deltamap; can be used if the deltamap or snapshots
# are lost or if the source volume reverted to an earlier state.

def receive_volume(datavol, select_ses="", save_path="", diff=False):
    global destmountpoint, destdir, bkdir, bkchunksize, vgname

    if save_path and os.path.exists(save_path) and not options.unattended:
        print("\n!! This will erase all existing data in",save_path)
        ans = input("   Are you sure? (yes/no): ")
        if ans.lower() != "yes":
            exit(0)

    sessions = get_sessions(datavol)
    # Set the session to retrieve
    if select_ses:
        datetime.datetime.strptime(select_ses, "%Y%m%d-%H%M%S")
        select_ses = "S_"+select_ses
        if select_ses not in sessions:
            print("The specified session date-time does not exist.")
            exit(1)
    elif len(sessions) > 0:
        select_ses = sessions[-1]
    else:
        print("No sessions available.")
        exit(1)


    print("\nReading manifests")
    attended = not options.unattended
    volsize = get_info_vol_size(datavol, select_ses)
    last_chunk = "x"+format(last_chunk_addr(volsize, bkchunksize), "016x")
    zeros = bytes(bkchunksize)
    open(tmpdir+"/manifests.cat", "wb").close()

    # Collect session manifests
    for ses in reversed(sorted(sessions)):
        if ses > "S_"+select_ses:
            continue
        if aset.vols[datavol].sessions[ses].format == "tar":
            raise NotImplementedError(
                "Receive from tarfile not yet implemented: "+ses)
        # add session column to end of each line:
        cmd = ["cd '"+pjoin(bkdir,datavol)
            +"' && sed -E 's|$| "+ses+"|' "
            +pjoin(ses,"manifest")+" >>"+tmpdir+"/manifests.cat"
            ]
        p = subprocess.check_output(cmd, shell=True)

    # Merge manifests and send to archive system:
    # sed is used to expand chunk info into a path and filter out any entries
    # beyond the current last chunk, then piped to cat on destination.
    # Note address_split is used to bisect filename to construct the subdir.
    cmd = ["cd '"+pjoin(bkdir,datavol)
        +"' && sort -u -d -k 2,2 "+tmpdir+"/manifests.cat"
        +"  |  tee "+tmpdir+"/manifest.verify"
        +"  |  sed -E 's|^.+\s+x(\S{" + str(address_split[0]) + "})(\S+)\s+"
        +"(S_.+)|\\3/\\1/x\\1\\2|;"
        +" /"+last_chunk+"/q'"
        +"  | "+" ".join(dest_run_args(vmtype,
                        ["cat >"+tmpdir+"/rpc/receive.lst"])
        )]
    p = subprocess.check_output(cmd, shell=True)

    print("\nReceiving volume", datavol, select_ses)

    # Create retriever process using py program
    cmd = dest_run_args(vmtype,
            ["cd '"+pjoin(destmountpoint,destdir,bkdir.strip("/"),datavol)
            +"' && cat >"+tmpdir+"/rpc/receive_out.py"
            +"  && python3 "+tmpdir+"/rpc/receive_out.py"
            ])
    getvol = subprocess.Popen(" ".join(cmd), stdout=subprocess.PIPE,
                              stdin=subprocess.PIPE, shell=True)

    ##> START py program code <##
    getvol.stdin.write(b'''import os.path, sys
with open("''' + bytes(tmpdir,encoding="UTF-8") + b'''/rpc/receive.lst",
          "r") as list:
    for line in list:
        fname = line.strip()
        fsize = os.path.getsize(fname)
        i = sys.stdout.buffer.write(fsize.to_bytes(4,"big"))
        with open(fname,"rb") as dataf:
            i = sys.stdout.buffer.write(dataf.read(fsize))
    ''')
    ##> END py program code <##
    getvol.stdin.close() # <-program starts on destination


    # Prepare save volume
    if save_path:
        # Discard all data in destination if this is a block device
        # then open for writing
        if vg_exists(os.path.dirname(save_path)):
            lv = os.path.basename(save_path)
            vg = os.path.basename(os.path.dirname(save_path))
            if not lv_exists(vg,lv):
                # not possible to tell from path which thinpool to use
                print("Please create LV before receiving.")
                raise NotImplementedError("Automatic LV creation")
            if volsize > get_lvm_size(save_path):
                p = subprocess.check_output(["lvresize", "-L",str(volsize)+"b",
                                             "-f", save_path])
        if os.path.exists(save_path) \
        and stat.S_ISBLK(os.stat(save_path).st_mode):
            p = subprocess.check_output(["blkdiscard", save_path])
        else: # file
            p = subprocess.check_output(
                ["truncate", "-s", "0", save_path])
            p = subprocess.check_output(
                ["truncate", "-s", str(volsize), save_path])
        print("Saving to", save_path)
        savef = open(save_path, "w+b")
    elif diff:
        # Fix: check info vs lvm volume size
        if not options.unattended:
            print("\nFor diff, make sure the specified volume"
                  " is unmounted first!")
            ans = input("Continue? (yes/no): ")
            if ans.lower() != "yes":
                exit(0)
        mapfile = pjoin(bkdir, datavol, "deltamap")
        bmap_size = (volsize // bkchunksize // 8) + 1
        if not lv_exists(vgname, datavol+".tick"):
            p = subprocess.check_output(["lvcreate", "-pr", "-kn",
                "-ay", "-s", vgname+"/"+datavol, "-n", snap1vol],
                stderr=subprocess.STDOUT)
            print("  Initial snapshot created for", datavol)
        if not os.path.exists(mapfile):
            init_deltamap(mapfile, bmap_size)

        cmpf  = open(pjoin("/dev",vgname,datavol+".tick"), "rb")
        bmapf = open(mapfile, "r+b")
        os.ftruncate(bmapf.fileno(), bmap_size)
        bmap_mm = mmap.mmap(bmapf.fileno(), 0)
        cmp_count = 0

    # Open manifest then receive, check and save data
    with open(tmpdir+"/manifest.verify", "r") as mf:
        for addr in range(0, volsize, bkchunksize):
            faddr = "x"+format(addr,"016x")
            if attended:
                print(int(addr/volsize*100),"%  ",faddr,end="  ")

            cksum, fname, ses = mf.readline().strip().split()
            size = int.from_bytes(getvol.stdout.read(4),"big")

            if fname != faddr:
                raise ValueError("Bad fname "+fname)
            if cksum.strip() == "0":
                if size != 0:
                    raise ValueError("Expected zero length, got "+size)
                print("OK",end="\x0d")
                if save_path:
                    savef.seek(bkchunksize, 1)
                elif diff:
                    cmpf.seek(bkchunksize, 1)
                continue
            if size > bkchunksize + (bkchunksize // 128) or size < 1:
                raise BufferError("Bad chunk size: "+size)

            buf = getvol.stdout.read(size)
            rc  = getvol.poll()
            if rc is not None and len(buf) == 0:
                break

            if len(buf) != size:
                raise BufferError("Got "+len(buf)+" bytes, expected "+size)
            if cksum != hashlib.sha256(buf).hexdigest():
                with open(tmpdir+"/bufdump", "wb") as dump:
                    dump.write(buf)
                raise ValueError("Bad hash "+fname
                    +" :: "+hashlib.sha256(buf).hexdigest())
            if attended:
                print("OK",end="\x0d")

            if save_path:
                buf = gzip.decompress(buf)
                if len(buf) > bkchunksize:
                    raise BufferError("Decompressed to "+len(buf)+" bytes")
                savef.write(buf)
            elif diff:
                buf = gzip.decompress(buf)
                if len(buf) > bkchunksize:
                    raise BufferError("Decompressed to "+len(buf)+" bytes")
                buf2 = cmpf.read(bkchunksize)
                if buf != buf2:
                    print("* delta", faddr, "    ")
                    if options.remap:
                        volsegment = addr // bkchunksize 
                        bmap_pos = volsegment // 8
                        bmap_mm[bmap_pos] |= 2** (volsegment % 8)
                    cmp_count += len(buf)

        print("\nReceived bytes :",addr)
        if rc is not None and rc > 0:
            raise RuntimeError("Error code from getvol process: "+rc)
        if save_path:
            savef.close()
        elif diff:
            bmapf.close()
            cmpf.close()
            if options.remap:
                print("Delta bytes re-mapped:", cmp_count)
                if cmp_count > 0:
                    print("\nNext 'send' will bring this volume into sync.")




##  Main  #####################################################################

''' ToDo:
    Config management, add/recognize disabled volumes
    Check free space on destination
    Encryption
    Add support for special source metadata (qubes.xml etc)
    Add other destination exec types (e.g. ssh to vm)
    Separate threads for encoding tasks
    Option for live Qubes volumes (*-private-snap)
    Guard against vm snap rotation during receive-save
    Verify entire archive
    Deleting volumes
    Multiple storage pool configs
    Auto-pruning/rotation
    Auto-resume aborted backup session:
        Check dir/file presence, volume sizes, deltabmap size
        Example: if deltamap-tmp exists, then perform checks on
        which snapshots exist.
'''


# Constants
progversion = "0.2alphaX"
progname = "sparsebak"
topdir = "/"+progname # must be absolute path
tmpdir = "/tmp/"+progname
volgroups = {}
lv_vols = {}
bs = 512
# LVM min blocks = 128 = 64kBytes
lvm_block_factor = 128
# Dest chunk size = 128kBytes
bkchunksize = 2 * lvm_block_factor * bs
assert bkchunksize % (lvm_block_factor * bs) == 0
max_address = 0xffffffffffffffff # 64bits
# for 64bits, a subdir split of 9+7 allows 2048 files per dir
address_split = [len(hex(max_address))-2-7, 7]


# Root user required
if os.getuid() > 0:
    print("sparsebak must be run as root/sudo user.")
    exit(1)

# Allow only one instance at a time
lockpath = "/var/lock/"+progname
try:
    lockf = open(lockpath, "w")
    fcntl.lockf(lockf, fcntl.LOCK_EX|fcntl.LOCK_NB)
except IOError:
    print("ERROR: sparsebak is already running.")
    exit(1)

# Create our tmp dir
shutil.rmtree(tmpdir+"-old", ignore_errors=True)
if os.path.exists(tmpdir):
    os.rename(tmpdir, tmpdir+"-old")
os.makedirs(tmpdir)


# Parse arguments
parser = argparse.ArgumentParser(description="")
parser.add_argument("action", choices=["send","monitor","purge-metadata",
                    "prune","receive","verify","diff","list","version"],
                    default="monitor", help="Action to take")
parser.add_argument("-u", "--unattended", action="store_true", default=False,
                    help="Non-interactive, supress prompts")
parser.add_argument("-a", "--all", action="store_true", default=False,
                    help="Apply action to all volumes")
parser.add_argument("--tarfile", action="store_true", dest="tarfile", default=False,
                    help="Store backup session as a tarfile")
parser.add_argument("--session",
                    help="YYYYMMDD-HHMMSS[,YYYYMMDD-HHMMSS] select session date(s), singular or range.")
parser.add_argument("--save-to", dest="saveto", default="",
                    help="Path to store volume for receive")
parser.add_argument("--remap", action="store_true", default=False,
                    help="Remap volume during diff")
parser.add_argument("volumes", nargs="*")
options = parser.parse_args()
#subparser = parser.add_subparsers(help="sub-command help")
#prs_prune = subparser.add_parser("prune",help="prune help")


# General configuration

monitor_only = options.action == "monitor" # gather metadata without backing up

conf = None
vgname, poolname, destvm, destmountpoint, destdir, datavols \
= get_configs()
destcd = " cd '"+destmountpoint+"/"+destdir+"'"

bkdir = topdir+"/"+vgname+"%"+poolname
if not os.path.exists(bkdir):
    os.makedirs(bkdir)

vmtype = detect_internal_state()

vm_run_args = {"internal":["sh"],
                "ssh":["ssh",destvm],
                "qubes":["qvm-run", "-p", destvm],
                "qubes-ssh":["qvm-run", "-p", destvm.split("|")[0]]
                }

detect_dest_state(destvm)

# Check volume args against config
for vol in options.volumes:
    if vol not in datavols:
        raise ValueError("Volume "+vol+" not configured.")


# Process commands
print()
if options.action == "monitor":
    monitor_send(datavols, monitor_only=True)

elif options.action   == "send":
    monitor_send(options.volumes, monitor_only=False)

else:
    # get lvs for funcs that don't create snapshots...
    volgroups = get_lvm_vgs()
    if vgname not in volgroups.keys():
        raise ValueError("Volume group "+vgname+" not present.")
    lv_vols = volgroups[vgname].lvs


if options.action == "version":
    print(progname, "version", progversion)

elif options.action == "prune":
    if not options.session:
        raise ValueError("Must specify --session for prune")
    dvs = datavols if len(options.volumes) == 0 else options.volumes
    for dv in dvs:
        if dv in datavols:
            prune_sessions(dv, options.session.split(","))

elif options.action == "receive":
    if not options.saveto:
        raise ValueError("Must specify --save-to for receive.")
    if len(options.volumes) != 1:
        raise ValueError("Specify one volume for receive")
    if options.session and len(options.session.split(",")) > 1:
        raise ValueError("Specify one session for receive")
    receive_volume(options.volumes[0],
                   select_ses="" if not options.session \
                   else options.session.split(",")[0],
                   save_path=options.saveto)

elif options.action == "verify":
    if len(options.volumes) != 1:
        raise ValueError("Specify one volume for verify")
    if options.session and len(options.session.split(",")) > 1:
        raise ValueError("Specify one session for verify")
    receive_volume(options.volumes[0],
                   select_ses="" if not options.session \
                   else options.session.split(",")[0],
                   save_path="")

elif options.action == "diff":
    receive_volume(options.volumes[0], save_path="", diff=True)

elif options.action == "list":
    for dv in options.volumes:
        print("\nSessions for volume",dv,":")
        sessions = get_sessions(dv)
        for ses in sessions:
            print(" ",ses[2:]+(" (tar)"
                    if aset.vols[dv].sessions[ses].format == "tar"
                    else ""))

elif options.action == "purge-metadata":
    if options.unattended:
        raise RuntimeError("Purge cannot be used with --unattended.")
    print("Warning: This removes all sparsebak-generated snapshots and metadata for:")
    print(", ".join(options.volumes))
    print()
    
    ans = input("Are you sure (y/N)? ")
    if ans.lower() not in ["y","yes"]:
        exit(0)
    print("Purging")
    for dv in options.volumes:
        for ext in [".tick",".tock"]:
            if lv_exists(vgname, dv+ext):
                p = subprocess.check_output(["lvremove",
                                             "-f",vgname+"/"+dv+ext])
                print("Removed", vgname+"/"+dv+ext)
        shutil.rmtree(pjoin(bkdir,dv))

elif options.action == "delete":
    raise NotImplementedError()

elif options.action == "untar":
    raise NotImplementedError()


print("\nDone.\n")
