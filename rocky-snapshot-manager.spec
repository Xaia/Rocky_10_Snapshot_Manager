Name:           rocky-snapshot-manager
Version:        1.0
Release:        1%{?dist}
Summary:        LVM Snapshot Manager GUI for Rocky Linux 10

License:        GPL-3.0
URL:            https://github.com/Xaia/Rocky_10_Snapshot_Manager
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
Requires:       python3
Requires:       python3-tkinter
Requires:       boom-boot
Requires:       lvm2

%description
A Tkinter-based GUI application for managing LVM snapshots on Rocky Linux 10,
integrating with Boom for boot management.

%prep
%setup -q

%build
# No build step required for Python script

%install
mkdir -p %{buildroot}%{_bindir}
install -m 755 snapshot_manager.py %{buildroot}%{_bindir}/rocky-snapshot-manager

%files
%license LICENSE
%doc README.md
%{_bindir}/rocky-snapshot-manager

%changelog
* Wed Nov 20 2025 Xaia <xaia@example.com> - 1.0-1
- Initial package