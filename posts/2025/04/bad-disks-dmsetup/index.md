
# Introduction

I have a disk with bad blocks. The filesystem I'm using (such as ZFS) doesn't support marking bad blocks like ext did, and completely replacing the disk is costly and unnecessary. Instead, I've used `dmsetup` to create a virtual disk that excludes the bad sectors, allowing the filesystem to work with the remaining good areas.

This guide covers the process of scanning the disk, preparing a custom partition, setting up `dmsetup`, and ensuring everything works across reboots. I've additionally included steps to ensure that the `dmsetup` configuration follows the disk, ensuring you don't loose that critical piece of information.

> ℹ️ Info: If you're mounting a disk that was prepared by this post, skip to step 4 and copy files from the ext3 filesystem in partition 1.

## Essential components

- **Device mapper** is a linux component that allows us to create virtual devices, who's underlying implementation can change. This can be used to implement striping, multipathing, redirect parts of the device to different physical disks, various tests like artificial delays and errors and so on. In this post, I use it to map around bad blocks.
- Identifying disks **by their id** - to ensure that we never encounter issues due to disk renumbering, or when moving between systems, it is essential to use the disk ids instead of their temporary names. All disks should be available in `/dev/disk/by-id/` on your linux system. My approach will use the disk id, like `scsi-88774aaeef234` as the identifier for the device.

> {{< per-post/2025/dmsetup-js >}}

## The process

The process will:

1. Create a partition layout on the faulty disk
2. Run `badblocks` to identify faulty areas
3. Create the necessary `dmsetup` configuration and `systemd` unit
4. "Mount" the virtual device, and ensure it mounts on boot

## 0. Identify the disk

Say you want to operate on `/dev/sdk`. Identify its id, by looking in `/dev/disk/by-id/`, like this:

```bash
find /dev/disk/by-id -lname "*sdk"
```

This above script will list all the links in `by-id` that point to `sdk`. Choose your preferred id, and substitue the `DISK_ID` in all future bits of this post with the name of that. As an example, you may choose `/dev/disk/by-id/scsi-35000039fe6e8235c` - then use `scsi-35000039fe6e8235c`.

## 1. Creating Partitions

We will first prepare a partition layout to separate the configuration for `dmsetup` and the remainder of the disk.

```bash
parted /dev/disk/by-id/DISK_ID mklabel gpt
parted /dev/disk/by-id/DISK_ID mkpart primary ext3 1MB 10MB
parted /dev/disk/by-id/DISK_ID mkpart primary 10MB 100%
```

This creates two partitions:

- Partition 1: A very small partition to hold important configurations on this disk
- Partition 2: The remainder of the drive. This is where we will be making our `dmsetup` magic

I made the small partition 10MB, but even that may be too large. Although its more tricky to make it larger if needed, later on.

## 2. Running Badblocks

Scan the remainder of the disk for bad blocks:

```bash
badblocks -b 4096 -o badblocks-4k.txt -s /dev/disk/by-id/DISK_ID-part2
```

Now, you can additionally:

- Add `-n` for a non-destructive read-write mode, it rewrites the entire disk with the same contents
- Add `-w` for a **destructive** read-write mode, it overwrites the entire disk with 4 patterns
- Remove `-s` (status reporting) if you, like me, are running this in parallel on many disks.

> ⚠️ Important: `-w` is destructive, it will overwrite data.

> ℹ️ Info: `dmsetup` operates on 512-byte units, so ideally we would set `-b 512` to keep everything aligned, but badblocks uses 32-bit integers internally for blocks. So 512-byte blocks has a cap of a 2TB disk, 1024-byte a 4 TB disk and so on. I will operate on `4096` byte blocks, because most larger disks are this size anyways, but we'll have to multiply all offsets later on to compensate.

> ℹ️ Info: If we ever need to in the future, we must run badblocks with the same block size as before. I've encoded the size in the filename (`-4k.txt`) so we can know.

## 3. Prepare dmsetup and systemd

Once `badblocks` is done, you'll have a file filled with blocks that are considered bad. Now, we need to _inverse_ that to get ranges that are good. You can do this manually, read the file and identify sequential sets of numbers, then write out the ranges _between_ those numbers. F.ex, a file with the numbers `1, 2, 3, 9, 10, 17` should give ranges `0-1, 4-9, 11-17`.

I've prepared a bash script that can:

- Prepare a `dmsetup table` for the disk with the inverse of the badblocks ranges
- Prepare a `systemd` unit that can load our `dmsetup` device

