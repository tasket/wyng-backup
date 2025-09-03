_<h1 align="center">Wyng</h1>_
<p align="center">
Faster incremental backups for logical volumes and disk images.
</p>

### Introduction

Wyng is able to deliver faster incremental backups for logical
volumes and disk images. It accesses *copy-on-write* metadata (instead of comparing all data
for each backup) to instantly find changes since the last backup.
Combined with its efficient archive format, Wyng can also very quickly reclaim space
from older backup sessions.

Having nearly instantaneous access to volume changes and a nimble archival format
enables backing up even terabyte-sized volumes multiple times per hour with little
impact on system resources.

Wyng pushes data to archives in a stream-like fashion, which avoids temporary data
caches and re-processing data. And Wyng's ingenious snapshot rotation avoids common
_aging snapshot_ space consumption pitfalls.

Wyng also doesn't require the source admin system to ever mount processed volumes or
to handle them as anything other than blocks, so it safely handles
untrusted data in guest file systems to bolster container-based security.


### Status

<table style="border-style:none; padding:0px;">
    <tr vertical-align="center" style="border-style:none;">
        <td align="center" style="border-style:none; width:50px"><img src="media/info1.svg" height=42 /></td>
        <td style="border-style:none;"><b>Notice: Wyng project has moved to <a href="https://codeberg.org/tasket/wyng-backup">Codeberg.org!</b></a></td>
</tr></table>

Public beta with a range of features including:

 - Incremental backups of Linux logical volumes from Btrfs, XFS and Thin-provisioned LVM

 - Supported destinations: Local file system, Virtual machine or SSH host

 - Fast pruning of old backup sessions

 - Basic archive management such as add/delete volume and auto-pruning

 - Automatic creation & management of local snapshots

 - Data deduplication

 - Marking and selecting archived snapshots with user-defined tags

Version 0.8 major enhancements:

 - Btrfs and XFS reflink support

 - Authenticated encryption with auth caching

 - Full data & metadata integrity checking

 - Fast differential receive based on local snapshots

 - Overall faster operation

 - Change autoprune behavior with --apdays

 - Configure defaults in /etc/wyng/wyng.ini

 - Simple selection of archives and local paths: Choose any _local_ or _dest_ each time you run Wyng

 - Multiple volumes can now be specified for most Wyng commands; send and receive support multiple storage pools

 Wyng is released under a GPL license and comes with no warranties expressed or implied.


Wyng v0.8 Requirements & Setup
---

Before starting:

* Python 3.8 or greater is required for basic operation.

* For encryption and top performance, the _python3-pycryptodome_ and _python3-zstd_ packages
should be installed, respectively.

* Volumes to be backed-up should reside locally in one of the following snapshot-capable
storage types:  LVM thin-provisioned pool, Btrfs subvolume, or XFS/reflink capable file system. Otherwise, volumes may be imported from or saved to other file systems at standard (slower) speeds.

* For backing up from LVM, _thin-provisioning-tools & lvm2_ must be present on the source system.  For Btrfs, the `btrfs` command must be present.

* The destination system where the Wyng archive is stored (if different from source) should
also have python3, plus a basic Unix command set and file system (i.e. a typical Linux or BSD
system). Otherwise, _samba_, FUSE, etc. may be used to access remote storage using smb, sftp, s3 or other protocols
without concern for python or Unix commands.

* See the 'Testing' section below for tips and caveats about using the alpha and beta versions.


## Getting Started

Wyng is distributed as a single Python executable with no complex
supporting modules or other program files; it can be placed in '/usr/local/bin'
or another place of your choosing:

```
sudo cp -a wyng-backup/src/wyng /usr/local/bin
```

Archives can be created with `wyng arch-init`:

```
sudo wyng arch-init --dest=ssh://me@example.com:/home/me/mylaptop.backup

...or...

sudo wyng arch-init --dest=file:/mnt/drive2/mylaptop.backup
```

The examples above create a 'mylaptop.backup' directory on the destination.
The `--dest` argument includes the destination type, remote system (where applicable)
and directory path.

Next you can start making backups with `wyng send`:

```
sudo wyng send --dest=file:/mnt/drive2/mylaptop.backup --local=volgrp1/pool1 root-volume home-volume
```

This command sends two volumes 'root-volume' and 'home-volume' from the LVM thin pool 'volgrp1/pool1' to the destination archive.

<br/>
 
## Basic Operation

Run Wyng using the following commands and arguments in the form of:

**wyng \[--options] command \[volume_names] \[--options]**


### Command summary

| _Command_ | _Description_  |
|---------|---|
| **list** _[volume_name]_    | List volumes or volume sessions
| **send** _[volume_name]_    | Perform a backup of enabled volumes
| **receive** _volume_name [*]_   | Restore volume(s) from the archive
| **arch-init**               | Create a new Wyng archive
| **version**                 | Print the Wyng version and exit

For additional commands, options, and advanced usage notes see the _[Wyng User Reference](doc/Wyng_User_Reference.md)._

<br/>

### Command details

### send

Performs a backup by storing volume data to a new session in the archive.  If the volume
already exists in the archive, incremental mode is automatically used.

```

wyng send my_big_volume --local=vg/pool --dest=file:/mnt/drive2/mylaptop.backup

```

`send` supports automatic pruning of older backup sessions to recover disk space before the new data is sent; set `--autoprune` option to _on_ or _full_ to use this feature.

Volume names for non-LVM storage may include subdirectories, making them relative paths in
the same manner as file paths in `tar`.
For example, `wyng --local=/mnt/pool1 send appvms/personal.img` will send the volume located
at '/mnt/pool1/appvms/personal.img'.


### receive

