# Rocky 10 Snapshot Manager
<img width="1694" height="809" alt="image" src="https://github.com/user-attachments/assets/89af0b61-5094-433b-88b1-d281862f2039" />

A Tkinter-based GUI application for managing LVM snapshots on Rocky Linux 10, integrating with Boom for boot management.

## Features

- Detect existing LVM snapshots and layout
- Create snapshots for root, var, and home logical volumes
- Add Boom boot entries for rollback
- Merge snapshots to rollback the system
- Delete snapshots
- Install Boom if not present

## Requirements

- Rocky Linux 10
- Root privileges (run with `sudo`)
- LVM2
- Boom (installed automatically via the app)
- Python 3 with Tkinter

## Installation

Install the RPM package:

```bash
sudo dnf install rocky-snapshot-manager-1.0-1.noarch.rpm
```

## Usage

Run the application:

```bash
sudo rocky-snapshot-manager
```

The GUI provides buttons for all operations. Ensure you have sufficient free space in the VG before creating snapshots.

## Building from Source

To build the RPM:

1. Ensure `rpm-build` is installed: `sudo dnf install rpm-build`
2. Run the build script: `./build_rpm.sh`
3. The RPM will be in `~/rpmbuild/RPMS/noarch/`

## Installation on Rocky 10:

Ensure dependencies are available: `sudo dnf install python3-tkinter boom-boot lvm2`
Install the RPM: `sudo dnf install ~/rpmbuild/RPMS/noarch/rocky-snapshot-manager-1.0-1.el10.noarch.rpm`
Run the app: `sudo rocky-snapshot-manager`
The package installs the script as `/usr/bin/rocky-snapshot-manager` with proper permissions, includes documentation and license files, and declares dependencies on Python 3, Tkinter, Boom, and LVM2. It's a noarch package, so it works on any architecture.

You can now distribute this RPM for easy installation on Rocky Linux 10 systems! If you need to rebuild or modify the package, just run build_rpm.sh again.


## License

GPL-3.0
