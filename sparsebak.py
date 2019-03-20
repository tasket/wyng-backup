#!/usr/bin/python3


###  sparsebak
###  Copyright Christopher Laprise 2018-2019 / tasket@github.com
###  Licensed under GNU General Public License v3. See file 'LICENSE'.


import sys, os, stat, shutil, subprocess, time, datetime
import re, mmap, gzip, tarfile, io, fcntl, tempfile
import xml.etree.ElementTree
import argparse, configparser, hashlib, uuid


# ArchiveSet manages configuration and configured volume info

class ArchiveSet:
    def __init__(self, name, top, conf_file):
        self.name = name
        self.confpath = pjoin(top,conf_file)

        cp = configparser.ConfigParser()
        cp.optionxform = lambda option: option
        cp.read(self.confpath)
        c = cp["var"]
        self.conf = cp

        self.vgname = c['vgname']
        self.poolname = c['poolname']
        self.path = pjoin(top,self.vgname+"%"+self.poolname)
        self.destvm = c['destvm']
        self.destmountpoint = c['destmountpoint']
        self.destdir = c['destdir']

        self.vols = {}
        for key in cp["volumes"]:
            if cp["volumes"][key] != "disable" \
            and (len(options.volumes)==0 or key in options.volumes):
                os.makedirs(pjoin(self.path,key), exist_ok=True)
                self.vols[key] = self.Volume(key, pjoin(self.path,key),
                                             self.vgname)
                self.vols[key].enabled = True

        #fs_vols = [e.name for e in os.scandir(self.path) if e.is_dir()
        #           and e.name not in self.vols.keys()]
        #for key in fs_vols:
        #    self.vols[key] = self.Volume(key, self.path)

    def add_volume(self, datavol):
        if datavol in self.conf["volumes"].keys():
            x_it(1, datavol+" is already configured.")

        volname_check = re.compile("^[a-zA-Z0-9\+\._-]+$")
        if volname_check.match(datavol) == None:
            x_it(1, "Only characters A-Z 0-9 . + _ - are allowed"
                " in volume names.")

        if len(datavol) > 112:
            x_it(1, "Volume name must be 112 characters or less.")

        #self.vols[datavol] = self.Volume(datavol, pjoin(self.path,datavol),
        #                                 self.vgname)

        self.conf["volumes"][datavol] = "enable"
        with open(self.confpath, "w") as f:
            self.conf.write(f)

    def delete_volume(self, datavol):
        if datavol in self.conf["volumes"].keys():
            del(self.conf["volumes"][datavol])
            with open(self.confpath, "w") as f:
                self.conf.write(f)

        for ext in {".tick",".tock"}:
            if lv_exists(vgname, datavol+ext):
                p = subprocess.check_output(["lvremove",
                                                "-f",vgname+"/"+datavol+ext])
                print("Removed snapshot", vgname+"/"+datavol+ext)

        if os.path.exists(pjoin(self.path,datavol)):
            shutil.rmtree(pjoin(self.path,datavol))


    class Volume:
        def __init__(self, name, path, vgname):
            self.name = name
            self.path = path
            self.vgname = vgname
            self.present = lv_exists(vgname, name)
            self.enabled = False
            self.error = False
            self.volsize = None
            self.chunksize = bkchunksize
            # persisted:
            self.format_ver = "0"
            self.uuid = None
            self.first = None
            self.last = None
            self.que_meta_update = "false"

            # load volume info
            if os.path.exists(pjoin(path,"volinfo")):
                with open(pjoin(path,"volinfo"), "r") as f:
                    for ln in f:
                        vname, value = ln.strip().split(" = ")
                        setattr(self, vname, value)

            # load sessions
            self.sessions ={e.name: self.Ses(e.name,pjoin(path,e.name)) \
                for e in os.scandir(path) if e.name[:2]=="S_" \
                    and e.name[-3:]!="tmp"} if self.present else {}

            # Convert metadata fron alpha to v1:
            # move map to new location
            no_manifest = [ses.name for ses in self.sessions.values()
                           if not ses.present]
            if len(no_manifest):
                print("** WARNING: Some manifests do not exist for", name,
                      "\n(Alpha format?)")
            mapfile = pjoin(path, "deltamap")
            if os.path.exists(path+".deltamap"):
                os.rename(path+".deltamap", mapfile)
            self.mapped = os.path.exists(mapfile)

            if int(self.format_ver) < format_version and len(self.sessions)>0:
                sesnames = sorted(list(self.sessions.keys()))
                for i in range(0,len(sesnames)):
                    s = self.sessions[sesnames[i]]
                    if s.format not in {"folders","tar"}:
                        s.format = "folders"
                    s.previous = "none" if i==0 else sesnames[i-1]
                    s.sequence = i
                    s.save_info()
                self.first = sesnames[0]
                self.last = sesnames[-1]
                self.format_ver = str(format_version)
                self.que_meta_update = "true"
                self.save_volinfo()

            if int(self.format_ver) > format_version:
                raise ValueError("Archive format ver = "+self.format_ver+
                                 ". Expected = "+format_version)

            # use last known chunk size
            if len(self.sessions):
                self.chunksize = self.sessions[self.last].chunksize

            # build ordered, linked list of names
            sesnames = []
            sname = self.last
            for i in range(len(self.sessions)):
                sesnames.insert(0, sname)
                if sname == "none":
                    break
                sname = self.sessions[sname].previous
            self.sesnames = sesnames

            # check for continuity between sessions
            for sname, s in self.sessions.items():
                if s.previous == "none" and self.first != sname:
                    print("**** PREVIOUS MISMATCH",sname, self.first)
                elif s.previous not in sesnames+["none"]:
                    print("**** PREVIOUS NOT FOUND",sname, s.previous)

            # use latest volsize
            self.volsize = self.sessions[self.last].volsize \
                            if self.sessions else 0

        def save_volinfo(self, fname="volinfo"):
            with open(pjoin(self.path,fname), "w") as f:
                print("format_ver =", format_version, file=f)
                print("uuid =", self.uuid if self.uuid else str(uuid.uuid4()),
                      file=f)
                print("first =", self.first, file=f)
                print("last =", self.last, file=f)
                print("que_meta_update =", self.que_meta_update, file=f)

        def new_session(self, sname):
            ns = self.Ses(sname)
            ns.path = pjoin(self.path, sname)
            if self.first is None:
                ns.sequence = 0
                self.first = sname
            else:
                ns.previous = self.last
                ns.sequence = self.sessions[self.last].sequence + 1

            self.last = sname
            self.sesnames.append(sname)
            self.sessions[sname] = ns
            return ns

        def delete_session(self, ses):
            if ses == self.last:
                raise NotImplementedError("Cannot delete last session")
            index = self.sesnames.index(ses)
            affected = self.sesnames[index+1]
            self.sessions[affected].previous \
                = self.sessions[ses].previous
            if index == 0:
                self.first = self.sesnames[1]
            del self.sesnames[index]
            del self.sessions[ses]
            shutil.rmtree(pjoin(self.path, ses))
            return affected


        class Ses:
            def __init__(self, name, path=""):
                self.name = name
                self.path = path
                self.present = os.path.exists(pjoin(path,"manifest"))
                # persisted:
                self.localtime = None
                self.volsize = None
                self.chunksize = None
                self.format = None
                self.sequence = None
                self.previous = "none"
                attr_str = {"localtime","format","previous"}
                attr_int = {"volsize","chunksize","sequence"}

                if path:
                    with open(pjoin(path,"info"), "r") as sf:
                        for ln in sf:
                            vname, value = ln.strip().split(" = ")
                            setattr(self, vname, 
                                int(value) if vname in attr_int else value)
                    if self.localtime is None or self.localtime == "None":
                        self.localtime = self.name[2:]

            def save_info(self):
                if not self.path:
                    raise ValueError("Path not set for save_info")
                with open(pjoin(self.path,"info"), "w") as f:
                    print("localtime =", self.localtime, file=f)
                    print("volsize =", self.volsize, file=f)
                    print("chunksize =", self.chunksize, file=f)
                    print("format =", self.format, file=f)
                    print("sequence =", self.sequence, file=f)
                    print("previous =", self.previous, file=f)


