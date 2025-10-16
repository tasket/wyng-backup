# Wyng archive duplicate/update utility.
# Perform remote updates of duplicate Wyng archives.

# Use: sync-archive.py source_arch_path dest_arch_path
# dest_arch_path may be a dir path or a URL of the form 'ssh://[user@]hostname[:port]/remote/path'

import sys, os, subprocess as SPr
from urllib.parse import urlparse

def dir_scan(netloc, path):
    vols, cmd = {}, rf"cd '{path}' && find . -maxdepth 2 -type d -name 'S_????????-??????'"
    for ln in run_dest(cmd, netloc, capture_output=True).stdout.splitlines():
        v, s = ln.split("/")[-2:]
        if v.startswith("Vol_") and s.startswith("S_"):
            vols.setdefault(v, set()).add(s)
    return vols

def run_dest(cmd, netloc, **kwargs):
    return SPr.run(["ssh", "ssh://"+netloc, cmd], shell=False, text=True, **kwargs) \
        if netloc else SPr.run(cmd, shell=True, text=True, **kwargs)


##  MAIN  ##

srcpath, destpath = sys.argv[1:3]

if destpath.endswith("/."):   destpath = destpath[:-2]
if destpath.endswith("/"):    destpath = destpath[:-1]
dest_url = urlparse(destpath)
assert dest_url.scheme in ("", "file", "ssh")
assert not dest_url.path.endswith("-incomplete")
dipath = dest_url.path+"-incomplete"
if srcpath.endswith("/."):   srcpath = srcpath[:-2]
if srcpath.endswith("/"):    srcpath = srcpath[:-1]

run_dest(rf"if [ ! -e '{dipath}' ]; then"
         rf"   if [ ! -e {dest_url.path} ]; then mkdir -p '{dipath}';"
         rf"   else mv '{dest_url.path}' '{dipath}';"
         rf" fi; fi", dest_url.netloc)

src = dir_scan("", srcpath)    ; dest = dir_scan(dest_url.netloc, dipath)

for v in src.keys() & dest.keys():
    # Merge pruned session dirs on dest
    src_l, dest_l = sorted(src[v]), sorted(dest[v])
    if not src[v] or not dest[v]:   continue
    if src_l[-1] < dest_l[-1]:
        print(f"Source '{v}' appears older.")   ; continue

    pruned = sorted(dest[v] - src[v])    ; common = sorted(dest[v] & src[v])

    while pruned and common:
        ses = pruned.pop(0)    ; dpos = dest_l.index(ses)    ; ses_next = dest_l[dpos+1]

        if ses < common[-1]:
            print(f"Prune: {v}/{ses}")
            run_dest(rf"cd '{dipath}/{v}'"
                     rf" && cp -alf {ses_next}/* {ses}"
                     rf" && rm -r {ses_next}"
                     rf" && mv {ses} {ses_next}", dest_url.netloc)
            dest_l.pop(dpos)

rs0 = ["rsync", "-uaHW", "--progress", "--no-compress", "--delete"]
rs1 = ["--rsh=ssh" + (f" -p {dest_url.port}" if dest_url.port else "")] \
        if dest_url.scheme=="ssh" else []
rs2 = [srcpath + "/."]
rs3 = [(dest_url.username+"@" if dest_url.username else "") + dest_url.hostname + ":" + dipath]

print("\nExecuting:", " ".join(rs0 + rs1 + rs2 + rs3), flush=True)
SPr.run(rs0 + rs1 + rs2 + rs3)
run_dest(rf"mv '{dipath}' '{dest_url.path}'", dest_url.netloc)