{{< collapse summary="Bash script to prepare dmsetup and system configs" >}}
```bash
generate_dmsetup_and_systemd_unit() {
    local input="$1"
    local badblocks_file="$2"
    local block_size="$3"

    # Resolve input to a /dev/disk/by-id/ path (disk, not partition)
    local device=""
    if [[ "$input" =~ ^/dev/disk/by-id/ ]]; then
        device="$input"
    elif [[ "$input" =~ ^/dev/ ]]; then
        device=$(find /dev/disk/by-id -lname "*${input##*/}" | grep -E '/dev/disk/by-id/(scsi|ata|nvme|sas)-[0-9a-fA-F]+' | head -n1)
        if [[ -z "$device" ]]; then
            device=$(find /dev/disk/by-id -lname "*${input##*/}" | grep -E '/dev/disk/by-id/wwn-' | head -n1)
        fi
        if [[ -z "$device" ]]; then
            device=$(find /dev/disk/by-id -lname "*${input##*/}" | head -n1)
        fi
    else
        device="/dev/disk/by-id/$input"
    fi

    if [[ ! -e "$device" || ! -b "$device" ]]; then
        echo "Error: Unable to resolve '$input' to a valid /dev/disk/by-id/ block device." >&2
        return 1
    fi

    local id="${device##*/}"
    local part_device="${device}-part2"
    if [[ ! -e "$part_device" || ! -b "$part_device" ]]; then
        echo "Error: Expected partition device $part_device not found." >&2
        return 1
    fi

    local name="dm-badblocks-${id}"
    local table_file="${name}.table"
    local service_file="${name}.service"

    if [[ ! -f "$badblocks_file" ]]; then
        echo "Error: badblocks file not found: $badblocks_file" >&2
        return 1
    fi

    if [[ -z "$block_size" || "$block_size" -lt 512 ]]; then
        echo "Error: block size must be >= 512" >&2
        return 1
    fi
    if (( block_size & (block_size - 1) )); then
        echo "Error: block size must be a power of 2" >&2
        return 1
    fi

    local scale=$((block_size / 512))
    local total_sectors
    total_sectors=$(blockdev --getsz "$part_device")

    echo "Generating ${table_file} for $part_device..."

    # Parse/sort badblocks file (may be empty)
    local -a badblock_sectors
    while IFS= read -r line; do
        [[ -n "$line" ]] && badblock_sectors+=($((line * scale)))
    done < <(sort -n "$badblocks_file")

    # Emit a dmsetup table file in the form "<virtual_offset> <length> linear <device> <physical_offset>"
    if (( ${#badblock_sectors[@]} == 0 )); then
        {
            local length=$((total_sectors - 8))
            echo "0 $length linear $part_device 8"
        } > "$table_file"
    else
        if (( badblock_sectors[0] <= 8 )); then
            echo "Error: there are badblocks on the first sectors of the disk. This is not supported by this script." >&2
            return 1
        fi
        {
            local first_length=$((badblock_sectors[0] - 8))
            echo "0 $first_length linear $part_device 8"
            local offset=$((first_length))
            local physical_sector_prev=-1
            for i in "${!badblock_sectors[@]}"; do
                local physical_sector="${badblock_sectors[i]}"
                if (( physical_sector_prev != -1 && physical_sector > physical_sector_prev + 1 )); then
                    local start=$((physical_sector_prev + 1))
                    local length=$((physical_sector - start))
                    echo "$offset $length linear $part_device $start"
                    offset=$((offset + length))
                fi
                physical_sector_prev=$physical_sector
            done
            # Final range
            if (( physical_sector_prev < total_sectors - 1 )); then
                local start=$((physical_sector_prev + 1))
                local length=$((total_sectors - start))
                echo "$offset $length linear $part_device $start"
            fi
        } > "$table_file"
    fi

    echo "Generating ${service_file}..."

    local encoded_id="${id//-/'\\x2d'}"

    cat > "$service_file" <<EOF
[Unit]
Description=Prepare dmsetup device for $name
After=dev-disk-by${encoded_id}\\x2dpart2.device

[Service]
Type=oneshot
ExecStart=/bin/sh -c '/bin/cat /etc/dmsetup/${table_file} | /sbin/dmsetup create ${name}'
ExecStop=/sbin/dmsetup remove ${name}
RemainAfterExit=true

[Install]
WantedBy=multi-user.target
EOF

    echo "Done."
    echo "-> Table:   $PWD/$table_file"
    echo "-> Service: $PWD/$service_file"
    if (( ${#badblock_sectors[@]} == 0 )); then
        echo -e "\033[1;31mWARNING: badblocks file is empty. Outputting a table for the whole device.\033[0m" >&2
    fi
}
```
{{< /collapse >}}

