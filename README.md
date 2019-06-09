<h1 align="center">Sparsebak</h1>
<p align="center">
Fast incremental backups for logical volumes.
</p>

Introduction
---

Sparsebak is able to deliver faster, more efficient incremental backups for logical volumes.
It accesses logical volume *metadata* (instead of re-scanning data) to instantly find which
data has changed since the last backup. Combined with a Time Machine style storage format,
it can also prune older backups from the
archive very quickly, meaning you only ever have to do a full backup once and can send 
incremental backups to the same archive indefinitely.

Having nearly instantaneous access to volume changes and fast archive operations
enable backing up even terabyte-sized volumes multiple times per hour with little
impact on system resources.

And sparsebak's ingenious snapshot-rotation avoids "*aging snapshot*" space consumption
pitfalls that most lvm backups suffer.

Sparsebak sends data as *streams* whenever possible, which
avoids writing temporary caches of data to disk. It also doesn't require the
source admin system to ever mount processed volumes, meaning untrusted data
in guest filesystems can be handled safely for container-based security.


Status
---

Full range of features including:

 - Incremental backups of Linux thin-provisioned LVM volumes
to local or guest VM filesystems or SSH hosts

 - Volume retrieval for restore and verify operations
 
 - Fast pruning of past backup sessions

 - Basic archive management such as add and delete volume

Data verification currently relies on SHA-256 manifests being safely stored on the
source/admin system to maintain integrity checks. Integrated encryption and key-based
verification are not yet implemented.

Sparsebak is in beta-testing, is released under a GPL license and comes with no warranties expressed or implied.


Setup & Requirements
---

Before starting:

* Thin-provisioning-tools, lvm2, and python >=3.5.4 must be present on the source system.

* The destination system (if different from source) should also have python, plus
a basic Unix command set *and* Unix filesystem.

* Configured volumes to be backed-up must reside in an LVM thin-provisioned pool.

`sparsebak.py` is currently distributed as a single python executable with no complex
supporting modules or other program files; it can be placed in '/usr/local/bin'
or another place of your choosing. It looks in '/sparsebak/default.ini'
for settings that define what to back up and where the backup archive will
be located as well as the archive's metadata.

Settings are initialized with `arch-init`. Please note that dashed arguments are
always placed before the command:

```
sparsebak.py --source=vg/pool --dest=ssh://me@exmaple.com/mnt/bkdrive arch-init
```

...or...

```
sparsebak.py --source=vg/poolname --dest=internal:/ --subdir=home/user arch-init
```

The `--dest` argument always ends in a _mountpoint_ (mounted volume) absolute path.
In the second example, the destination system has no unique mountpoint in the
desired backup path, so `--dest` ends with the root '/' path and the `--subdir`
argument is supplied to complete the archive path.

The destination mountpoint is automatically checked to make sure its mounted
before executing certain sparsebak commands
including `send`, `receive`, `verify`, `delete` and `prune`.

(See the `arch-init` summary below for more details.)


Operation
---

Run `sparsebak.py` in a Linux environment using the following commands and options
in the form of `sparsebak.py [--options] command [volume_name]`.

### Command summary

```
list [volume_name]    | List volumes, or volume sessions.
send [volume_name]    | Perform a backup of enabled volumes.
receive volume_name   | Restore a volume from the archive.
verify volume_name    | Verify a volume against SHA-256 manifest.
prune [volume_name]   | Remove older backup sessions to recover archive space.
monitor               | Collect volume change metadata & rotate snapshots.
diff volume_name      | Compare local volume with archived volume.
add volume_name       | Add a volume to the configuration.
delete volume_name    | Remove entire volume from config and archive.
arch-init             | Initialize archive configuration.
arch-delete           | Remove data and metadata for all volumes.
arch-deduplicate      | Deduplicate existing data in archive (experimental).
```

### Options summary

Note that options currently are always specified before commands, not after.

```
-u, --unattended      | Don't prompt for interactive input.
--all-before          | Select all sessions before the specified --session date-time.
--session=date-time[,date-time]
                      | Select a session or session range by date-time (receive, verify, prune).
--save-to=path        | Required for `receive`.
--tarfile             | Store backups as tar files (experimental).
--remap               | Remap volume during `diff`.
--source              | (arch-init) Specify source for backups.
--dest                | (arch-init) Specify destination of backup archive.
--subdir              | (arch-init) Optional subdirectory bewlow mountpoint.
--compression         | (arch-init) Set compression type:level.
--chunk-factor        | (arch-init) Set archive chunk size.
--testing-dedup=N     | Select deduplication algorithm for send (see Testing notes).
```

