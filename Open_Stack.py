#!/usr/bin/env python3
import os
import json
import base64
import time
import threading
import requests
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from requests.packages.urllib3.exceptions import InsecureRequestWarning

# Tắt cảnh báo SSL
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

class OpenStackFullLabApp:
    def __init__(self, root):
        self.root = root
        self.root.title("OpenStack REST API Dashboard - UIT NT533 (Lab 1)")
        self.root.geometry("1200x800")

        # Cấu hình Endpoints HTTPS
        self.ep_auth = "https://cloud-identity.uitiot.vn/v3/auth/tokens"
        self.ep_compute = "https://cloud-compute.uitiot.vn/v2.1"
        self.ep_network = "https://cloud-network.uitiot.vn/v2.0"
        self.ep_image = "https://cloud-image.uitiot.vn/v2/images"
        self.ep_lb = "https://cloud-loadbalancer.uitiot.vn/v2.0/lbaas"

        self.token = None
        self.project_id = None
        self.ext_net_id = None # ID của mạng External để cấp Floating IP và Router GW
        
        # Lưu trữ ID máy ảo và cấu trúc Dropdown
        self.vm_list = []
        self.map_img = {}
        self.map_flv = {}
        self.map_net = {}

        self.setup_gui()
        self.load_env()

    def log(self, msg):
        self.txt_log.insert(tk.END, msg + "\n")
        self.txt_log.see(tk.END)
        self.root.update_idletasks()

    def load_env(self):
        self.ent_user.insert(0, os.environ.get("OS_USERNAME", ""))
        self.ent_pass.insert(0, os.environ.get("OS_PASSWORD", ""))
        self.ent_proj.insert(0, os.environ.get("OS_PROJECT_NAME", "NT533.R12.G1"))

    def get_headers(self):
        return {"Content-Type": "application/json", "X-Auth-Token": self.token}

    def run_async(self, func, *args):
        threading.Thread(target=func, args=args, daemon=True).start()

    # ================== KHỐI 1: XÁC THỰC & TẢI DỮ LIỆU ==================
    def api_get_token(self):
        self.run_async(self._worker_get_token)

    def _worker_get_token(self):
        user = self.ent_user.get().strip()
        pwd = self.ent_pass.get().strip()
        proj = self.ent_proj.get().strip()
        if not pwd: return messagebox.showwarning("Cảnh báo", "Vui lòng nhập mật khẩu!")

        self.log("[...] Đang gửi POST request lấy Token...")
        payload = {
            "auth": {
                "identity": {"methods": ["password"], "password": {"user": {"name": user, "domain": {"name": "Default"}, "password": pwd}}},
                "scope": {"project": {"name": proj, "domain": {"name": "Default"}}}
            }
        }
        try:
            res = requests.post(self.ep_auth, json=payload, verify=False, timeout=10)
            if res.status_code == 201:
                self.token = res.headers.get("X-Subject-Token")
                self.project_id = res.json()["token"]["project"]["id"]
                self.log("[+] Xác thực thành công! Hãy bấm 'Tải Dữ Liệu' để tiếp tục.")
            else:
                self.log(f"[-] LỖI XÁC THỰC: {res.text}")
        except Exception as e:
            self.log(f"[-] LỖI KẾT NỐI: {str(e)}")

    def api_load_data(self):
        if not self.token: return self.log("[-] Hãy lấy Token trước!")
        self.run_async(self._worker_load_data)

    def _worker_load_data(self):
        self.log("\n--- [GET] TẢI DỮ LIỆU TÀI NGUYÊN (YC 1-4) ---")
        try:
            imgs = requests.get(self.ep_image, headers=self.get_headers(), verify=False).json().get("images", [])
            flvs = requests.get(f"{self.ep_compute}/flavors/detail", headers=self.get_headers(), verify=False).json().get("flavors", [])
            nets = requests.get(f"{self.ep_network}/networks", headers=self.get_headers(), verify=False).json().get("networks", [])
            vms = requests.get(f"{self.ep_compute}/servers", headers=self.get_headers(), verify=False).json().get("servers", [])

            self.map_img = {f"{i.get('name', i['id'])}": i['id'] for i in imgs}
            self.map_flv = {f"{f['name']} (RAM: {f['ram']}MB, Disk: {f['disk']}GB)": f['id'] for f in flvs}
            self.map_net = {f"{n.get('name', n['id'])}": n['id'] for n in nets}
            self.vm_list = [v['id'] for v in vms]

            # Tìm External Network
            for n in nets:
                if n.get("router:external") == True:
                    self.ext_net_id = n["id"]
                    break

            self.log(f"[+] Đã tải: {len(imgs)} Images, {len(flvs)} Flavors, {len(nets)} Networks, {len(vms)} Instances.")
            self.root.after(0, self.update_comboboxes)
        except Exception as e:
            self.log(f"[-] Lỗi tải dữ liệu: {str(e)}")

    def update_comboboxes(self):
        self.cbo_img['values'] = list(self.map_img.keys())
        if self.map_img: self.cbo_img.current(0)
        self.cbo_flv['values'] = list(self.map_flv.keys())
        if self.map_flv: self.cbo_flv.current(0)
        self.cbo_net['values'] = list(self.map_net.keys())
        if self.map_net: self.cbo_net.current(0)

    # ================== KHỐI 2: TẠO VM THỦ CÔNG QUA DROPDOWN ==================
    def api_create_custom_vm(self):
        if not self.token: return self.log("[-] Hãy lấy Token trước!")
        self.run_async(self._worker_create_custom_vm)

    def _worker_create_custom_vm(self):
        vm_name = self.ent_vm_name.get().strip()
        if not vm_name or not self.cbo_img.get(): return
        
        img_id = self.map_img[self.cbo_img.get()]
        flv_id = self.map_flv[self.cbo_flv.get()]
        net_id = self.map_net[self.cbo_net.get()]
        vol_size = int(self.ent_vol.get().strip() or 20)

        self.log(f"\n🚀 TẠO CUSTOM VM: [{vm_name}] (Vol: {vol_size}GB)")
        vm_payload = {
            "server": {
                "name": vm_name, "flavorRef": flv_id, "networks": [{"uuid": net_id}],
                "block_device_mapping_v2": [{"boot_index": 0, "uuid": img_id, "source_type": "image", "destination_type": "volume", "volume_size": vol_size, "delete_on_termination": True}]
            }
        }
        res = requests.post(f"{self.ep_compute}/servers", json=vm_payload, headers=self.get_headers(), verify=False)
        if res.status_code in [200, 201, 202]:
            self.log(f"[+] Thành công! Máy ảo ID: {res.json()['server']['id']}")
        else:
            self.log(f"[-] Lỗi tạo VM: {res.text}")

    # ================== KHỐI 3: KỊCH BẢN TỰ ĐỘNG LAB 1 (YC 5-8) ==================
    def auto_deploy_lab(self):
        if not self.token: return self.log("[-] Hãy lấy Token trước!")
        self.run_async(self._worker_auto_deploy_lab)

    def _worker_auto_deploy_lab(self):
        grp = self.ent_grp.get().strip()
        self.log(f"\n🚀 BẮT ĐẦU AUTO DEPLOY (Yêu cầu 5 & 6) CHO NHÓM {grp}...")
        try:
            # 1. YC 5: Tạo Network & Subnet
            net_res = requests.post(f"{self.ep_network}/networks", json={"network": {"name": f"nhom_{grp}_net", "admin_state_up": True}}, headers=self.get_headers(), verify=False).json()
            net_id = net_res["network"]["id"]
            self.log(f"[1] Tạo Network thành công: {net_id}")

            sub_res = requests.post(f"{self.ep_network}/subnets", json={"subnet": {"name": f"nhom_{grp}_sub", "network_id": net_id, "ip_version": 4, "cidr": "192.168.10.0/24"}}, headers=self.get_headers(), verify=False).json()
            sub_id = sub_res["subnet"]["id"]
            self.log(f"[2] Tạo Subnet thành công: {sub_id}")

            # 2. YC 5: Tạo Router & Nối External
            if self.ext_net_id:
                r_payload = {"router": {"name": f"nhom_{grp}_router", "external_gateway_info": {"network_id": self.ext_net_id}}}
                r_res = requests.post(f"{self.ep_network}/routers", json=r_payload, headers=self.get_headers(), verify=False).json()
                r_id = r_res["router"]["id"]
                requests.put(f"{self.ep_network}/routers/{r_id}/add_router_interface", json={"subnet_id": sub_id}, headers=self.get_headers(), verify=False)
                self.log(f"[3] Tạo Router & Nối Ext-Net thành công: {r_id}")
            else:
                self.log("[3] Cảnh báo: Không tìm thấy External Network để cấp Gateway.")

            # 3. YC 6: Tạo VM kèm Web Server (User Data)
            img_id = list(self.map_img.values())[0]
            flv_id = list(self.map_flv.values())[0]  # Disk=0 cần Volume-backed
            script = f"#!/bin/bash\napt update && apt install -y nginx\necho '<h1>Nhom {grp} - IP: $(hostname -I)</h1>' > /var/www/html/index.html"
            b64_script = base64.b64encode(script.encode()).decode()

            vm_payload = {
                "server": {
                    "name": f"nhom_{grp}_web_1", "flavorRef": flv_id, "networks": [{"uuid": net_id}], "user_data": b64_script,
                    "block_device_mapping_v2": [{"boot_index": 0, "uuid": img_id, "source_type": "image", "destination_type": "volume", "volume_size": 15, "delete_on_termination": True}]
                }
            }
            vm_res = requests.post(f"{self.ep_compute}/servers", json=vm_payload, headers=self.get_headers(), verify=False).json()
            vm_id = vm_res["server"]["id"]
            self.vm_list.append(vm_id)
            self.log(f"[4] Đã tạo Web Instance (ID: {vm_id})")

            # 4. YC 6: Cấp Floating IP (Chờ VM boot 5s)
            if self.ext_net_id:
                self.log(f"[5] Đang cấp Floating IP cho Web Server...")
                time.sleep(5) 
                fip_res = requests.post(f"{self.ep_network}/floatingips", json={"floatingip": {"floating_network_id": self.ext_net_id}}, headers=self.get_headers(), verify=False).json()
                fip_addr = fip_res["floatingip"]["floating_ip_address"]
                requests.post(f"{self.ep_compute}/servers/{vm_id}/action", json={"addFloatingIp": {"address": fip_addr}}, headers=self.get_headers(), verify=False)
                self.log(f"   -> Đã gán Floating IP: {fip_addr}")

            self.log("✅ AUTO DEPLOY YÊU CẦU 5 & 6 HOÀN TẤT!")
        except Exception as e:
            self.log(f"[-] Lỗi Auto Deploy: {str(e)}")

    def api_create_lb(self):
        if not self.token: return
        self.run_async(self._worker_create_lb)
    
    def _worker_create_lb(self):
        grp = self.ent_grp.get().strip()
        self.log(f"\n⚖️ (YC 7) Đang tạo Load Balancer cho nhóm {grp}...")
        try:
            nets = requests.get(f"{self.ep_network}/subnets", headers=self.get_headers(), verify=False).json().get("subnets", [])
            target_sub = [s for s in nets if f"nhom_{grp}_sub" in s["name"]]
            if not target_sub: return self.log("[-] Chưa tìm thấy Subnet. Hãy Auto Deploy trước!")
            
            lb_payload = {"loadbalancer": {"name": f"lb_{grp}", "vip_subnet_id": target_sub[0]["id"]}}
            res = requests.post(f"{self.ep_lb}/loadbalancers", json=lb_payload, headers=self.get_headers(), verify=False)
            if res.status_code in [200, 201, 202]:
                self.log(f"[+] Tạo Load Balancer thành công: {res.json()['loadbalancer']['id']}")
            else:
                self.log(f"[-] Lỗi tạo LB: {res.text}")
        except Exception as e:
            self.log(f"[-] Lỗi LB: {str(e)}")

    # (YC 8) Tăng giảm máy ảo
    def api_scale(self, action="up"):
        if not self.token: return
        threading.Thread(target=self._worker_scale, args=(action,), daemon=True).start()

    def _worker_scale(self, action):
        if action == "up":
            self.log("\n➕ (YC 8) Scale Up: Thêm 1 máy ảo...")
            img_id = list(self.map_img.values())[0]
            flv_id = list(self.map_flv.values())[0]
            net_id = list(self.map_net.values())[0] # Lấy net gần nhất
            
            payload = {
                "server": {
                    "name": f"scale_vm_{len(self.vm_list)+1}", "flavorRef": flv_id, "networks": [{"uuid": net_id}],
                    "block_device_mapping_v2": [{"boot_index": 0, "uuid": img_id, "source_type": "image", "destination_type": "volume", "volume_size": 10, "delete_on_termination": True}]
                }
            }
            res = requests.post(f"{self.ep_compute}/servers", json=payload, headers=self.get_headers(), verify=False)
            if res.status_code in [200, 201, 202]:
                self.vm_list.append(res.json()["server"]["id"])
                self.log(f"[+] Đã Scale Up VM: {res.json()['server']['id']}")
        else:
            if not self.vm_list: return self.log("[-] Không còn VM để Scale Down!")
            vm_id = self.vm_list.pop()
            self.log(f"\n➖ (YC 8) Scale Down: Xóa máy ảo {vm_id}...")
            requests.delete(f"{self.ep_compute}/servers/{vm_id}", headers=self.get_headers(), verify=False)
            self.log("[+] Đã xóa thành công!")

    # ================== GIAO DIỆN GUI (CÓ TABS) ==================
    def setup_gui(self):
        # Notebook (Tabs)
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="x", padx=10, pady=5)

        tab1 = ttk.Frame(notebook, padding=10)
        tab2 = ttk.Frame(notebook, padding=10)
        tab3 = ttk.Frame(notebook, padding=10)

        notebook.add(tab1, text=" 1. Đăng nhập & Tải dữ liệu ")
        notebook.add(tab2, text=" 2. Builder (Dropdown) ")
        notebook.add(tab3, text=" 3. Kịch bản Lab 1 (Tự động) ")

        # --- TAB 1: AUTH ---
        ttk.Label(tab1, text="User:").grid(row=0, column=0)
        self.ent_user = ttk.Entry(tab1, width=15)
        self.ent_user.grid(row=0, column=1, padx=5)

        ttk.Label(tab1, text="Pass:").grid(row=0, column=2)
        self.ent_pass = ttk.Entry(tab1, width=20, show="*")
        self.ent_pass.grid(row=0, column=3, padx=5)

        ttk.Label(tab1, text="Project:").grid(row=0, column=4)
        self.ent_proj = ttk.Entry(tab1, width=15)
        self.ent_proj.grid(row=0, column=5, padx=5)

        ttk.Button(tab1, text="🔑 1. Lấy Token", command=self.api_get_token).grid(row=0, column=6, padx=10)
        ttk.Button(tab1, text="📥 2. Tải Dữ liệu (Images, Flavors, Nets)", command=self.api_load_data).grid(row=0, column=7)

        # --- TAB 2: BUILDER MÔ PHỎNG HTML ---
        ttk.Label(tab2, text="Tên máy ảo:").grid(row=0, column=0, sticky="e", pady=5)
        self.ent_vm_name = ttk.Entry(tab2, width=30)
        self.ent_vm_name.insert(0, "Ubuntu_Custom_VM")
        self.ent_vm_name.grid(row=0, column=1, padx=5, sticky="w")

        ttk.Label(tab2, text="Chọn Image:").grid(row=1, column=0, sticky="e", pady=5)
        self.cbo_img = ttk.Combobox(tab2, state="readonly", width=50)
        self.cbo_img.grid(row=1, column=1, padx=5, sticky="w")

        ttk.Label(tab2, text="Chọn Flavor:").grid(row=2, column=0, sticky="e", pady=5)
        self.cbo_flv = ttk.Combobox(tab2, state="readonly", width=50)
        self.cbo_flv.grid(row=2, column=1, padx=5, sticky="w")

        ttk.Label(tab2, text="Chọn Network:").grid(row=3, column=0, sticky="e", pady=5)
        self.cbo_net = ttk.Combobox(tab2, state="readonly", width=50)
        self.cbo_net.grid(row=3, column=1, padx=5, sticky="w")

        ttk.Label(tab2, text="Ổ đĩa (GB):").grid(row=4, column=0, sticky="e", pady=5)
        self.ent_vol = ttk.Entry(tab2, width=15)
        self.ent_vol.insert(0, "20")
        self.ent_vol.grid(row=4, column=1, padx=5, sticky="w")

        ttk.Button(tab2, text="💻 Tạo Máy Ảo Theo Yêu Cầu", command=self.api_create_custom_vm).grid(row=4, column=2, padx=20)

        # --- TAB 3: AUTO DEPLOY LAB 1 ---
        ttk.Label(tab3, text="Tên Nhóm:").pack(side="left", padx=5)
        self.ent_grp = ttk.Entry(tab3, width=8)
        self.ent_grp.insert(0, "12")
        self.ent_grp.pack(side="left")

        ttk.Button(tab3, text="🚀 AUTO DEPLOY (YC 5, 6)", command=self.auto_deploy_lab).pack(side="left", padx=10)
        ttk.Button(tab3, text="⚖️ Tạo Load Balancer (YC 7)", command=self.api_create_lb).pack(side="left", padx=10)
        ttk.Button(tab3, text="➕ Scale Up (YC 8)", command=lambda: self.api_scale("up")).pack(side="left", padx=5)
        ttk.Button(tab3, text="➖ Scale Down (YC 8)", command=lambda: self.api_scale("down")).pack(side="left", padx=5)

        # --- LOG CONSOLE ---
        f_log = ttk.LabelFrame(self.root, text=" Hệ Thống Log REST API (Console) ")
        f_log.pack(fill="both", expand=True, padx=10, pady=5)
        self.txt_log = scrolledtext.ScrolledText(f_log, bg="#1e1e1e", fg="#00ff00", font=("Consolas", 10))
        self.txt_log.pack(fill="both", expand=True)

if __name__ == "__main__":
    root = tk.Tk()
    app = OpenStackFullLabApp(root)
    root.mainloop()