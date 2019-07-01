<h1 align="center">Wyng</h1>
<p align="center">
Fast incremental backups for logical volumes.
</p>

### Introduction

Wyng is able to deliver faster, more efficient incremental backups for logical
volumes. It accesses logical volume *metadata* (instead of re-scanning data over
and over) to instantly find which *data* has changed since the last backup.
Combined with a Time Machine style storage format, it can also prune older
backups from the archive very quickly, meaning you only ever have to do a full
backup once and can send incremental backups to the same archive indefinitely
and frequently.

Having nearly instantaneous access to volume changes and a nimble archival format
enable backing up even terabyte-sized volumes multiple times per hour with little
impact on system resources.

And Wyng's ingenious snapshot rotation avoids common _"aging snapshot"_ space
consumption pitfalls.

Wyng sends data as *streams* whenever possible, which
avoids writing temporary caches of data to disk. Wyng also doesn't require the
source admin system to ever mount processed volumes, so it safely handles
untrusted data in guest filesystems to bolster container-based security.


### Status

Beta, with a range of features including:

 - Incremental backups of Linux thin-provisioned LVM volumes
to local filesystem, virtual machine or SSH host

 - Volume retrieval for restore and verify operations

 - Fast pruning of past backup sessions

 - Basic archive management such as add and delete volume

Data verification currently relies on SHA-256 manifests being safely stored on the
source admin system or encrypted volume. Integrated encryption and key-based
verification are not yet implemented.

Wyng is released under a GPL license and comes with no warranties expressed or implied.


### Requirements & Setup

Before starting:

* Thin-provisioning-tools, lvm2, and python >=3.5.4 must be present on the source system.

* The destination system (if different from source) should also have python, plus
a basic Unix command set *and* Unix filesystem.

* Volumes to be backed-up must reside in an LVM thin-provisioned pool.

Wyng is currently distributed as a single python executable with no complex
supporting modules or other program files; it can be placed in '/usr/local/bin'
or another place of your choosing.

Settings are initialized with `wyng <args> arch-init`:

```

wyng --local=vg/pool --dest=ssh://me@exmaple.com/mnt/bkdrive arch-init

...or...

wyng --local=vg/pool --dest=internal:/ --subdir=home/user arch-init

wyng add my_big_volume


```

The `--dest` argument always ends in a _mountpoint_ (mounted volume) absolute path.
In the second example, the destination system has no unique mountpoint in the
desired backup path, so `--dest` ends with the root '/' path and the `--subdir`
argument is supplied to complete the archive path.

The destination mountpoint is automatically checked to make sure its mounted
before executing certain Wyng commands
including `send`, `receive`, `verify`, `delete` and `prune`.

(See the `arch-init` summary below for more details.)


Operation
---

Run Wyng using the following commands and arguments in the form of:

**wyng \<parameters> command [volume_name]**

Please note that dashed parameters are always placed before the command.

### Command summary

| _Command_ | _Description_  |
|---------|---|
| **list** _[volume_name]_    | List volumes or volume sessions.
| **send** _[volume_name]_    | Perform a backup of enabled volumes.
| **receive** _volume_name_   | Restore a volume from the archive.
| **verify** _volume_name_    | Verify a volume against SHA-256 manifest.
| **prune** _[volume_name]_   | Remove older backup sessions to recover archive space.
| **monitor**                 | Collect volume change metadata & rotate snapshots.
| **diff** _volume_name_      | Compare local volume with archived volume.
| **add** _volume_name_       | Add a volume to the configuration.
| **delete** _volume_name_    | Remove entire volume from config and archive.
| **arch-init**               | Initialize archive configuration.
| **arch-delete**             | Remove data and metadata for all volumes.
| **arch-deduplicate**        | Deduplicate existing data in archive (experimental).

### Parameters / Options summary

| _Option_                      | _Description_
|-------------------------------|--------------
-u, --unattended       | Don't prompt for interactive input.
--session=_date-time[,date-time]_ | Select a session or session range by date-time (receive, verify, prune).
--all-before           | Select all sessions before the specified _--session date-time_ (prune).
--save-to=_path_       | Required for `receive`: Specify a save path.
--from=_type:location_ | Retrieve from a specific unconfigured archive (receive, verify, list).
--tarfile              | Store backups as tar files (experimental).
--remap                | Remap volume during `diff`.
--local=_vg/pool_      | (arch-init) Specify pool containing local volumes.
--dest=_type:location_ | (arch-init) Specify destination of backup archive.
--subdir=_dirname_     | (arch-init) Optional subdirectory below mountpoint.
--compression          | (arch-init) Set compression type:level.
--chunk-factor         | (arch-init) Set archive chunk size.
--testing-dedup=_N_    | Select deduplication algorithm for send (see Testing notes).


#### send

Performs a backup by sending volume data to a new archive session
(each session under an archival volume represents the entire contents of
the source volume at that time, even if only changed data is sent):

```

wyng send


```