#### send

   $ sudo sparsebak.py send

The `send` command performs a backup by sending volume data to the archive
as a *'session'* denoted by a date-time YYYYMMDD-HHMMSS. For example: 20190530-120000.
Each session under an archival volume represents the entire contents of
the source volume at that time.

If sparsebak has no metadata on file about a
volume, its treated as a new addition to the backup set so an initial snapshot will
be made and a full backup will be sent to the archive;
otherwise it will automatically use snapshot delta information to send a much faster
incremental backup. Whenever a `send` operation is completed, snapshots are
renewed just as with the `monitor` command.


#### receive

The `receive` command retreives a volume instance (using the latest session ID
if `--session` isn't specified) from the archive and saves it to the path specified
with `--save-to`. If `--session` is used, only one date-time is accepted. The volume
name and `--save-to` are required.

   $ sudo sparsebak.py --save-to=myfile.img receive vm-work-private

...restores a volume called 'vm-work-private' to 'myfile.img' in
the current folder. Note that its possible to specify any path, including block
devices such as '/dev/vgname/vm-work-private'. In this case, the lv volume will
be automatically created if the configured volume group matches the save path.

Resizing is automatic if the path is a logical volume or regular file. For any
`--save-to` type, sparsebak will try to discard old data before saving.


#### verify

The `verify` command is similar to `receive` without `--save-to`. For both
`receive` and `verify` modes, an exception error will be raised with a non-zero exit
code if the received data does not pass integrity checks.


#### prune

The `prune` command can quickly reclaim space on a backup drive by removing
any prior backup session you specify; it does this
without re-writing data or compromising volume integrity.

To use, supply a single exact date-time in YYYYMMDD-HHMMSS format to remove a
specific session, or two date-times as a range:

   $ sudo sparsebak.py --session=20180605-000000,20180701-140000 prune

...removes any backup sessions from midnight on June 5 through 2pm on July 1.
Alternately, `--all-before` may be used with a single `--session` date-time
to select all sessions prior to that time.

If specific volumes aren't specified, `prune` will operate across all
enabled volumes.


#### monitor

   $ sudo sparsebak.py monitor

The `monitor` command frees disk space that is increasingly occupied by aging
snapshots, thereby addressing a common resource usage issue with snapshot-based
backups. After harvesting their change metadata, the older snapshots are replaced with
new ones. Running `monitor` isn't strictly necessary, but it only takes a few seconds
and is good to run on a frequent, regular basis (several times an hour or more)
if you have some volumes that are very active.

This rule in /etc/cron.d runs `monitor` every 20 minutes:

```
*/20 * * * * root su -l -c '/usr/local/bin/sparsebak.py monitor'
```

#### diff

   $ sudo sparsebak.py diff vm-work-private

Compare a current configured volume with the archive copy and report any differences.
This is useful for diagnostics and can also be useful after a verification
error has occurred. The `--remap` option will record any differences into the
volume's current change map, resulting in those blocks being backed-up on
the next `send`.


#### add

   $ sudo sparsebak.py add vm-untrusted-private

Adds a new entry to the list of volumes configured for backup.


#### delete

   $ sudo sparsebak.py delete vm-untrusted-private

Removes a volume's config, snapshots and metadata from the source system and
all of its *data* from the destination archive. Use with caution!


#### arch-init

Initializes the settings for a backup archive. Parameters:

`--source` is required and
takes the source volume group and pool as `--source=vgname/poolname`.
These LVM objects don't have to exist before using `arch-init` but they will
have to be there later, of course.

`--dest` is required and accepts one of the following forms, always ending
in a mountpoint path:

```
URL:                                      Destination Type:

ssh://user@exmaple.com/path              | SSH server
                                         |
internal:/path                           | Local filesystem
                                         |
qubes://vm-name/path                     | Qubes virtual machine
                                         |
qubes-ssh://vm-name|me@example.com/path  | SSH server via a Qubes VM 
```

`--subdir` allows you to specify a subdirectory below the mountpoint.

`--compression=zlib:4` accepts the form `type:level`. However, only zlib compression
is supported at this time so this option is currently only useful to set the
compression level.



Tips
----

* If the destination volume is not thoroughly trusted, its currently recommended
to avoid backing up sensitive data to such a volume -- exercise caution
and add encryption where necessary.

* To reduce the size of incremental backups it may be helpful to remove cache
files, if they exist in your volume(s). Typically, the greatest cache space
consumption comes from web browsers, so
volumes holding paths like /home/user/.cache can impacted by this, depending
on the amount and type of browser use associated with the volume. Two possible
approaches are to delete /home/user/.cache dirs on browser exit or system/container
shutdown (this reasonably assumes cached data is expendable), or to mount .cache
on a separate volume that is not configured for backup.

* Another factor in space/bandwidth use is how sparse your source volumes are in
practice. Therefore it is best that the `discard` option is used when mounting
your volumes for normal use.

* The chunk size of your LVM thin pool can also affect disk space and I/O used when
sending backups. Larger pool chunk
sizes can mean larger incremental backups for volumes with lots of random writes.
To see the chunksize for your pool(s) run `sudo lvs -o name,chunksize`. Common sizes
are 128-512kB but if the chunk size is larger and random writes are prevalent (i.e. for
large databases or mail archives) then using sparsebak deduplication (which resolves
at 64kB) can reduce the size of your backup sessions.



Troubleshooting notes
---

* Backup sessions in `list` output may be seemingly (but not actually) out of
order if the system's local time shifts
substantially between backups, such as when moving between time zones (including DST).
If this results in undesired selections with `--session` parameters, its possible
to nail down the precisely desired range by observing the output of
`list volumename` and using exact date-times from the listing.

### Encryption options

Sparsebak is slated to integrate encryption in the future. In the meantime,
here are some encryption approaches you can try:

* __Regular Linux systems__ have many options for mounting an encrypted filesystem on a
backup drive. Some examples you'll find use `gnome-disks` to
format a partition as Ext4 on LUKS, or they use encrypted filesystems like
[Encfs](https://wiki.ubuntu.com/SecureEncryptedRemoteVolumeHowTo)
or [Cryfs](https://www.cryfs.org). These usually
create a local filesystem mountpoint, so configuring sparsebak with an
'internal:/path' destination should suffice.

    For remote backups where the server is trusted (i.e. encrypted and secured) it
    is possible to forgo setup of archive encryption on your source computer and just
    specify 'ssh://user@address/path' for your sparsebak destination. Of course, this
    requires that you have access to the server via SSH.

    What to avoid: Any 'mirroring' type of remote or cloud storage, such as the regular
    Dropbox client — these would keep a local copy of *everything* in the backup archive
    in addition to sending data to the cloud server. Use these only if you prefer using lots
    of extra disk space on your system.

* __Virtualized host systems__ using Xen or KVM hypervisors have a couple options:

1. Setup a trusted guest VM instance to decrypt and mount an encrypted backup drive.
Then from the admin/storage VM setup sparsebak with an 'ssh://' destination specifying
the local network address of the guest VM. This method generally uses less bandwidth
and completes faster.

2. For hypervisors that support attachment of block devices to different VMs: An
encrypted block dev can be attached to the admin/storage VM where it is then decrypted
and mounted (this means a guest VM is not trusted with handling encryption).
In this case use 'internal:/path' for the sparsebak destination.

* __Qubes OS:__ Here is a brief description for dom0-encrypted remote storage from a Qubes laptop:

1. Qube *remotefs* runs `sshfs` or other file sharing to access a remote filesystem
and then `losetup` on a remote file (to size the file correctly during inital setup,
use `truncate -s <size> myfile.img` before using `losetup`).

2. *Domain0* runs `qvm-block attach dom0 remotefs:loop0`.

3. *Domain0* runs `cryptsetup` on /dev/xvdi to create/access the volume in its
encrypted form. Finally, the resulting /dev/mapper device can be mounted for use.

4. Setup sparsebak on *Domain0* for an `internal:/path` destination type
pointing to the mounted path.

A local USB storage option similar to the above can be used by substituting *sys-usb*
for *remotefs*.

For Qubes OS where you have a trusted backup VM handling encryption, you can setup
sparsebak in dom0 with a 'qubes://vm-name/path' destination. And for Qubes OS where
you have both a trusted backup VM *and* trusted server, you can backup to the server
via the backup VM with a 'qubes-ssh://vm-name|user@address/path' destination (note
these qubes options have much faster performance than the above `qvm-block attach` setup).


Todo
---

* Encryption integration

* Additional functions: untar, verify-archive

* File name and sequence obfuscation

* Btrfs and ZFS support