```bash
# Example use:
> generate_dmsetup_and_systemd_unit scsi-35000c500bf2dc1eb badblocks-4k.txt 4096
> generate_dmsetup_and_systemd_unit /dev/sdc badblocks-4k.txt 4096
> generate_dmsetup_and_systemd_unit /dev/disk/by-id/scsi-35000c500bf2dc1eb badblocks-4k.txt 4096
```

Once run, you'll have two files in your current directory:

- `dm-badblocks-DISK_ID.table` -- dmsetup table to avoid badblocks
- `dm-badblocks-DISK_ID.service` -- systemd unit

> ℹ️ Info: If, like me, you're using ZFS, it is important that this unit loads _before_ ZFS mounts its devices. Add this line under the `[Unit]` section to ensure ZFS mounts _after_ dmsetup: `Before=zfs-mount.service`. You can adjust this as needed for other systems.

## 4. Setting up this system

Now we will prepare our running system to use the `dmsetup`. This step should be repeated, if you move the disk to a new system.

```bash
# Prepare the dmsetup etc directory
mkdir -p /etc/dmsetup

# Copy the systemd unit
cp dm-badblocks-DISK_ID.service /etc/systemd/system/
cp dm-badblocks-DISK_ID.table /etc/dmsetup/
```

Reload the unit, and start it. Verify it doesn't emit any errors.

```bash
systemctl daemon-reload
systemctl start dm-badblocks-DISK_ID
```

Once it works, enable the service to make it auto-start on boot

```bash
systemctl enable dm-badblocks-DISK_ID
```

> ℹ️ Info: We copy the table into `/etc/dmsetup` to ensure that on boot, we don't need to _first_ have the configuration mounted and _then_ be able to load `dmsetup`. It's better to have fewer dependencies. Step 6 below will copy in the configuration to the first partition for safekeeping, but once thats done, you don't need to mount that partition again (until you move the disk or reinstall the OS of course).

## 5. Preparing the configuration partition

Copy the table, and the systemd unit to your configuration partition.

```bash
# Make the configuration partition use ext3, a widely supported filesystem
# Emphasis on small - make it 1024 byte blocks, 5% reserved space and fewer inodes
mkfs.ext3 -b 1024 -m 5 -T news /dev/disk/by-id/DISK_ID-part1

mkdir /mnt/tmp
mount /dev/disk/by-id/DISK_ID-part1 /mnt/tmp

# Ensure we can identify this setup in the future
# Do this by writing a helpful text in the beginning of our physical device, in the 4k in the beginning that is not used
e2label /dev/disk/by-id/DISK_ID-part1 "READ ME"

dd if=/dev/zero of=/dev/disk/by-id/DISK_ID-part2 bs=4096 count=1 conv=notrunc
echo -n "This disk is managed by dmsetup. Do not use directly. Read the configuration on the first partition for how to use." | dd of=/dev/disk/by-id/DISK_ID-part2 bs=4096 count=1 conv=notrunc

# Copy in configuration files
cp dm-badblocks-DISK_ID.table /mnt/tmp/
cp dm-badblocks-DISK_ID.service /mnt/tmp/
cp badblocks-4k.txt /mnt/tmp/

# Copy this blogpost to the readme
printf "Source: {{< ref "index.md" >}}\n\n" > /mnt/tmp/README.txt
wget {{< ref "index.md" >}}index.md -O - >> /mnt/tmp/README.txt
```

> ℹ️ Info: The ext3 partition holds the configuration files (`dmsetup` table, systemd service) so that everything follows the disk when you move it around. Setting its label to **'READ ME'** hints at its purpose and ensures anyone inspecting the disk understands its role.

> ℹ️ Info: We've also ensured that partition 2 is not mountable by conventional means. This ensures that when the disk is moved to a new system, it is not accidentally identified as EXT/ZFS/FAT or whatever might actually be on it.

## Summary

By using this method, you can salvage a disk with bad sectors and make it usable again without having to replace it. This approach is especially useful when working with filesystems that do not support marking bad blocks, like ZFS.

You can replicate this process for other disks by adjusting the disk IDs and table filenames.
