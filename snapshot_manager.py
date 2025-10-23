#!/usr/bin/env python3
# snapshot_manager.py — LVM + Boom GUI for Rocky 10 (XFS, thin or classic)
# Run as: sudo python3 snapshot_manager.py

import os, subprocess, sys, time
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
        self.geometry("1300x720")
        self.minsize(900, 640)

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

        ttk.Separator(frm, orient="horizontal").grid(row=row, column=0, columnspan=6, sticky="ew", pady=6); row += 1

        for label, var in [("root snap size", self.root_sz), ("var snap size", self.var_sz), ("home snap size", self.home_sz)]:
            ttk.Label(frm, text=label, width=14).grid(row=row, column=0, sticky="w")
            ttk.Entry(frm, textvariable=var, width=10).grid(row=row, column=1, sticky="w", padx=6)
            row += 1

        ttk.Label(frm, text="STAMP").grid(row=row, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.stamp, width=18).grid(row=row, column=1, sticky="w", padx=6)
        row += 1

        # Buttons row
        btns = ttk.Frame(self, padding=8)
        btns.pack(fill="x")
        # Buttons row (add this next to the others)
        ttk.Button(btns, text="Install Boom", command=self.install_boom).pack(side="left", padx=6)
        ttk.Button(btns, text="Detect Snapshots", command=self.detect_snapshots).pack(side="left", padx=6)
        ttk.Button(btns, text="Detect Layout", command=self.detect).pack(side="left")
        ttk.Button(btns, text="Create Snapshots", command=self.create_snaps).pack(side="left", padx=6)
        ttk.Button(btns, text="Add Boom Entry", command=self.add_boom).pack(side="left", padx=6)
        ttk.Button(btns, text="Merge (Rollback)", command=self.merge_snaps).pack(side="left", padx=6)
        ttk.Button(btns, text="Delete Snapshots", command=self.delete_snaps).pack(side="left", padx=6)
        ttk.Button(btns, text="Show LVM", command=self.show_lvm).pack(side="left", padx=6)

        # Output box
        self.txt = tk.Text(self, wrap="word")
        self.txt.pack(fill="both", expand=True)
        self.log("$ Ready.\n")

    def log(self, s):
        self.txt.insert("end", s if s.endswith("\n") else s+"\n")
        self.txt.see("end")
        self.update_idletasks()

    def detect_snapshots(self):
        self.log("== Scanning for LVM snapshots ==")
        rc, out, err = sh("lvs --reportformat json -o vg_name,lv_name,lv_attr,origin,lv_size,data_percent")
        if rc != 0:
            self.log(err or "lvs failed")
            return
        import json
        try:
            data = json.loads(out)
            rows = data["report"][0]["lv"]
        except Exception as e:
            self.log(f"JSON parse error: {e}")
            return
        found = False
        for r in rows:
            attr = r.get("lv_attr","")
            if attr and attr[0].lower() == "s":  # 's' = snapshot LV
                found = True
                vg   = r.get("vg_name","")
                name = r.get("lv_name","")
                orig = r.get("origin","")
                size = r.get("lv_size","")
                dper = r.get("data_percent","")
                self.log(f"{vg}/{name: <24} origin={orig: <24} size={size: <8} Data%={dper}")
        if not found:
            self.log("(none found)")



    def detect(self):
        self.log("== Detecting LVM / thinpool / free space ==")
        rc, out, err = sh("vgs; echo; lvs -a -o vg_name,lv_name,lv_attr,lv_size,origin,Data%,Metadata%,pool_lv")
        self.log(out or err)
        # Try to guess thinpool
        rc2, out2, _ = sh("lvs -a --noheadings -o lv_name,lv_attr | awk '{print $1,$2}'")
        thin = any(("twi-" in line or "twi" in line) for line in out2.splitlines())
        self.log(f"* Thin pool detected: {'yes' if thin else 'no'}")
        return thin

    def _snap_name(self, base):
        return f"{base}-{self.stamp.get()}"

    def create_snaps(self):
        vg = self.vg.get()
        root_lv = self.root_lv.get()
        var_lv  = self.var_lv.get()
        home_lv = self.home_lv.get()

        stamp = self.stamp.get()
        root_snap = self._snap_name("snap-pre")
        var_snap  = self._snap_name("var-pre")
        home_snap = self._snap_name("home-pre")

        root_sz = self.root_sz.get()
        var_sz  = self.var_sz.get()
        home_sz = self.home_sz.get()

        thin = self.detect()
        # Check VFree against requested sizes (rough check for classic LVM)
        rc, vgs_out, _ = sh("vgs --noheadings -o vg_name,vfree")
        self.log("== vgs ==\n" + vgs_out)
        try:
            # crude parse: find our VG line and extract GiB number
            line = next(l for l in vgs_out.splitlines() if self.vg.get() in l)
            free_str = line.split()[-1]  # e.g., '2.00g'
            free_g = float(free_str.lower().rstrip('g'))
        except Exception:
            free_g = None

        def to_g(sz):
            s = sz.strip().lower()
            return float(s.rstrip('g')) if s.endswith('g') else None

        need_g = sum(filter(None, [to_g(self.root_sz.get()), to_g(self.var_sz.get()), to_g(self.home_sz.get())]))
        if free_g is not None and need_g is not None and free_g < need_g:
            messagebox.showwarning(APP_TITLE, f"Not enough free VG space: need ~{need_g}G, have ~{free_g}G.\n"
                                            f"Delete old snapshots or free space first.")

        cmds = []
        if thin:
            # Thin snapshots: -s (snapshot) is implicit; we use --snapshot on thin?
            # In LVM thin, snapshots are thin LVs with origin. lvcreate -s works the same.
            self.log("Creating THIN snapshots...")
        else:
            self.log("Creating CLASSIC snapshots... (needs free extents)")

        if root_sz.lower() != "0g":
            cmds.append(f"lvcreate -s -n {root_snap} -L {root_sz} /dev/{vg}/{root_lv}")
        if var_sz.lower() != "0g":
            cmds.append(f"lvcreate -s -n {var_snap} -L {var_sz} /dev/{vg}/{var_lv}")
        if home_sz.lower() != "0g":
            cmds.append(f"lvcreate -s -n {home_snap} -L {home_sz} /dev/{vg}/{home_lv}")

        for c in cmds:
            rc, out, err = sh(f"sudo {c}")
            if rc != 0:
                self.log(f"ERR: {c}\n{err}")
                messagebox.showerror(APP_TITLE, f"Snapshot failed:\n{err}")
                return
            self.log(out or f"OK: {c}")

        # Optional mount test for root snapshot
        rc, _, _ = sh(f"mkdir -p /mnt/{root_snap}")
        rc, out, err = sh(f"mount -o ro,nouuid /dev/{vg}/{root_snap} /mnt/{root_snap}")
        if rc == 0:
            sh(f"umount /mnt/{root_snap}")
            self.log(f"Mounted {root_snap} read-only successfully.")
        else:
            self.log(f"(Note) Could not mount test {root_snap}: {err}")

        self.show_lvm()
        self.log("Snapshots created. You can now add a Boom entry (root).")

    def add_boom(self):
        vg = self.vg.get()
        root_snap = self._snap_name("snap-pre")
        # Ensure /boot is rw
        sh("mount | grep ' on /boot ' && mount -o remount,rw /boot")
        rc, ver, _ = sh("uname -r", check=True)
        ver = ver.strip()
        linux = f"/vmlinuz-{ver}"
        initrd = f"/initramfs-{ver}.img"

        cmd = (
            f"boom entry create "
            f"--linux '{linux}' "
            f"--initrd '{initrd}' "
            f"--root-lv {vg}/{root_snap} "
            f"--title 'Rollback: {self.stamp.get()} (root snapshot)'"
        )
        rc, out, err = sh(f"sudo {cmd}")
        if rc != 0:
            self.log(f"ERR: {cmd}\n{err}")
            messagebox.showerror(APP_TITLE, f"Boom entry failed:\n{err}")
            return
        self.log(out or "Boom entry created.")
        sh("boom entry list --rows")
        rc, out2, _ = sh("boom entry list --rows")
        self.log(out2)

    def install_boom(self):
        self.log("Installing Boom...")
        rc, out, err = sh("dnf install -y boom-boot")
        if rc == 0:
            self.log("Boom installed successfully.")
        else:
            self.log(f"Failed to install Boom: {err}")

    def merge_snaps(self):
        vg = self.vg.get()
        var_snap  = self._snap_name("var-pre")
        root_snap = self._snap_name("snap-pre")
        # Merge var first (non-root), then root (completes on reboot)
        for lv in [var_snap, root_snap]:
            path = f"/dev/{vg}/{lv}"
            # Only try if exists
            rc, _, _ = sh(f"lvs {path}")
            if rc == 0:
                rc2, out, err = sh(f"sudo lvconvert --merge {path}")
                self.log(out or err or f"Merged {path}")
        self.log("Merged snapshots. Reboot to complete root rollback.")
        messagebox.showinfo(APP_TITLE, "Merged snapshots.\nReboot to finish root rollback.")

    def delete_snaps(self):
        vg = self.vg.get()
        
        # Remove all Boom entries referencing snapshots in this VG
        rc, out, _ = sh("boom entry list -o id,title,root_lv")
        if rc == 0:
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 3:
                    entry_id, title, root_lv = parts[0], ' '.join(parts[1:-1]), parts[-1]
                    if root_lv.startswith(f"{vg}/") and 'pre-' in root_lv:
                        rc_del, _, err_del = sh(f"boom entry delete {entry_id}")
                        if rc_del == 0:
                            self.log(f"Removed Boom entry {entry_id} for {root_lv}")
                        else:
                            self.log(f"Failed to remove Boom entry {entry_id}: {err_del}")
        
        # Find and remove all snapshots with 'pre-' in name
        rc, out, err = sh("lvs --reportformat json -o vg_name,lv_name,lv_attr")
        if rc == 0:
            import json
            try:
                data = json.loads(out)
                rows = data["report"][0]["lv"]
                for r in rows:
                    attr = r.get("lv_attr", "")
                    name = r.get("lv_name", "")
                    lv_vg = r.get("vg_name", "")
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
