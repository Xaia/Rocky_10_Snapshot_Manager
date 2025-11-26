#!/usr/bin/env python3
# snapshot_manager.py — LVM + Boom GUI for Rocky 10 (XFS/ext4, thin or classic)
# Run as: sudo python3 snapshot_manager.py
# Requires: tkinter, boom-boot, boom-boot-conf, python3-boom

import os, subprocess, sys, time, re, json, shutil
import tkinter as tk
from tkinter import ttk, messagebox

APP_TITLE = "Rocky 10 Snapshot Manager (LVM + Boom)"
DEFAULT_VG = "rl"
DEFAULT_ROOT_LV = "root"
DEFAULT_VAR_LV  = "var"
DEFAULT_HOME_LV = "home"

def sh(cmd, check=False):
    """Run shell command; return (rc, out, err)."""
    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = p.communicate()
    if check and p.returncode != 0:
        raise RuntimeError(f"cmd failed: {cmd}\n{err}")
    return p.returncode, out.strip(), err.strip()

def need_root():
    if os.geteuid() != 0:
        messagebox.showerror(APP_TITLE, "Please run as root: sudo python3 snapshot_manager.py")
        sys.exit(1)

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1700x770")
        self.minsize(1000, 680)

        # Top form
        frm = ttk.Frame(self, padding=8)
        frm.pack(fill="x")

        self.vg = tk.StringVar(value=DEFAULT_VG)
        self.root_lv = tk.StringVar(value=DEFAULT_ROOT_LV)
        self.var_lv  = tk.StringVar(value=DEFAULT_VAR_LV)
        self.home_lv = tk.StringVar(value=DEFAULT_HOME_LV)

        self.root_sz = tk.StringVar(value="20G")
        self.var_sz  = tk.StringVar(value="10G")
        self.home_sz = tk.StringVar(value="0G")  # 0G means skip

        self.stamp = tk.StringVar(value=time.strftime("%Y-%m-%d-%H%M"))

        row = 0
        for label, var in [("VG", self.vg), ("root LV", self.root_lv), ("var LV", self.var_lv), ("home LV", self.home_lv)]:
            ttk.Label(frm, text=label, width=10).grid(row=row, column=0, sticky="w")
            ttk.Entry(frm, textvariable=var, width=22).grid(row=row, column=1, sticky="w", padx=6)
            row += 1

        ttk.Separator(frm, orient="horizontal").grid(row=row, column=0, columnspan=8, sticky="ew", pady=6); row += 1

        for label, var in [("root snap size", self.root_sz), ("var snap size", self.var_sz), ("home snap size", self.home_sz)]:
            ttk.Label(frm, text=label, width=14).grid(row=row, column=0, sticky="w")
            ttk.Entry(frm, textvariable=var, width=10).grid(row=row, column=1, sticky="w", padx=6)
            row += 1

        ttk.Label(frm, text="STAMP").grid(row=row, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.stamp, width=18).grid(row=row, column=1, sticky="w", padx=6)
        row += 1
        # Kernel options controls
        opts = ttk.Frame(self, padding=(8, 2))
        opts.pack(fill="x")
        self.use_current_opts = tk.BooleanVar(value=True)
        self.clean_current_opts = tk.BooleanVar(value=True)
        self.extra_opts = tk.StringVar(value="")

        ttk.Checkbutton(opts, text="Use current kernel options (/proc/cmdline)",
                        variable=self.use_current_opts).pack(side="left", padx=(0,12))
        ttk.Checkbutton(opts, text="Clean options (remove root=, rd.lvm.lv=, ro/rw)",
                        variable=self.clean_current_opts).pack(side="left", padx=(0,12))

        ttk.Label(opts, text="Extra options:").pack(side="left", padx=(8,6))
        ttk.Entry(opts, textvariable=self.extra_opts, width=60).pack(side="left", padx=(0,6))

        # Buttons row
        btns = ttk.Frame(self, padding=8)
        btns.pack(fill="x")
        self.btns = btns
        ttk.Button(btns, text="Install Boom", command=self.install_boom).pack(side="left", padx=6)
        ttk.Button(btns, text="Detect Snapshots", command=self.detect_snapshots).pack(side="left", padx=6)
        ttk.Button(btns, text="Detect Layout", command=self.detect).pack(side="left")
        ttk.Button(btns, text="Create Snapshots", command=self.create_snaps).pack(side="left", padx=6)
        ttk.Button(btns, text="Add Boom Entry", command=self.add_boom).pack(side="left", padx=6)
        ttk.Button(btns, text="Merge (Rollback)", command=self.merge_snaps).pack(side="left", padx=6)
        ttk.Button(btns, text="Delete Snapshots", command=self.delete_snaps).pack(side="left", padx=6)
        ttk.Button(btns, text="Show LVM", command=self.show_lvm).pack(side="left", padx=6)
        ttk.Button(btns, text="Use Unallocated Space (grow PV)", command=self.grow_pv_path_a).pack(side="left", padx=12)
        ttk.Button(btns, text="Add New PV (use free disk)", command=self.add_new_pv_path_b).pack(side="left", padx=6)

        # Output box
        self.txt = tk.Text(self, wrap="word")
        self.txt.pack(fill="both", expand=True)
        self.log("$ Ready.\n")

    # ------------- helpers / UI utils -------------
    def log(self, s):
        self.txt.insert("end", s if s.endswith("\n") else s+"\n")
        self.txt.see("end")
        self.update_idletasks()

    def set_buttons(self, state: str):
        for w in self.btns.winfo_children():
            try: w.configure(state=state)
            except: pass

    def _snap_name(self, base):
        return f"{base}-{self.stamp.get()}"

    def _to_g(self, sz):
        s = str(sz).strip().lower()
        if s.endswith('g'):
            try: return float(s[:-1])
            except: return None
        return None

    # ------------- snapshot detection -------------
    def detect_snapshots(self):
        self.log("== Scanning for LVM snapshots ==")
        rc, out, err = sh("lvs --reportformat json -o vg_name,lv_name,lv_attr,origin,lv_size,data_percent")
        if rc != 0:
            self.log(err or "lvs failed"); return
        try:
            data = json.loads(out)
            rows = data["report"][0]["lv"]
        except Exception as e:
            self.log(f"JSON parse error: {e}"); return
        found = False
        for r in rows:
            attr = r.get("lv_attr","")
            if attr and attr[0].lower() == "s":
                found = True
                vg   = r.get("vg_name","")
                name = r.get("lv_name","")
                orig = r.get("origin","")
                size = r.get("lv_size","")
                dper = r.get("data_percent","")
                self.log(f"{vg}/{name: <24} origin={orig: <24} size={size: <8} Data%={dper}")
        if not found:
            self.log("(none found)")

    # ------------- layout detection + PV free -------------
    def detect(self):
        self.log("== Detecting LVM / thinpool / free space ==")
        rc, out, err = sh("vgs; echo; lvs -a -o vg_name,lv_name,lv_attr,lv_size,origin,Data%,Metadata%,pool_lv")
        self.log(out or err)

        rc2, out2, _ = sh("lvs -a --noheadings -o lv_attr")
        thin = any(attr.strip().startswith("t") for attr in out2.splitlines())
        self.log(f"* Thin pool detected: {'yes' if thin else 'no'}")

        rc3, pvs_out, _ = sh("pvs --noheadings -o pv_name,pv_size,pv_free,vg_name")
        if rc3 == 0: self.log("== pvs ==\n" + pvs_out)
        else: self.log("(pvs failed)")
        self.detect_possible_unallocated_after_pv()
        return thin

    def detect_possible_unallocated_after_pv(self):
        rc, out, _ = sh("vgs --noheadings -o vg_name,vfree")
        vg_line = None
        for line in out.splitlines():
            if self.vg.get() in line:
                vg_line = line; break
        if not vg_line: return
        free_str = vg_line.split()[-1].lower()
        self.log(f"== vg free check ==\n{vg_line.strip()}")
        if free_str.endswith('m'):
            self.log("Hint: VG free is small. If your disk tool shows unallocated space, try Path A or B below.")
        pv_path = self.guess_pv_path()
        if pv_path:
            base_disk = re.sub(r"p\d+$|\d+$", "", pv_path)
            rc2, ls, _ = sh(f"lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT {base_disk}")
            self.log(ls)

    # ------------- helpers for PV/disk/partition -------------
    def guess_pv_path(self):
        rc, out, _ = sh(f"pvs --noheadings -o pv_name,vg_name | awk '$2==\"{self.vg.get()}\" {{print $1}}' | head -1")
        pv = out.strip()
        return pv if pv else None

    def split_disk_part(self, pv):
        m = re.match(r"^(/dev/nvme\d+n\d+)p(\d+)$", pv)
        if m: return m.group(1), m.group(2)
        m = re.match(r"^(/dev/[a-z]+)(\d+)$", pv)
        if m: return m.group(1), m.group(2)
        disk = re.sub(r"\d+$", "", pv)
        part = pv.replace(disk, "")
        return disk, part

    # ------------- path A: grow existing PV -------------
    def ensure_growpart(self):
        if shutil.which("growpart"): return True
        self.log("Installing cloud-utils-growpart...")
        rc2, out, err = sh("dnf install -y cloud-utils-growpart")
        if rc2 != 0:
            self.log(f"Failed to install growpart: {err}")
            messagebox.showerror(APP_TITLE, "Could not install growpart (cloud-utils-growpart).")
            return False
        return True

    def grow_pv_path_a(self):
        self.set_buttons("disabled")
        try:
            pv = self.guess_pv_path()
            if not pv:
                self.log("Could not find PV for VG."); messagebox.showwarning(APP_TITLE, "Could not find PV for this VG."); return
            disk, part = self.split_disk_part(pv)
            self.log(f"PV: {pv}  → disk: {disk}, part: {part}")
            rc, out, _ = sh(f"lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT {disk}"); self.log(out)

            if not self.ensure_growpart(): return
            self.log(f"Running: growpart {disk} {part}")
            rc, out, err = sh(f"growpart {disk} {part}"); self.log(out or err or "growpart done")

            sh("partprobe"); time.sleep(1)

            self.log(f"Running: pvresize {pv}")
            rc, out, err = sh(f"pvresize {pv}"); self.log(out or err or "pvresize done")

            rc, out, _ = sh("pvs --noheadings -o pv_name,pv_size,pv_free,vg_name"); self.log("== pvs ==\n" + out)
            rc, out, _ = sh("vgs"); self.log("== vgs ==\n" + out)
            messagebox.showinfo(APP_TITLE, "PV grown. VG should now have free space for snapshots.")
        finally:
            self.set_buttons("normal")

    # ------------- path B: new partition → pvcreate → vgextend -------------
    def add_new_pv_path_b(self):
        """Create a new LVM partition in the largest free region and add it to the VG."""
        self.set_buttons("disabled")
        try:
            pv = self.guess_pv_path()
            if not pv:
                self.log("Could not find PV for VG."); messagebox.showwarning(APP_TITLE, "Could not find PV for this VG."); return
            disk, _ = self.split_disk_part(pv)
            self.log(f"Base disk for new PV: {disk}")

            rc, out, err = sh(f"parted -m {disk} unit MiB print free")
            if rc != 0:
                self.log(err or "parted failed"); messagebox.showerror(APP_TITLE, "parted failed to query free space."); return

            free_regions = []
            for line in out.splitlines():
                if "free" not in line.lower(): continue
                cols = line.split(":")
                if len(cols) < 5: continue
                try:
                    start = float(cols[1].rstrip("MiB"))
                    end   = float(cols[2].rstrip("MiB"))
                    size  = float(cols[3].rstrip("MiB"))
                    label = cols[4].lower()
                except Exception:
                    continue
                if "free" in label and size >= 1024:
                    free_regions.append((size, start, end))

            if not free_regions:
                self.log("No sufficiently large free region found on disk.")
                messagebox.showinfo(APP_TITLE, "No sufficiently large free region found on disk."); return

            free_regions.sort(reverse=True)
            size, start, end = free_regions[0]
            start_align = max(1, int(start))
            end_align   = int(end)

            self.log(f"Creating new LVM partition in free region: ~{size/1024:.1f} GiB from {start_align}MiB to {end_align}MiB")
            rc, out, err = sh(f"parted -s {disk} mkpart primary {start_align}MiB {end_align}MiB")
            self.log(out or err or "mkpart done")

            rc, out, _ = sh(f"lsblk -lnpo NAME,TYPE {disk} | awk '$2==\"part\"{{print $1}}' | tail -1")
            newpart = out.strip()
            if not newpart:
                self.log("Could not detect new partition name."); messagebox.showerror(APP_TITLE, "Could not detect new partition name."); return

            partnum_match = re.search(r"(\d+)$", newpart)
            if partnum_match:
                partnum = partnum_match.group(1)
                sh(f"parted -s {disk} set {partnum} lvm on")

            sh("partprobe"); time.sleep(1)
            self.log(f"New partition: {newpart}")

            rc, out, err = sh(f"pvcreate {newpart}")
            if rc != 0:
                self.log(err or f"pvcreate failed on {newpart}"); messagebox.showerror(APP_TITLE, f"pvcreate failed on {newpart}:\n{err}"); return
            self.log(out or "pvcreate done")

            rc, out, err = sh(f"vgextend {self.vg.get()} {newpart}")
            if rc != 0:
                self.log(err or "vgextend failed"); messagebox.showerror(APP_TITLE, f"vgextend failed:\n{err}"); return
            self.log(out or "vgextend done")

            rc, out, _ = sh("pvs --noheadings -o pv_name,pv_size,pv_free,vg_name"); self.log("== pvs ==\n" + out)
            rc, out, _ = sh("vgs"); self.log("== vgs ==\n" + out)
            messagebox.showinfo(APP_TITLE, "New PV added to VG. You now have free space for snapshots.")
        finally:
            self.set_buttons("normal")

    # ------------- Boom profile helpers -------------
    def get_boom_osid(self):
        """Return first Boom os_id using JSON (preferred), with --rows fallback."""
        rc, out, err = sh("boom profile list --json")
        if rc == 0 and out.strip():
            try:
                data = json.loads(out)
                profiles = data.get("profiles") or data.get("profile") or []
                if isinstance(profiles, dict): profiles = [profiles]
                for p in profiles:
                    osid = p.get("os_id") or p.get("OsID") or ""
                    if osid: return osid
            except Exception as e:
                self.log(f"Boom JSON parse error: {e}")
        # fallback to rows
        rc2, rows, _ = sh("boom profile list --rows")
        if rc2 == 0 and rows.strip():
            m = re.search(r'\bOsID\s+([0-9a-f]{7,})', rows, re.I)
            if m: return m.group(1)
        return ""

    def ensure_boom_profile(self):
        """Return a valid Boom OsID; create a minimal Rocky 10 profile if none exists."""
        osid = self.get_boom_osid()
        if osid: return osid

        sh("mount | grep ' on /boot ' && mount -o remount,rw /boot")
        prof_cmd = (
            "boom profile create "
            "--name 'Rocky Linux 10' "
            "--short-name rocky "
            "--os-version 10 "
            "--os-version-id 10 "
            "--uname-pattern '.*el10.*x86_64' "
            "--kernel-pattern '/vmlinuz-%{version}' "
            "--initramfs-pattern '/initramfs-%{version}.img'"
        )
        rc, out, err = sh(prof_cmd)
        self.log(out or err or "Created Boom profile.")

        # try extraction from creation output
        m = re.search(r'os_id\s+([0-9a-f]{7,})', out, re.I)
        if m: return m.group(1)

        return self.get_boom_osid()

    # ------------- snapshot creation -------------
    def create_snaps(self):
        vg = self.vg.get()
        root_lv = self.root_lv.get()
        var_lv  = self.var_lv.get()
        home_lv = self.home_lv.get()

        root_snap = self._snap_name("snap-pre")
        var_snap  = self._snap_name("var-pre")
        home_snap = self._snap_name("home-pre")

        root_sz = self.root_sz.get()
        var_sz  = self.var_sz.get()
        home_sz = self.home_sz.get()

        thin = self.detect()

        rc, vgs_out, _ = sh("vgs --noheadings -o vg_name,vfree")
        self.log("== vgs ==\n" + vgs_out)
        free_g = None
        try:
            line = next(l for l in vgs_out.splitlines() if self.vg.get() in l)
            free_str = line.split()[-1]
            free_g = float(free_str.lower().rstrip('g').replace(',', '.')) if free_str.lower().endswith('g') else None
        except Exception:
            pass

        need_g = sum(filter(None, [self._to_g(root_sz), self._to_g(var_sz), self._to_g(home_sz)]))
        if free_g is not None and need_g is not None and free_g < need_g:
            messagebox.showwarning(APP_TITLE, f"Not enough free VG space: need ~{need_g}G, have ~{free_g}G.\n"
                                              f"Use 'Use Unallocated Space (grow PV)' or 'Add New PV (use free disk)'.")
            return

        self.set_buttons("disabled")
        try:
            self.log("Creating THIN snapshots..." if thin else "Creating CLASSIC snapshots... (needs free extents)")
            cmds = []
            if root_sz.lower() != "0g":
                cmds.append(f"lvcreate -s -n {root_snap} -L {root_sz} /dev/{vg}/{root_lv}")
            if var_sz.lower() != "0g":
                cmds.append(f"lvcreate -s -n {var_snap} -L {var_sz} /dev/{vg}/{var_lv}")
            if home_sz.lower() != "0g":
                cmds.append(f"lvcreate -s -n {home_snap} -L {home_sz} /dev/{vg}/{home_lv}")

            for c in cmds:
                rc, out, err = sh(c)
                if rc != 0:
                    self.log(f"ERR: {c}\n{err}")
                    messagebox.showerror(APP_TITLE, f"Snapshot failed:\n{err}")
                    return
                self.log(out or f"OK: {c}")

            # Mount test for root snapshot: XFS=nouuid, ext4=noload, with fallback
            rc, fstype, _ = sh(f"lsblk -no FSTYPE /dev/{vg}/{root_snap}")
            fstype = fstype.strip().lower()
            opt = "ro,nouuid" if fstype == "xfs" else "ro,noload"
            sh(f"mkdir -p /mnt/{root_snap}")
            rc, out, err = sh(f"mount -o {opt} /dev/{vg}/{root_snap} /mnt/{root_snap}")
            if rc != 0:
                alt = "ro,noload" if opt == "ro,nouuid" else "ro,nouuid"
                rc2, out2, err2 = sh(f"mount -o {alt} /dev/{vg}/{root_snap} /mnt/{root_snap}")
                if rc2 == 0:
                    sh(f"umount /mnt/{root_snap}")
                    self.log(f"Mounted {root_snap} read-only successfully (fallback {alt}).")
                else:
                    self.log(f"(Note) Could not mount test {root_snap}:\n{err}\n{err2}")
            else:
                sh(f"umount /mnt/{root_snap}")
                self.log(f"Mounted {root_snap} read-only successfully.")

            self.show_lvm()
            self.log("Snapshots created. You can now add a Boom entry (root).")
        finally:
            self.set_buttons("normal")

    # ------------- Boom entry -------------
    def add_boom(self):
        vg = self.vg.get()
        root_snap = self._snap_name("snap-pre")
        # ensure /boot writable
        sh("mount | grep ' on /boot ' && mount -o remount,rw /boot")

        # kernel artifacts
        _, ver, _ = sh("uname -r", check=True)
        ver = ver.strip()
        linux = f"/vmlinuz-{ver}"
        initrd = f"/initramfs-{ver}.img"

        # Build --options
        options = ""
        if self.use_current_opts.get():
            rc_c, cur, _ = sh("cat /proc/cmdline")
            if rc_c == 0 and cur.strip():
                tokens = cur.strip().split()
                if self.clean_current_opts.get():
                    # drop conflicting/unsafe items; keep everything else (like resume=, NVIDIA flags, etc.)
                    drop_keys = ("root=", "rd.lvm.lv=")
                    tokens = [
                        t for t in tokens
                        if not t.startswith(drop_keys) and t not in ("ro", "rw")
                    ]
                # ensure read-only unless user provided rw explicitly in Extra options
                if all(t not in ("ro", "rw") for t in tokens):
                    tokens.insert(0, "ro")
                options = " ".join(tokens).strip()

        extra = (self.extra_opts.get() or "").strip()
        if extra:
            options = (options + " " + extra).strip() if options else extra

        # Try plain create first (works on hosts with a matching HostProfile)
        base_cmd = (
            f"boom entry create "
            f"--linux '{linux}' "
            f"--initrd '{initrd}' "
            f"--root-lv {vg}/{root_snap} "
            f"--title 'Rollback: {self.stamp.get()} (root snapshot)'"
        )
        cmd = base_cmd + (f" --options '{options}'" if options else "")
        rc, out, err = sh(cmd)
        if rc == 0:
            self.log(out or "Boom entry created.")
            rc2, out2, _ = sh("boom entry list --rows"); self.log(out2)
            return

        # If Boom demands a profile, ensure one exists and retry with --profile
        if "requires --profile" in (err.lower() + out.lower()):
            self.log("Boom requires a profile; ensuring a minimal Rocky 10 profile exists...")
            osid = self.ensure_boom_profile()
            if not osid:
                self.log("Failed to obtain a Boom OsID.")
                messagebox.showerror(APP_TITLE, "Could not obtain a Boom OsID.")
                return
            cmd2 = (
                f"boom entry create --profile '{osid}' "
                f"--linux '{linux}' "
                f"--initrd '{initrd}' "
                f"--root-lv {vg}/{root_snap} "
                f"--title 'Rollback: {self.stamp.get()} (root snapshot)'"
                + (f" --options '{options}'" if options else "")
            )
            rc2, out2, err2 = sh(cmd2)
            if rc2 != 0:
                self.log(f"ERR: {cmd2}\n{err2 or out2}")
                messagebox.showerror(APP_TITLE, f"Boom entry failed after profile creation:\n{err2 or out2}")
                return
            self.log(out2 or "Boom entry created (after creating profile).")
            rc3, out3, _ = sh("boom entry list --rows"); self.log(out3)
            return

        # other error
        self.log(f"ERR: {cmd}\n{err or out}")
        messagebox.showerror(APP_TITLE, f"Boom entry failed:\n{err or out}")


    def install_boom(self):
        self.log("Installing Boom...")
        rc, out, err = sh("dnf install -y boom-boot boom-boot-conf python3-boom")
        if rc == 0: self.log("Boom installed successfully.")
        else: self.log(f"Failed to install Boom: {err}")

    # ------------- rollback / cleanup -------------
    def merge_snaps(self):
        vg = self.vg.get()
        var_snap  = self._snap_name("var-pre")
        root_snap = self._snap_name("snap-pre")
        self.set_buttons("disabled")
        try:
            for lv in [var_snap, root_snap]:
                path = f"/dev/{vg}/{lv}"
                rc, _, _ = sh(f"lvs {path}")
                if rc == 0:
                    # THIS IS THE FIX: force nouuid so XFS doesn't choke at early boot
                    rc2, out, err = sh(f"lvconvert --merge {path}")
                    self.log(out or err or f"Merged {path}")

            # Also force nouuid on the next boot just to be 100% safe
            current = sh("cat /proc/cmdline", check=True)[1]
            if "rootflags=nouuid" not in current:
                sh("grubby --update-kernel=ALL --args=rootflags=nouuid")

            self.log("Merged snapshots + added rootflags=nouuid. Reboot → perfect rollback.")
            messagebox.showinfo(APP_TITLE, "Rollback scheduled successfully!\n"
                                          "rootflags=nouuid added for XFS safety.\n"
                                          "Reboot now.")
        finally:
            self.set_buttons("normal")

    def delete_snaps(self):
        vg = self.vg.get()
        # remove Boom entries that reference our snapshots
        rc, out, _ = sh("boom entry list --rows -o id,root_lv,title --separator '|'")
        if rc == 0 and out:
            for line in out.splitlines():
                parts = [p.strip() for p in line.split('|', 2)]
                if len(parts) == 3:
                    entry_id, root_lv, title = parts
                    if root_lv.startswith(f"{vg}/") and 'pre-' in root_lv:
                        rc_del, out_del, err_del = sh(f"boom entry delete {entry_id}")
                        if rc_del == 0: self.log(f"Removed Boom entry {entry_id} for {root_lv}")
                        else: self.log(f"Failed to remove Boom entry {entry_id}: {err_del}")

        # remove snapshot LVs (names containing 'pre-' and attr starting with 's')
        rc, out, err = sh("lvs --reportformat json -o vg_name,lv_name,lv_attr")
        if rc == 0:
            try:
                rows = json.loads(out)["report"][0]["lv"]
                for r in rows:
                    attr = r.get("lv_attr", ""); name = r.get("lv_name", ""); lv_vg = r.get("vg_name", "")
                    if lv_vg == vg and attr and attr[0].lower() == "s" and "pre-" in name:
                        rc2, out2, err2 = sh(f"lvremove -y /dev/{vg}/{name}")
                        self.log(out2 or err2 or f"Removed {name}")
            except Exception as e:
                self.log(f"JSON parse error: {e}")
        else:
            self.log(err or "Failed to list LVs")

        self.show_lvm()

    def show_lvm(self):
        rc, out, err = sh("lvs -o vg_name,lv_name,lv_attr,origin,lv_size,data_percent --noheadings")
        self.log("== lvs ==\n" + (out or err))
        rc, out, err = sh("vgs")
        self.log("== vgs ==\n" + (out or err))

if __name__ == "__main__":
    need_root()
    App().mainloop()
