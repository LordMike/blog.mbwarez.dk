# Introduction

I have a disk with bad blocks. The filesystem I'm using (such as ZFS) doesn't support marking bad blocks like ext did, and completely replacing the disk is costly and unnecessary. Instead, I've used `dmsetup` to create a virtual disk that excludes the bad sectors, allowing the filesystem to work with the remaining good areas.

This guide covers the process of scanning the disk, preparing a custom partition, setting up `dmsetup`, and ensuring everything works across reboots. I've additionally included steps to ensure that the `dmsetup` configuration follows the disk, ensuring you don't loose that critical piece of information.

## Essential components

- **Device mapper** is a linux component that allows us to create virtual devices, who's underlying implementation can change. This can be used to implement striping, multipathing, redirect parts of the device to different physical disks, various tests like artificial delays and errors and so on. In this post, I use it to map around bad blocks.

# The process

The process will:

1. Create a partition layout on the faulty disk
2. Run `badblocks` to identify faulty areas
3. Create the necessary `dmsetup` configuration
4. "Mount" the virtual device, and ensure it mounts on boot

## 1. Creating Partitions
We will first prepare a partition to hold the configuration for `dmsetup`.

```bash
parted /dev/<disk> mklabel gpt
parted /dev/<disk> mkpart primary ext3 1MB 20MB
parted /dev/<disk> mkpart primary 20MB 100%

# Make the configuration partition use ext3, a widely supported filesystem
mkfs.ext3 /dev/<disk>1
e2label /dev/<disk>1 "READ ME"
```

This creates two partitions:

* Partition 1: A very small partition to hold important configurations on this disk
* Partition 2: The remainder of the drive. This is where we will be making our `dmsetup` magic

I made the small partition 20MB, but even that may be too large. Although its more tricky to make it larger if needed, later on.

> ℹ️ Info: The ext3 partition holds the configuration files (`dmsetup` table, systemd service) so that everything follows the disk when you move it around. Setting its label to **'READ ME'** hints at its purpose and ensures anyone inspecting the disk understands its role.

## 2. Running Badblocks
Scan the remainder of the disk for bad blocks:
```bash
badblocks -b 512 -o badblocks.txt -s
```

Now, you can additionally:

* Run `badblocks` with `-n` for a non-destructive read-write mode, it rewrites the entire disk with the same contents
* Run `badblocks` with `-w` for a **destructive** read-write mode, it overwrites the entire disk with 4 patterns
  * If you do this, also consider passing `-p 1` to just do one pass. My disks are 8 TB, 4 passes is a lot

> ℹ️ Info: Even if the physical disk uses 4k sectors, we use 512-byte sectors, as `dmsetup` operates on 512-byte units.

## 3. Identify good ranges

Once `badblocks` is done, you'll have a file filled with sectors that are considered bad. Now, we need to _inverse_ that to get ranges that are good. You can do this manually, read the file and identify sequential sets of numbers, then write out the ranges _between_ those numbers. F.ex, a file with the numbers `1, 2, 3, 9, 10, 17` should give ranges `0-1, 4-9, 11-17`. I've also prepared a bash script that can do this:

```bash
generate_dmsetup_table() {
    local device="$1"
    local badblocks_file="$2"

    if [[ ! -b "$device" ]]; then
        echo "Device not found or not a block device: $device" >&2
        return 1
    fi

    if [[ ! -f "$badblocks_file" ]]; then
        echo "Badblocks file not found: $badblocks_file" >&2
        return 1
    fi

    # Get the total number of 512-byte sectors on the device
    local total_sectors
    total_sectors=$(blockdev --getsz "$device")

    if [[ -z "$total_sectors" ]]; then
        echo "Failed to retrieve the total number of sectors from $device." >&2
        return 1
    fi

    # Read numbers into an array
    readarray -t numbers < "$badblocks_file"

    local prev=-1
    local offset=0

    # Add initial good range from 0 to the first bad block (if not starting at 0)
    if (( numbers[0] > 0 )); then
        local length=$((numbers[0] - 0))
        echo "0 $length $device linear $offset"
        offset=$((offset + length))
    fi

    # Iterate over the bad blocks to generate ranges
    for i in "${!numbers[@]}"; do
        local num="${numbers[i]}"
        if (( prev != -1 && num > prev + 1 )); then
            local start=$((prev + 1))
            local length=$((num - start))
            echo "$start $length $device linear $offset"
            offset=$((offset + length))
        fi
        prev=$num
    done

    # Add final range from the last bad block to the end of the device
    if (( prev < total_sectors - 1 )); then
        local start=$((prev + 1))
        local length=$((total_sectors - start))
        echo "$start $length $device linear $offset"
    fi
}


# Example use:
> generate_dmsetup_table /dev/<disk>2 badblocks.txt
```

This script should ideally generate a dmsetup table, which covers the good ranges in the badblocks file. 

> ⚠️ Important: Make sure to reference the second partition of your disk, the one that covers the rest of the disk. All offsets are _relative_ to that device. If you don't, the final dmsetup device will be incorrect.

> ℹ️ Info: At this point, begin referencing the disk by its id, like `/dev/disk/by-id/<disk>-part2`. This reference persists between reboots, and will make sure your dmsetup file also references that.

Once ready, output the table to a file in `/etc/dmsetup`, f.ex. `/etc/dmsetup/sd-badblocks-<disk>.table`.

## 4. Setting up `dmsetup` systemd unit
Create this `systemd` unit, in `/etc/systemd/system/dmsetup-sd-badblocks-<disk>.service`

```ini
[Unit]
Description=Prepare dmsetup device for <device>, to avoid badblocks

[Service]
Type=oneshot
ExecStart=/bin/sh -c '/bin/cat /etc/dmsetup/<disk-id>.table | /sbin/dmsetup create sd-badblocks-<disk-id>'
ExecStop=/sbin/dmsetup remove <disk-id>
RemainAfterExit=true

[Install]
WantedBy=multi-user.target
```

> ℹ️ Info: If, like me, you're using ZFS, it is important that this unit loads _before_ ZFS mounts its devices. Add this line under the `[Unit]` section to ensure ZFS mounts _after_: `Before=zfs-mount.service`

Reload the unit, and start it. Verify it doesn't emit any errors.

```bash
systemctl daemon-reload
systemctl start dmsetup-sd-badblocks-<disk>
```

Once it works, enable the service to make it auto-start on boot

```bash
systemctl enable dmsetup-sd-badblocks-<disk>
```

> ℹ️ Info: We copy the table into `/etc/dmsetup` to ensure that on boot, we don't need to _first_ have the configuration mounted and _then_ be able to load `dmsetup`. It's better to have fewer dependencies. Step 6 below will copy in the configuration to the first partition for safekeeping, but once thats done, you don't need to mount that partition again (until you move the disk or reinstall the OS of course).

## 6. Preparing the configuration partition

Copy the table, and the systemd unit to your configuration partition.

```bash
mkdir /mnt/tmp
mount /dev/<disk>1 /mnt/tmp

cp /etc/dmsetup/<disk-id>.table /mnt/tmp/
cp /etc/systemd/system/dmsetup-sd-badblocks-<disk>.service /mnt/tmp/

# Copy this blogpost to the readme
printf "Source: {{< ref "index.md" >}}\n\n" > /mnt/tmp/README.txt
wget {{< ref "index.md" >}}readme.txt -O - >> /mnt/tmp/README.txt
```

> ℹ️ Info: Now, if you move the disk to a new computer or similarly, then mounting the first partition will show the information needed to mount the second partition using dmsetup.

> ⚠️ Important: It is possible to mount the second partition, as it will contain actual filesystem headers. Ensure you only use the mapped device.