If wyng has no metadata on file about a
volume, its treated as a new addition to the backup set so an initial snapshot will
be made and a full backup will be sent to the archive;
otherwise it will automatically use snapshot delta information to send a much faster
incremental backup. Whenever a `send` operation is completed, snapshots are
renewed just as with the `monitor` command.


#### receive

Retrieves a volume instance (using the latest session ID
if `--session` isn't specified) from the archive and saves it to the path specified
with `--save-to`. If `--session` is used, only one date-time is accepted. The volume
name and `--save-to` are required.

```

wyng --save-to=myfile.img receive vm-work-private


```

...restores a volume called 'vm-work-private' to 'myfile.img' in
the current folder. Its possible to specify any valid file path or block
device such as '/dev/vgname/vm-work-private'. In the latter case, the LVM volume will
be automatically created if the configured volume group matches the save-to path.

Resizing is automatic if the path is a logical volume or regular file. For any
`--save-to` target, Wyng will try to discard old data before saving.

The `--from` option may be used to retreive from any archive that is not currently
configured in the users' current system, permitting restore operations in
an emergency. It is specified just like the `--dest` option of `arch-init`:

```

wyng --from=ssh://user@192.168.1.2/mountpoint --save-to=vol.img receive my-volume


```

#### verify

The `verify` command is similar to `receive` without `--save-to`. For both
`receive` and `verify` modes, an exception error will be raised with a non-zero exit
code if the received data does not pass integrity checks.


#### prune

Quickly reclaims space on a backup drive by removing
any prior backup session you specify; it does this
without re-writing data or compromising volume integrity.

To use, supply a single exact date-time in _YYYYMMDD-HHMMSS_ format to remove a
specific session, or two date-times as a range:

```

wyng --session=20180605-000000,20180701-140000 prune


```

...removes backup sessions from midnight on June 5 through 2pm on July 1 for all
volumes. Alternately, `--all-before` may be used with a single `--session` date-time
to prune all sessions prior to that time.

If volume names aren't specified, `prune` will operate across all
enabled volumes.


#### monitor

Frees disk space that is cumulatively occupied by aging
snapshots, thereby addressing a common resource usage issue with snapshot-based
backups. After harvesting their change metadata, the older snapshots are replaced with
new ones. Running `monitor` isn't strictly necessary, but it only takes a few seconds
and is good to run on a frequent, regular basis if you have some volumes that are
very active. Volume names may also be
specified if its desired to monitor only certain volumes.

This rule in /etc/cron.d runs `monitor` every 20 minutes:

```
*/20 * * * * root su -l -c '/usr/local/bin/wyng monitor'
```

#### diff
```

wyng diff vm-work-private


```

Compare a local volume snapshot with the archive and report any differences.
This is useful for diagnostics and can also be useful after a verification
error has occurred. The `--remap` option will record any differences into the
volume's current change map, resulting in those blocks being backed-up on
the next `send`.


#### add
```

wyng add vm-untrusted-private


```
Adds a new entry to the list of volumes configured for backup.


#### delete
```

wyng delete vm-untrusted-private


```

Removes a volume's config, snapshots and metadata from the source system and
all of its *data* from the destination archive. Use with caution!


#### arch-init

Initializes a backup archive.
```

wyng --source=myvg/mypool --dest=internal:/mountpoint arch-init


```


Parameters:

`--local` is required and takes the source volume group and pool as `vgname/poolname`.
These LVM objects don't have to exist before using `arch-init` but they will
have to be there before using `send`.

`--dest` is required and describes the location where backups will be sent.
It accepts one of the following forms, always ending
in a mountpoint path:

| _URL Form_ | _Destination Type_
|----------|-----------------
|__internal:__/path                           | Local filesystem
|__ssh://__user@example.com/path              | SSH server
|__qubes://__vm-name/path                     | Qubes virtual machine
|__qubes-ssh://__vm-name\|me@example.com/path  | SSH server via a Qubes VM

`--subdir` allows you to specify a subdirectory below the mountpoint.

`--compression=zlib:4` accepts the form `type:level`. However, only zlib compression
is supported at this time so this option is currently only useful to set the
compression level.

`--chunk-factor=1` sets the pre-compression data chunk size used within the destination archive in
units of 64kB. A chunk-factor of '4' equates to 256kB chunks. Minimum is '1' and
maximum is '256'. The recommended range of sizes for general use is 1-4.


Tips
----

* If the destination volume is not thoroughly trusted, its currently recommended
to avoid backing up sensitive data to such a volume -- exercise caution
and add encryption where necessary.

* To reduce the size of incremental backups it may be helpful to remove cache
files, if they exist in your volume(s). Typically, the greatest cache space
consumption comes from web browsers, so
volumes holding paths like /home/user/.cache can impacted by this, depending
on the amount and type of browser use associated with the volume. Three possible
approaches are to clear caches on browser exit, delete /home/user/.cache dirs on system/container
shutdown (this reasonably assumes cached data is expendable), or to mount .cache
on a separate volume that is not configured for backup.

* Another factor in space/bandwidth use is how sparse your source volumes are in
practice. Therefore it is best that the `discard` option is used when mounting
your volumes for normal use.

* The chunk size your LVM thin pool was initialized with can also affect disk space
and I/O used when sending backups. Larger LVM chunk
sizes can mean larger incremental backups for volumes with lots of random writes.
To see the chunksize for your pool(s) run `sudo lvs -o name,chunksize`. Common sizes
are 128-512kB so if random writes are prevalent (i.e. for
large databases or mail archives) then using Wyng deduplication (which resolves
at 64kB by default) can reduce the size of your backup sessions.

* If your system root volume resides in the LVM thin pool, there may be no obvious
way to back up this volume in a 'safe' offline manner since snapshotting it while
the system is running could leave the archived filesystem in an inconsistent state.
One way to do this is to place a small script in /lib/systemd/system-shutdown with
[snapshot commands]() then `wyng add` the snapshot name instead of the actual root
volume name.



Troubleshooting notes
---

* Backup sessions in `list` output may be seemingly (but not actually) out of
order if the system's local time shifts
substantially between backups, such as when moving between time zones (including DST).
If this results in undesired selections with `--session` parameters, its possible
to nail down the precisely desired range by observing the output of
`list volumename` and using exact date-times from the listing.


Encryption options
---

Wyng is slated to integrate encryption in the future. In the meantime,
here are some encryption approaches you can use:

* __Regular Linux systems__:

    Many options exist for mounting an encrypted filesystem on a local
    backup drive. Some examples you'll find use `gnome-disks` to
    format a partition as Ext4 on LUKS or VeraCrypt, or they use encrypted filesystems
    like [Encfs](https://wiki.ubuntu.com/SecureEncryptedRemoteVolumeHowTo)
    or [Cryfs](https://www.cryfs.org). These usually
    create a local filesystem mountpoint, so configuring Wyng with an
    'internal:/path' destination should suffice.

    For remote backups on untrusted servers, use one of the above encryption
    options on a shared folder (Encfs, Cryfs) or disk image file (LUKS, VeraCrypt).

    For remote backups where the server is trusted (i.e. encrypted and secured) it
    is possible to forgo setup of archive encryption on your source computer and just
    specify 'ssh://user@address/path' for your Wyng destination. Of course, this
    requires that you have access to the server via SSH.

    What to avoid: Any 'mirroring' type of remote or cloud storage, such as the
    regular Dropbox client — these would keep a local copy of *everything* in
    the backup archive in addition to sending data to the cloud server. Use
    these only if you prefer using lots of extra disk space on your system.

* __Virtualized host systems__ using Xen, KVM or other hypervisors:

    Option A)  From the admin/storage VM, setup Wyng with an 'ssh://' destination where
    you wish to store the archive. This destination may be a local guest VM or a
    remote server.

    Option B)  For hypervisors that support attachment of block devices to
    different VMs: An encrypted block dev can be attached directly to the
    admin/storage VM where it is then decrypted and mounted. This uses an
    'internal:/path' destination and means that a guest VM or destination server
    is not trusted with handling encryption, but may be slower due to
    filesystem-network overhead.

* __Qubes OS:__ A brief description for dom0-encrypted remote storage from a Qubes laptop:

    1. Qube *remotefs* runs `sshfs` or other file sharing to access a remote filesystem
    and then `losetup` on a remote file (to size the file correctly during inital
    setup, use `truncate -s <size> mydisk.img` before using `losetup`).

    2. *Domain0* runs `qvm-block attach dom0 remotefs:loop0`.

    3. *Domain0* runs `cryptsetup` on /dev/xvdi to create/access the volume in its
    encrypted form. Finally, the resulting /dev/mapper device can be mounted for use.

    4. Setup Wyng on *Domain0* with `--dest=internal:/path`
    pointing to the mounted path.

    A local USB storage option similar to the above can be used by substituting *sys-usb*
    for *remotefs* and (if no disk image file) skipping `truncate` and `losetup`.

    As an alternative to the above, if you have a trusted backup qube handling
    encryption, you can easily setup Wyng in dom0 with a 'qubes://vm-name/path'
    destination. Also, for Qubes OS where you have both a trusted backup VM *and*
    trusted server, you can backup to the server via the backup VM with a
    'qubes-ssh://vm-name|user@address/path' destination. These qubes options can
    achieve faster performance than the above `qvm-block attach` setup, but they
    move archive encryption out of Domain 0.


Donations
---
<a href="https://liberapay.com/tasket/donate"><img alt="Donate using Liberapay" src="images/lp_donate.svg" height=54></a>

<a href="https://www.patreon.com/tasket"><img alt="Donate with Patreon" src="images/become_a_patron_button.png" height=50></a>

If you like Wyng or my other efforts, monetary contributions are welcome and can
be made through [Liberapay](https://liberapay.com/tasket/donate)
or [Patreon](https://www.patreon.com/tasket).


Todo
---

* Encryption integration

* File name and sequence obfuscation

* Zstandard compression

* Btrfs and ZFS support