class Lvm_VolGroup:
    def __init__(self, name):
        self.name = name
        self.lvs = {}

class Lvm_Volume:
    colnames = ["vg_name","lv_name","lv_attr","lv_size","lv_time",
                "pool_lv","thin_id","lv_path"]
    attr_ints = ["lv_size"]

    def __init__(self, members):
        for attr in self.colnames:
            val = members[self.colnames.index(attr)]
            setattr(self, attr, int(re.sub("[^0-9]", "", val)) if attr \
                in self.attr_ints else val)


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

    aset = ArchiveSet("", topdir, prog_name+".ini")
    dvs = []

    for vn,v in aset.vols.items():
        if v.enabled:
            dvs.append(v.name)

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

    for prg in {"thin_delta","lvs","lvdisplay","lvcreate","blkdiscard",
                "truncate","ssh" if vmtype=="ssh" else "sh"}:
        if not shutil.which(prg):
            raise RuntimeError("Required command not found: "+prg)

    p = subprocess.check_output(["thin_delta", "-V"])
    ver = p[:5].decode("UTF-8").strip()
    target_ver = "0.7.4"
    if ver < target_ver:
        print("Note: Thin provisioning tools version", target_ver,
              "or later is recommended for stabilty."
              " Installed version =", ver+".")


    #####>  Begin helper program  <#####

    dest_program = \
    '''import os, sys, shutil
cmd = sys.argv[1]
with open("''' + tmpdir + '''/rpc/dest.lst", "r") as lstf:
    if cmd == "receive":
        for line in lstf:
            fname = line.strip()
            fsize = os.path.getsize(fname)
            i = sys.stdout.buffer.write(fsize.to_bytes(4,"big"))
            with open(fname,"rb") as dataf:
                i = sys.stdout.buffer.write(dataf.read(fsize))
    elif cmd == "merge":
        merge_target, target = lstf.readline().strip().split()
        src_list = []
        while True:
            ln = lstf.readline().strip()
            if ln == "###":
                break
            src_list.append(ln)
        subdirs = set()
        for src in src_list:
            for i in os.scandir(src):
                if i.is_dir():
                    subdirs.add(i.name)
        for sdir in subdirs:
            os.makedirs(merge_target+"/"+sdir, exist_ok=True)
        for line in lstf:
            first, source, dest = line.strip().split()
            os.replace(source, dest)
        for dir in src_list:
            shutil.rmtree(dir)
        os.replace(merge_target, target)
    '''
    with open(tmpdir +"/rpc/dest_helper.py", "wb") as progf:
        progf.write(bytes(dest_program, encoding="UTF=8"))

    #####>  End helper program  <#####

    return vmtype


