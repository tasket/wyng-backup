## sparsebak

Efficient, disk image-based backups for Qubes OS and Linux LVM.

### Overview

Some of the best backup tools in terms of ease of use, resource use and flexibility
are those based on a filesystem interlink storage model. This model uses links
between versions (or sessions) of a volume to avoid storing multiple copies of
files that haven't changed. A couple examples of this type of backup are rsnapshot
and Apple's Time Machine.

Another 'best of' backup category is the 'filesystem send' type which reads
metadata about the source volume to very quickly & efficiently find
only the bits of the filesystem that have changed. A few examples here are
btrfs and zfs send/receive... and Time Machine. This is in stark contrast
to backup tools that can't cope efficiently with modest changes to large files
without either storing the entire file or brute-force scanning of the entire
file to find any changes (this includes those vaunted hash-based backup tools
which are heavy on disk I/O and CPU).

These two 'best of' categories by themselves also carry pitfalls. Interlinks
won't save you from picking out only the changes from source files (or else
having to backup the entire file). Using source metadata can incur disk space penalties on the source volume due to
having idle snapshots consume increasing amounts of space as the source volume
accumulates changes.

Time Machine presents an interesting example because it (mostly) fits into
both of the above categories while avoiding those pitfals. It is a compromise in design that tries to
deliver a functional and efficiency sweet spot for the user. In many cases
Time Machine knows instantly what parts of the source volumes/files have changed without
scanning the files, and its able to organize the changes as parts that can be
quickly retreived as part of a whole, or quickly deleted without disturbing the integrity
of later backups.

sparsebak tries to create a Time Machine-like sweet spot for the task of backing
up logical volumes and disk images; these are storage volumes such as Linux LVM thin pools,
disk image files on Btrfs and perhaps most other copy-on-write mediums with snapshot
capability. The methods used are different than TM, however: snapshot metadata
is used in place of sparse bundle and folder timestamps, and on the destination
links are only seldom used.

sparsebak also adds a technique called 'walking snapshots' to keep snapshot space
consumption to a fraction of what it would normally use by regularly scanning the
snapshot metadata for changes and rotating in a fresh snapshot. This scan and
rotate process is very quick, usually requiring about one second for each source volume.
Walking snapshots enable use cases where the user can backup their system once
per hour, once per day, or at leisure without being chained to a frequent and
rigid backup schedule in order to avoid exhausting free space on the
source disk. A mobile laptop user, for example, may not want to see their free
space shrink if they heavily write to their internal disk while their backup
volume is offline or subject to interruptions. With sparsebak, the backup
process can be delayed to whenever and the extra snapshot space will return to zero
at every scan interval (i.e. 10 or 20 minutes).


### Status

Can do full and incremental backups of thin LVM to local dom0 or VM filesystems on Qubes OS,
as well as simple volume retreival for restoring; Btrfs has not yet been implemented.
As yet there is no verification or encryption so the destination environment must
be encrypted and trusted.
Cases of volume expansion or shrinkage are handled appropriately and a fair number
of sanity checks are performed.

This is still in alpha/testing stage. Do NOT rely on this program as your primary backup system!

### Operation

sparsebak looks in '/sparsebak/sparsebak.ini' for a list of volume names to
be monitored and backed up. Some settings you can change are `vgname` and `poolname`
for the volume group and pool, in addition to `destvm`, `destmountpoint` and `destdir`
which combine to a vm:dir/path specification for the backup destination. The
`destmountpoint` is checked to make sure its mounted when sparsebak is run in `--send` mode.

The resulting backup metadata is also saved to '/sparsebak' for now. Backups
can be sent to a trusted Qubes VM with access to an
encryped removable volume, for example, or an encrypted remote filesystem.

Currently the default mode (with no command options) is a monitor-only session
that collects volume change metadata. This only takes a few seconds and is good
to do on a frequent, regular basis - i.e. several times an hour.

Command options:
  -s, --send	Perform a backup after scanning volume changes.
  -u, --unattended
  --tarfile	Store backups in tar files instead of chunks (cannot be pruned).

### Restoring

The `spbk-assemble` tool can be used to create a regular disk image from a
sparsebak archive. It should be run on a system/VM that has filesystem access
to the archive, using the syntax `spbk-assemble path-to-volume-name`.

### Todo

* Basic functions: Volume selection, Restore, Delete

* Encryption

* Pool-based Deduplication

* Additional sanity checks

* Btrfs support