Retrieves volumes (using the latest session ID
if `--session` isn't specified) from the archive and saves it to either the `--local`
storage or the path specified with `--save-to` (the latter allows receiving only
one volume at a time).
If `--session` is used, only one date-time is accepted. The volume name is required.

```

wyng receive vm-work-private --local=vg/pool --dest=file:/mnt/drive2/mylaptop.backup

```

...restores a volume called 'vm-work-private' to 'myfile.img' in
the LVM thin pool 'vg/pool'.  Note that `--dest` always refers to the archive location, so
the volume is being restored _from_ '/mnt/drive2/mylaptop.backup'.

For any save path, Wyng will try to discard old data before receiving unless `--sparse`,
`--sparse-write` or `--use-snapshot` options are used.


<br>
 
### list

Displays the volumes contained in a Wyng archive.

```

# Show all volumes with details:
wyng list --verbose

# Show details of volume 'example.img':
wyng list example.img

# Show volumes in a particular backup session:
wyng list --session=20250601-000001

```


### arch-init

Creates new Wyng archives at a specified location.
```

# New archive on a mounted drive:
wyng arch-init --dest=file:/mnt/backups/archive1


# New archive on a remote system with stronger compression:
wyng arch-init --dest=ssh://user@example.com --compression=zstd:7

```

Optional parameters for `arch-init` are _encrypt, compression, hashtype_ and _chunk-factor_.
These cannot be changed for an archive after it is initialized.


<br/>

### Parameters / Options summary

| _Option_                      | _Description_
|-------------------------------|--------------
--dest=_URL_           | Location of backup archive.
--local=_vg/pool_  _...or..._    | Storage pool containing local volumes
--local=_/absolute/path_    | 
--session=_date-time[,date-time]_ | Select a session or session range by date-time or tag (receive, verify, prune)
--use-snapshot         | Receive from the local snapshot (receive)
--send-unchanged       | Record unchanged volumes, don't skip them (send)
--unattended, -u       | Don't prompt for interactive input
--verbose              | Increase details
--quiet                | Shhh...



### Option Details

#### `--dest=<URL>`

This option tells Wyng where to access the archive and has the same meaning for all read or write
commands. It accepts one of the following forms:

| _URL Form_ | _Destination Type_
|----------|-----------------
|__file:__/path                           | Local file system
|__ssh:__//user@example.com[:port][/path]      | SSH server
|__qubes:__//vm-name[/path]                     | Qubes virtual machine
|__qubes-ssh:__//vm-name:me@example.com[:port][/path]  | SSH server via a Qubes VM


#### `--local=<path | volgroup/pool>`

The location of local copy-on-write storage where logical volumes, disk images, etc. reside.  This serves as the _source_ for `send` commands, and as the place where `receive` restores/saves volumes.

This parameter takes one of two forms: Either the source volume group and pool as 'vgname/poolname'
or a directory path on a reflink-capable file system such as Btrfs or XFS (for Btrfs the path should
end at a subvolume).  Required for commands `monitor` and `diff`, `receive` when
not using `--save-to`, and `send` when not using `--import-other-from`.


#### `--session=<date-time>[,<date-time>]` OR
#### `--session=^<tag>[,^<tag>]`

Session allows you to specify a single date-time or tag spec for the `receive`, `verify`, `diff`, `prune`, `list`, and `arch-check` commands as well as a comma-separated range for `prune`. Using a single tag selects the last session having that tag. When specifying
tags, each must be prefixed by a `^` carat.

For more details, see the _Wyng User Reference_.


#### `--use-snapshot`

Use the latest local snapshot, if one is available, as the baseline for the `receive` process. This can result in near-instantaneous receiving of archived volumes. In cases where an older session is requested, only the differences between the snapshot and the requested version of the volume will be transferred from the archive, which can greatly accelerate `receive`.

Also use `--sparse` if you want Wyng to fall back to
sparse mode when snapshots are not already present.

### User Guide

For additional commands, options, and advanced usage notes see the _[Wyng User Reference](doc/Wyng_User_Reference.md)._

### Verifying Code

Wyng code can be cryptographically verified using either `gpg` directly or via `git`:

```sh
# Import Key
~$ cd wyng-backup
~/wyng-backup$ gpg --import pubkey
gpg: key 1DC4D106F07F1886: public key "Christopher Laprise <tasket@posteo.net>" imported
gpg: Total number processed: 1
gpg:               imported: 1

# GPG Method
~/wyng-backup$ gpg --verify src/wyng.gpg src/wyng

# Git Method
~/wyng-backup$ git verify-commit HEAD

# Output:
gpg: Signature made Sat 26 Aug 2023 04:20:46 PM EDT
gpg:                using RSA key 0573D1F63412AF043C47B8C8448568C8B281C952
gpg: Good signature from "Christopher Laprise <tasket@posteo.net>" [unknown]
gpg:                 aka "Christopher Laprise <tasket@protonmail.com>" [unknown]
```


### Donations

<a href="https://liberapay.com/tasket/donate"><img alt="Donate using Liberapay" src="media/lp_donate.svg" height=54></a>

<a href="https://ko-fi.com/tasket"><img src="media/ko-fi.png" height=57></a> <a href="https://ko-fi.com/tasket">Ko-Fi donate</a>

<a href="https://www.buymeacoffee.com/tasket"><img src="media/buymeacoffee_57.png" height=57></a> <a href="https://www.buymeacoffee.com/tasket">Buy me a coffee!</a>


If you like this project, monetary contributions are welcome and can
be made through [Liberapay](https://liberapay.com/tasket/donate) or [Ko-Fi](https://ko-fi.com/tasket) or [Buymeacoffee](https://www.buymeacoffee.com/tasket).