def detect_dest_state(destvm):

    if options.action not in {"monitor","list","version"} \
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
            cmd = ["mountpoint -q '"+destmountpoint
                  +"' && mkdir -p '"+destmountpoint+"/"+destdir+topdir
                  +"' && cd '"+destmountpoint+"/"+destdir+topdir
                  +"' && touch archive.dat"
                  ##+"  && ln -f archive.dat .hardlink"
                  ]

            p = subprocess.check_call(
                " ".join(dest_run_args(vmtype, cmd)), shell=True)

            # send helper program to remote
            if vmtype != "internal":
                cmd = ["rm -rf "+tmpdir
                    +"  && mkdir -p "+tmpdir+"/rpc"
                    +"  && cat >"+tmpdir +"/rpc/dest_helper.py"
                    ]
                p = subprocess.check_call(" ".join(
                    ["cat " + tmpdir +"/rpc/dest_helper.py | "]
                    + dest_run_args(vmtype, cmd)), shell=True)
        except:
            x_it(1, "Destination not ready to receive commands.")


# Run system commands on destination

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
        tmpf.write(bytes("set -e\n"+" ".join(commands) + "\n",
                        encoding="UTF-8"))
        remotetmp = os.path.basename(tmpf.name)

    if dest_type in {"qubes","qubes-ssh"}:

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


# Prepare snapshots and check consistency with metadata.
# Must run get_lvm_vgs() again after this.

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
        vol = aset.vols[datavol]
        sessions = vol.sesnames
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
                volgroups[vgname].lvs[snap1vol] = "placeholder"
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
    return vgname in volgroups.keys() \
            and lvname in volgroups[vgname].lvs.keys()


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


# Get raw lvm deltas between snapshots

def get_lvm_deltas(datavols):
    print("  Acquiring LVM deltas.")
    subprocess.call(["dmsetup","message", vgname+"-"+poolname+"-tpool",
        "0", "release_metadata_snap"], stderr=subprocess.DEVNULL)
    subprocess.check_call(["dmsetup", "message", vgname+"-"+poolname+"-tpool",
        "0", "reserve_metadata_snap"])
    td_err = []
    for datavol in datavols:
        snap1vol = datavol + ".tick"
        snap2vol = datavol + ".tock"
        try:
            with open(tmpdir+"/delta."+datavol, "w") as f:
                cmd = ["export LC_ALL=C"
                    + " && thin_delta -m"
                    + " --thin1 " + l_vols[snap1vol].thin_id
                    + " --thin2 " + l_vols[snap2vol].thin_id
                    + " /dev/mapper/"+vgname+"-"+poolname+"_tmeta"
                    + " | grep -v '<same .*\/>$'"
                    ]
                subprocess.check_call(cmd, shell=True, stdout=f)
        except:
            td_err.append(datavol)
    subprocess.check_call(["dmsetup","message", vgname+"-"+poolname+"-tpool",
        "0", "release_metadata_snap"] )
    if td_err:
        x_it(1, "ERROR running thin_delta process for "+str(td_err))


# update_delta_digest: Translates raw lvm delta information
# into a bitmap (actually chunk map) that repeatedly accumulates change status
# for volume block ranges until a send command is successfully performed and
# the mapfile is reinitialzed with zeros.

def update_delta_digest(datavol):

    if datavol in newvols:
        return False, False

    if monitor_only:
        print("Updating block change map. ", end="")

    vol = aset.vols[datavol]
    bkchunksize = vol.chunksize
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
            if delta.tag in {"different", "right_only"}:
                dnewblocks += blocklen
            elif delta.tag == "left_only":
                dfreedblocks += blocklen
            else: # superfluous tag
                continue

            # blockpos iterates over disk blocks, with
            # thin LVM tools constant of 512 bytes/block.
            # dblocksize (source) and and chunksize (dest) may be
            # somewhat independant of each other.
            for blockpos in range(blockbegin, blockbegin + blocklen):
                volsegment = blockpos // (bkchunksize // bs)
                bmap_pos = volsegment // 8
                if bmap_pos != lastindex:
                    bmap_mm[lastindex] |= bmap_byte
                    bmap_byte = 0
                bmap_byte |= 1 << (volsegment % 8)
                lastindex = bmap_pos

        bmap_mm[lastindex] |= bmap_byte

    if monitor_only and dnewblocks+dfreedblocks > 0:
        print(dnewblocks * bs, "changed,",
              dfreedblocks * bs, "discarded.")
    elif monitor_only:
        print("No changes.")

    return True, dnewblocks+dfreedblocks > 0


def last_chunk_addr(volsize, chunksize):
    return (volsize-1) - ((volsize-1) % chunksize)


# Send volume to destination:

def send_volume(datavol):
    vol = aset.vols[datavol]
    sessions = vol.sesnames
    sdir = vol.path+"/"+bksession
    send_all = len(sessions) == 0
    bkchunksize = vol.chunksize

    # Make new session folder
    if not os.path.exists(sdir+"-tmp"):
        os.makedirs(sdir+"-tmp")

    zeros = bytes(bkchunksize)
    empty = bytes(0)
    bcount = 0
    addrsplit = -address_split[1]
    lchunk_addr = last_chunk_addr(snap2size, bkchunksize)

    if send_all:
        # sends all from this address forward
        sendall_addr = 0
    else:
        # beyond range; send all is off
        sendall_addr = snap2size + 1

    # Check volume size vs prior backup session
    if len(sessions) > 0 and not send_all:
        prior_size = vol.volsize
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
    with open(pjoin("/dev",vgname,snap2vol),"rb") as vf, \
            open(sdir+"-tmp/manifest", "w") as hashf,    \
            open("/dev/zero" if send_all else mapfile+"-tmp","r+b") as bmapf:
        bmap_mm = bytes(1) if send_all else mmap.mmap(bmapf.fileno(), 0)

        # Show progress in increments determined by 1000/checkpt_pct
        # where '200' results in five updates i.e. in unattended mode.
        checkpt = checkpt_pct = 200 if options.unattended else 1
        percent = 0

        # Cycle over range of addresses in volume.
        for addr in range(0, snap2size, bkchunksize):

            # Calculate corresponding position in bitmap.
            chunk = addr // bkchunksize
            bmap_pos = chunk // 8
            b = chunk % 8

            # Send chunk if its above the send-all line
            # or its bit is on in the deltamap.
            if addr >= sendall_addr or bmap_mm[bmap_pos] & (1 << b):
                vf.seek(addr)
                buf = vf.read(bkchunksize)
                destfile = "x%016x" % addr

                # Show progress.
                percent = int(bmap_pos/bmap_size*1000)
                if percent >= checkpt:
                    print("  %.1f%%   %dMB " % (percent/10, bcount//1000000),
                          end="\x0d")
                    checkpt += checkpt_pct

                # Compress & write only non-empty and last chunks
                if buf != zeros or addr >= lchunk_addr:
                    # Performance fix: move compression into separate processes
                    buf = gzip.compress(buf, compresslevel=4)
                    bcount += len(buf)
                    print(hashlib.sha256(buf).hexdigest(), destfile,
                            file=hashf)
                else: # record zero-length file
                    buf = empty
                    print(0, destfile, file=hashf)

                # Start tar stream
                if not stream_started:
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
    if stream_started:
        print("  100%  ", ("%.1f" % (bcount/1000000)) +"MB")

        # Save session info
        ses = vol.new_session(bksession)
        ses.localtime = localtime
        ses.volsize = snap2size
        ses.chunksize = bkchunksize
        ses.format = "tar" if options.tarfile else "folders"
        ses.path = sdir+"-tmp"
        ses.save_info()
        for session in vol.sessions.values() \
                        if vol.que_meta_update == "true" else [ses]:
            tarf.add(session.path)
        vol.que_meta_update = "false"
        vol.save_volinfo("volinfo-tmp")
        tarf.add(vol.path+"/volinfo-tmp")

        #print("Ending tar process ", end="")
        tarf.close()
        untar.stdin.close()
        for i in range(30):
            if untar.poll() != None:
                break
            time.sleep(1)
        if untar.poll() == None:
            time.sleep(5)
            if untar.poll() == None:
                untar.terminate()
                print("terminated untar process!")

        # Cleanup on VM/remote
        dest_run([ destcd
            +" && mv ."+sdir+"-tmp ."+sdir
            +" && mv ."+vol.path+"/volinfo-tmp ."+vol.path+"/volinfo"
            +" && sync -f ."+vol.path+"/volinfo"])
        os.replace(sdir+"-tmp", sdir)
        os.replace(vol.path+"/volinfo-tmp", vol.path+"/volinfo")

    else:
        shutil.rmtree(sdir+"-tmp")

    if bcount == 0:
        print("  No changes.")
    return stream_started


# Controls flow of monitor and send_volume procedures:

def monitor_send(volumes=[], monitor_only=True):
    global datavols, newvols, volgroups, l_vols
    global bmap_size, snap1size, snap2size, snap1vol, snap2vol
    global map_exists, map_updated, mapfile, bksession, localtime

    localtime = time.strftime("%Y%m%d-%H%M%S")
    bksession = "S_"+localtime

    datavols, newvols \
        = prepare_snapshots(volumes if len(volumes) >0 else datavols)

    volgroups = get_lvm_vgs()
    if vgname not in volgroups.keys():
        raise ValueError("Volume group "+vgname+" not present.")
    l_vols = volgroups[vgname].lvs

    if monitor_only:
        newvols = []
        volumes = []

    if len(datavols)+len(newvols) == 0:
        x_it(0, "No new data.")

    if len(datavols) > 0:
        get_lvm_deltas(datavols)

    if not monitor_only:
        print("\nSending backup session", bksession,
              "to", (vmtype+"://"+destvm) if \
              destvm != "internal:" else destmountpoint)

    for datavol in datavols+newvols:
        print("\nVolume :", datavol)
        vol = aset.vols[datavol]
        snap1vol = datavol + ".tick"
        snap2vol = datavol + ".tock"
        snap1size = get_lvm_size(pjoin("/dev",vgname,snap1vol))
        snap2size = get_lvm_size(pjoin("/dev",vgname,snap2vol))
        bmap_size = (snap2size // vol.chunksize // 8) + 1

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
        #print("Rotating snapshots for", datavol)
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

    # Validate date-time params
    for dt in times:
        datetime.datetime.strptime(dt, "%Y%m%d-%H%M%S")

    # t1 alone should be a specific session date-time,
    # t1 and t2 together are a date-time range.
    t1 = "S_"+times[0].strip()
    if len(times) > 1:
        t2 = "S_"+times[1].strip()
        if t2 <= t1:
            x_it(1, "Error: second date-time must be later than first.")
    else:
        t2 = ""

    print("\nPruning Volume :", datavol)

    volume = aset.vols[datavol]
    sessions = volume.sesnames
    if len(sessions) < 2:
        print("  No extra sessions to prune.")
        return
    if t1 >= sessions[-1] or t2 >= sessions[-1]:
        print("  Cannot prune most recent session; Skipping.")
        return

    # Find specific sessions to prune;
    # Use contiguous ranges.
    to_prune = []
    if options.allbefore:
        for ses in sessions:
            if ses >= t1:
                break
            to_prune.append(ses)

    elif t2 == "":
        if t1 in sessions:
            to_prune.append(t1)

    else:
        if t1 in sessions:
            start = sessions.index(t1)
        else:
            for ses in sessions:
                if ses > t1:
                    start = sessions.index(ses)
                    break
        end = 0
        if t2 in sessions:
            end = sessions.index(t2)+1
        else:
            for ses in reversed(sessions):
                if ses < t2:
                    end = sessions.index(ses)+1
                    break
        to_prune = sessions[start:end]

    if len(to_prune) == 0:
        print("  No sessions in this date-time range.")
        return

    # Determine target session where data will be merged.
    target_s = sessions[sessions.index(to_prune[-1]) + 1]

    if not options.unattended and len(to_prune)>1:
        print("This will remove multiple sessions:\n"," ".join(to_prune))
        ans = input("Are you sure? (yes/no): ")
        if ans.lower() != "yes":
            x_it(0,"")

    merge_sessions(datavol, to_prune, target_s,
                   clear_sources=True)


# Merge sessions together. Starting from first session results in a target
# that contains an updated, complete volume. Other starting points can
# form the basis for a pruning operation.
# Specify the data volume (datavol), source sessions (sources), and
# target. Caution: clear_sources is destructive.

def merge_sessions(datavol, sources, target, clear_sources=False):
    global destmountpoint, destdir, bkdir

    volume = aset.vols[datavol]
    ses_sizes = set()
    for ses in sources + [target]:
        ses_sizes.add(volume.sessions[ses].volsize)
        if volume.sessions[ses].format == "tar":
            x_it(1, "Cannot merge range containing tarfile session.")

    # Get volume size
    volsize = volume.sessions[target].volsize
    last_chunk = "x"+format(last_chunk_addr(volsize, volume.chunksize), "016x")

    # Prepare manifests for efficient merge using fs mv/replace. The target is
    # included as a source, and oldest source is our target for mv. At the end
    # the merge_target will be renamed to the specified target. This avoids
    # processing the full range of volume chunks in the likely case that
    # the oldest (full) session is being pruned.
    merge_sources = ([target] + list(reversed(sources)))[:-1]
    merge_target  = sources[0]

    with open(pjoin(tmpdir,"sources.lst"), "w") as srcf:
        print(merge_target, target, file=srcf)

        # Get manifests, append session name to eol, print session names to srcf.
        print("  Reading manifests")
        manifests = ""
        cmd = ["set -e", "export LC_ALL=C", "cd "+tmpdir]
        for ses in merge_sources:
            if clear_sources:
                print(ses, file=srcf)
                manifests += " man."+ses
            cmd.append("sed -E 's|$| "+ses+"|' "
                    +pjoin(bkdir,datavol,ses+"/manifest")
                    +" >"+"man."+ses)

        print("###", file=srcf)

    # Unique-merge filenames: one for rename, one for new full manifest.
    cmd.append("sort -u -m -d -k 2,2 "+manifests
               +" >manifest.tmp")
    cmd.append("sort -u -m -d -k 2,2 manifest.tmp "
               +pjoin(bkdir,datavol,merge_target+"/manifest")
               +" >manifest.new")
    p = subprocess.check_call("\n".join(cmd), shell=True)

    # Output manifest filenames in the sftp-friendly form:
    # 'rename src_session/subdir/xaddress target/subdir/xaddress'
    # then pipe to destination and run dest_helper.py.
    print("  Merging to", target)

    cmd = ["cd "+pjoin(bkdir,datavol)
        +"  && export LC_ALL=C"
        +"  && sed -E 's|^\S+\s+x(\S{" + str(address_split[0]) + "})(\S+)\s+"
        +"(S_\S+)|rename \\3/\\1/x\\1\\2 "+merge_target+"/\\1/x\\1\\2|;"
        +" /"+last_chunk+"/q' "+tmpdir+"/manifest.tmp"
        +"  |  cat "+tmpdir+"/sources.lst -"
        +"  | "+" ".join(dest_run_args(vmtype, [destcd + bkdir+"/"+datavol
               +" && export LC_ALL=C"
               +" && cat >"+tmpdir+"/rpc/dest.lst"
               +" && python3 "+tmpdir+"/rpc/dest_helper.py merge"
               ]))
        ]
    p = subprocess.check_call(cmd, shell=True)

    # Update info records and trim to target size
    if clear_sources:
        for ses in sources:
            affected = volume.delete_session(ses)
        volume.sessions[target].save_info()
        volume.save_volinfo()
        print("  Removed", " ".join(sources))

    cmd = ["cd "+pjoin(bkdir,datavol)
        +"  && export LC_ALL=C"
        +"  && sed -E 's/^(\S+\s+\S+).*/\\1/; /"+last_chunk+"/q' "
        +tmpdir+"/manifest.new >"+target+"/manifest",

        # If volume size changed in this period then make trim list.
        ( " && sed -E '1,/"+last_chunk+"/d; "
        +  "s|^\S+\s+x(\S{" + str(address_split[0]) + "})(\S+)|"
        +  target+"/\\1/x\\1\\2|' "+tmpdir+"/manifest.new >"+target+"/delete"
        ) if len(ses_sizes)>1 else "",

        "   && tar -cf - volinfo "+target
        +"  | "+" ".join(dest_run_args(vmtype, [destcd + bkdir+"/"+datavol
            +"  && export LC_ALL=C"
            +"  && tar -xmf -",

            # Trim on dest.
            ( " && cat "+target+"/delete  |  xargs -r rm -f"
            + " && rm "+target+"/delete"
            + " && find "+target+" -maxdepth 1 -type d -empty -delete"
            ) if len(ses_sizes)>1 else "",

              " && sync -f volinfo"
            ])
        )]
    p = subprocess.check_call(" ".join(cmd), shell=True)


# Receive volume from archive. If no save_path specified, then verify only.
# If diff specified, compare with current source volume; with --remap option
# can be used to resync volume with archive if the deltamap or snapshots
# are lost or if the source volume reverted to an earlier state.

def receive_volume(datavol, select_ses="", save_path="", diff=False):
    global destmountpoint, destdir, bkdir, bkchunksize, vgname, poolname

    verify_only = not (diff or save_path!="")
    attended = not options.unattended
    remap = options.remap
    if save_path and os.path.exists(save_path) and attended:
        print("\n!! This will erase all existing data in",save_path)
        ans = input("   Are you sure? (yes/no): ")
        if ans.lower() != "yes":
            x_it(0,"")

    vol = aset.vols[datavol]
    volsize = vol.volsize
    bkchunksize = vol.chunksize
    snap1vol = datavol+".tick"
    sessions = vol.sesnames
    # Set the session to retrieve
    if select_ses:
        datetime.datetime.strptime(select_ses, "%Y%m%d-%H%M%S")
        select_ses = "S_"+select_ses
        if select_ses not in sessions:
            x_it(1, "The specified session date-time does not exist.")
    elif len(sessions) > 0:
        select_ses = sessions[-1]
    else:
        x_it(1, "No sessions available.")


    print("\nReading manifests")
    last_chunk = "x"+format(last_chunk_addr(volsize, bkchunksize), "016x")
    zeros = bytes(bkchunksize)
    open(tmpdir+"/manifests.cat", "wb").close()

    # Collect session manifests
    include = False
    for ses in reversed(sessions):
        if ses == select_ses:
            include = True
        elif not include:
            continue

        if vol.sessions[ses].format == "tar":
            raise NotImplementedError(
                "Receive from tarfile not yet implemented: "+ses)

        # add session column to end of each line:
        cmd = ["cd "+pjoin(bkdir,datavol)
            +"  && export LC_ALL=C"
            +"  && sed -E 's|$| "+ses+"|' "
            +pjoin(ses,"manifest")+" >>"+tmpdir+"/manifests.cat"
            ]
        p = subprocess.check_output(cmd, shell=True)

    # Merge manifests and send to archive system:
    # sed is used to expand chunk info into a path and filter out any entries
    # beyond the current last chunk, then piped to cat on destination.
    # Note address_split is used to bisect filename to construct the subdir.
    cmd = ["cd '"+pjoin(bkdir,datavol)
        +"' && export LC_ALL=C"
        +"  && sort -u -d -k 2,2 "+tmpdir+"/manifests.cat"
        +"  |  tee "+tmpdir+"/manifest.verify"
        +"  |  sed -E 's|^\S+\s+x(\S{" + str(address_split[0]) + "})(\S+)\s+"
        +"(S_\S+)|\\3/\\1/x\\1\\2|;"
        +" /"+last_chunk+"/q'"
        +"  | "+" ".join(dest_run_args(vmtype,
                        ["cat >"+tmpdir+"/rpc/dest.lst"])
        )]
    p = subprocess.check_output(cmd, shell=True)

    print("\nReceiving volume", datavol, select_ses)

    # Create retriever process using py program
    cmd = dest_run_args(vmtype,
            [destcd + bkdir+"/"+datavol
            +"  && export LC_ALL=C"
            +"  && python3 "+tmpdir+"/rpc/dest_helper.py receive"
            ])
    getvol = subprocess.Popen(" ".join(cmd), stdout=subprocess.PIPE,
                              shell=True)


    # Prepare save volume
    if save_path:
        # Discard all data in destination if this is a block device
        # then open for writing
        if vg_exists(os.path.dirname(save_path)):
            lv = os.path.basename(save_path)
            vg = os.path.basename(os.path.dirname(save_path))
            if not lv_exists(vg,lv):
                if vg != vgname:
                    x_it(1, "Cannot auto-create volume:"
                         " Volume group does not match config.")
                p = subprocess.check_output(
                    ["lvcreate -kn -ay -V "+str(volsize)+"b"
                     +" --thin -n "+lv+" "+vg+"/"+poolname], shell=True)
            else:
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
        mapfile = pjoin(bkdir, datavol, "deltamap")
        bmap_size = (volsize // bkchunksize // 8) + 1

        if remap:
            if not lv_exists(vgname, snap1vol):
                p = subprocess.check_output(["lvcreate", "-pr", "-kn",
                    "-ay", "-s", vgname+"/"+datavol, "-n", snap1vol],
                    stderr=subprocess.STDOUT)
                print("  Initial snapshot created for", datavol)
            if not os.path.exists(mapfile):
                init_deltamap(mapfile, bmap_size)
            bmapf = open(mapfile, "r+b")
            os.ftruncate(bmapf.fileno(), bmap_size)
            bmap_mm = mmap.mmap(bmapf.fileno(), 0)
        else:
            if not lv_exists(vgname, snap1vol):
                print("Snapshot '.tick' not available; Comparing with"
                      " source volume instead.")
                snap1vol = datavol

        if volsize != l_vols[snap1vol].lv_size:
            x_it(1, "Volume sizes differ:"
                 "\n  Archive = %d"
                 "\n  Local   = %d" % (volsize, l_vols[snap1vol].lv_size))

        cmpf  = open(pjoin("/dev",vgname,snap1vol), "rb")
        diff_count = 0

    # Open manifest then receive, check and save data
    with open(tmpdir+"/manifest.verify", "r") as mf:
        for addr in range(0, volsize, bkchunksize):
            faddr = "x%016x" % addr
            if attended:
                print(int(addr/volsize*100),"%  ",faddr,end="  ")

            cksum, fname, ses = mf.readline().strip().split()
            if fname != faddr:
                raise ValueError("Bad fname "+fname)

            # Read chunk size
            untrusted_size = int.from_bytes(getvol.stdout.read(4),"big")

            if untrusted_size == 0:
                if cksum.strip() != "0":
                    raise ValueError("Expected %s length, got %d." 
                                     % (cksum, untrusted_size))

                print("OK",end="\x0d")
                if save_path:
                    savef.seek(bkchunksize, 1)
                elif diff:
                    cmpf.seek(bkchunksize, 1)
                continue

            # allow for slight expansion from compression algo
            if untrusted_size > bkchunksize + (bkchunksize // 128) \
                or untrusted_size < 1:
                    raise BufferError("Bad chunk size: "+untrusted_size)

            # Size is OK.
            size = untrusted_size

            # Read chunk buffer
            untrusted_buf = getvol.stdout.read(size)
            rc  = getvol.poll()
            if rc is not None and len(untrusted_buf) == 0:
                break

            if len(untrusted_buf) != size:
                with open(tmpdir+"/bufdump", "wb") as dump:
                    dump.write(untrusted_buf)
                raise BufferError("Got "+len(untrusted_buf)
                                  +" bytes, expected "+size)
            if cksum != hashlib.sha256(untrusted_buf).hexdigest():
                with open(tmpdir+"/bufdump", "wb") as dump:
                    dump.write(untrusted_buf)
                raise ValueError("Bad hash "+fname
                    +" :: "+hashlib.sha256(untrusted_buf).hexdigest())

            # Buffer is OK; Proceed with decompress.
            if attended:
                print("OK",end="\x0d")

            if verify_only:
                continue

            buf = gzip.decompress(untrusted_buf)
            if len(buf) > bkchunksize:
                raise BufferError("Decompressed to "+len(buf)+" bytes")

            if save_path:
                savef.write(buf)
            elif diff:
                buf2 = cmpf.read(bkchunksize)
                if buf != buf2:
                    print("* delta", faddr, "    ")
                    if remap:
                        volsegment = addr // bkchunksize 
                        bmap_pos = volsegment // 8
                        bmap_mm[bmap_pos] |= 1 << (volsegment % 8)
                    diff_count += len(buf)

        print("\nReceived byte range:", addr+len(buf))
        if rc is not None and rc > 0:
            raise RuntimeError("Error code from getvol process: "+rc)
        if addr+len(buf) != volsize:
            raise ValueError("Received range does not match volume size %d."
                             % volsize)
        if save_path:
            savef.close()
        elif diff:
            cmpf.close()
            if remap:
                bmapf.close()
                print("Delta bytes re-mapped:", diff_count)
                if diff_count > 0:
                    print("\nNext 'send' will bring this volume into sync.")


# Exit with simple message

def x_it(code, text):
    sys.stderr.write(text+"\n")
    exit(code)




##  Main  #####################################################################

''' ToDo:
    Check free space on destination
    Encryption
    Reconcile deltas or del archive vol when restoring from older session
    Add support for special source metadata (qubes.xml etc)
    Add other destination exec types (sftp)
    Separate threads for encoding tasks
    Option for live Qubes volumes (*-private-snap)
    Guard against vm snap rotation during receive-save
    Verify entire archive
    Rename and info commands
    Auto-pruning/rotation
    Auto-resume aborted backup session:
        Check dir/file presence, volume sizes, deltabmap size
        Example: if deltamap-tmp exists, then perform checks on
        which snapshots exist.
'''


# Constants
prog_version = "0.2.0betaX"
format_version = 1
prog_name = "sparsebak"
topdir = "/"+prog_name # must be absolute path
tmpdir = "/tmp/"+prog_name
volgroups = {}
l_vols = {}
aset = None
bs = 512
# LVM min blocks = 128 = 64kBytes
lvm_block_factor = 128
# Dest chunk size = 128kBytes
bkchunksize = 2 * lvm_block_factor * bs
assert bkchunksize % (lvm_block_factor * bs) == 0
max_address = 0xffffffffffffffff # 64bits
# for 64bits, a subdir split of 9+7 allows 2048 files per dir
address_split = [len(hex(max_address))-2-7, 7]
pjoin = os.path.join


if sys.hexversion < 0x3050000:
    x_it(1, "Python ver. 3.5 or greater required.")

# Root user required
if os.getuid() > 0:
    x_it(1, "Must be root user.")

# Allow only one instance at a time
lockpath = "/var/lock/"+prog_name
try:
    lockf = open(lockpath, "w")
    fcntl.lockf(lockf, fcntl.LOCK_EX|fcntl.LOCK_NB)
except IOError:
    x_it(1, "ERROR: "+prog_name+" is already running.")

# Create our tmp dir
shutil.rmtree(tmpdir+"-old", ignore_errors=True)
if os.path.exists(tmpdir):
    os.rename(tmpdir, tmpdir+"-old")
os.makedirs(tmpdir+"/rpc")


# Parse arguments
parser = argparse.ArgumentParser(description="")
parser.add_argument("action", choices=["send","monitor","add","delete",
                    "prune","receive","verify","diff","list","version"],
                    default="monitor", help="Action to take")
parser.add_argument("-u", "--unattended", action="store_true", default=False,
                    help="Non-interactive, supress prompts")
parser.add_argument("-a", "--all", action="store_true", default=False,
                    help="Apply action to all volumes")
parser.add_argument("--all-before", dest="allbefore",
                    action="store_true", default=False,
                    help="Select all sessions before --session date-time.")
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

volgroups = get_lvm_vgs()
vgname, poolname, destvm, destmountpoint, destdir, datavols \
= get_configs()

if vgname not in volgroups.keys():
    raise ValueError("\nVolume group "+vgname+" not present.")
l_vols = volgroups[vgname].lvs

bkdir = topdir+"/"+vgname+"%"+poolname
if not os.path.exists(bkdir):
    os.makedirs(bkdir)
destcd = " cd '"+destmountpoint+"/"+destdir+"'"

vmtype = detect_internal_state()

vm_run_args = {"internal":["sh"],
                "ssh":["ssh",destvm],
                "qubes":["qvm-run", "-p", destvm],
                "qubes-ssh":["qvm-run", "-p", destvm.split("|")[0]]
                }

detect_dest_state(destvm)

# Check volume args against config
selected_vols = options.volumes[:]
for vol in options.volumes:
    if vol not in datavols and options.action not in {"add","delete"}:
        print("Volume "+vol+" not configured; Skipping.")
        del(selected_vols[selected_vols.index(vol)])


# Process commands

if options.action   == "monitor":
    monitor_send(datavols, monitor_only=True)


elif options.action == "send":
    monitor_send(selected_vols, monitor_only=False)


elif options.action == "version":
    print(prog_name, "version", prog_version)


elif options.action == "prune":
    if not options.session:
        x_it(1, "Must specify --session for prune.")
    dvs = datavols if len(selected_vols) == 0 else selected_vols
    for dv in dvs:
        if dv in datavols:
            prune_sessions(dv, options.session.split(","))


elif options.action == "receive":
    if not options.saveto:
        x_it(1, "Must specify --save-to for receive.")
    if len(selected_vols) != 1:
        x_it(1, "Specify one volume for receive")
    if options.session and len(options.session.split(",")) > 1:
        x_it(1, "Specify one session for receive")
    receive_volume(selected_vols[0],
                   select_ses="" if not options.session \
                   else options.session.split(",")[0],
                   save_path=options.saveto)


elif options.action == "verify":
    if len(selected_vols) != 1:
        x_it(1, "Specify one volume for verify")
    if options.session and len(options.session.split(",")) > 1:
        x_it(1, "Specify one session for verify")
    receive_volume(selected_vols[0],
                   select_ses="" if not options.session \
                   else options.session.split(",")[0],
                   save_path="")


elif options.action == "diff":
    if selected_vols:
        receive_volume(selected_vols[0], save_path="", diff=True)


elif options.action == "list":
    if not selected_vols:
        print("Configured Volumes:\n")
        for vol in datavols:
            print(" ", vol)

    for dv in selected_vols:
        print("Sessions for volume",dv,":")
        vol = aset.vols[dv]
        lmonth = ""; count = 0; ending = "."
        for ses in vol.sesnames:
            if ses[:8] != lmonth:
                print("" if ending else "\n")
                count = 0
            print(" ",ses[2:]+(" (tar)"
                        if vol.sessions[ses].format == "tar"
                        else ""), end="")
            ending = "\n" if count % 5 == 4 else ""
            print("", end=ending)
            lmonth = ses[:8]; count += 1

    print("" if selected_vols and ending else "\n", end="")


elif options.action == "add":
    if len(options.volumes) < 1:
        x_it(1, "A volume name is required for 'add' command.")

    aset.add_volume(options.volumes[0])
    print("Volume", options.volumes[0], "added.")


elif options.action == "delete":
    dv = selected_vols[0]
    if not options.unattended:
        print("Warning! Delete will remove ALL metadata AND archived data",
              "for volume", dv)

        ans = input("Are you sure (y/N)? ")
        if ans.lower() not in {"y","yes"}:
            x_it(0,"")

    path = aset.vols[dv].path
    aset.delete_volume(dv)
    cmd = [destcd
          +" && rm -rf ." + path
          +" && sync -f ."+ os.path.dirname(path)
          ]
    dest_run(cmd)
    print("\nVolume", dv, "deleted.")


elif options.action == "untar":
    raise NotImplementedError()


print("\nDone.\n")\
