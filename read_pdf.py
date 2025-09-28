# quiz_generator.py
# 功能：
# 1. 打开 PDF，从第二页开始逐页截图，用户手动输入题号/确认保存
# 2. 保存为 Q<题号>.png，若同一题跨页则追加 -p<原页号>
# 3. 结束时自动合并：同一题的多张图合成一个多页 PDF (Q<n>.pdf)

# 依赖：
# pip install pdfplumber pillow

import os
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import pdfplumber
from collections import defaultdict
from typing import List

# ========== 配置 ==========
START_PAGE_INDEX = 1          # 从第2页开始
RENDER_DPI = 180              # 截图清晰度
QUESTIONS_DIR = os.path.join("data", "outputs", "questions")
MERGED_DIR = os.path.join("data", "outputs", "merged")

# ========== Tkinter 截图标号器 ==========
class PageScreener(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("逐页截图 · 手工标号")
        self.minsize(980, 720)

        self.pdf = None
        self.page_images = []      # [(page_index, PIL.Image)]
        self.idx = 0
        self.qnum = 1
        self.saved = []            # [(qnum, filename, page_index)]

        self._build_ui()
        self._choose_pdf()

    def _build_ui(self):
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(outer)
        top.pack(fill=tk.X)
        self.lbl_info = ttk.Label(top, text="未选择PDF")
        self.lbl_info.pack(side=tk.LEFT)

        main = ttk.Frame(outer)
        main.pack(fill=tk.BOTH, expand=True, pady=(10, 6))

        self.canvas = tk.Canvas(main, bg="#222", highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right = ttk.Frame(main)
        right.pack(side=tk.LEFT, fill=tk.Y, padx=(10, 0))

        box_q = ttk.LabelFrame(right, text="题号")
        box_q.pack(fill=tk.X, pady=(0, 8))
        qrow = ttk.Frame(box_q)
        qrow.pack(fill=tk.X, padx=8, pady=8)
        ttk.Label(qrow, text="Q").pack(side=tk.LEFT)
        self.var_q = tk.StringVar(value=str(self.qnum))
        self.ent_q = ttk.Entry(qrow, textvariable=self.var_q, width=6, justify="center")
        self.ent_q.pack(side=tk.LEFT, padx=6)
        ttk.Button(qrow, text="-1", command=self.on_dec).pack(side=tk.LEFT)

        box_btn = ttk.LabelFrame(right, text="操作")
        box_btn.pack(fill=tk.X)
        ttk.Button(box_btn, text="确认（保存）", command=self.on_confirm).pack(fill=tk.X, padx=8, pady=(8, 4))
        ttk.Button(box_btn, text="放弃（跳过）", command=self.on_skip).pack(fill=tk.X, padx=8, pady=(0, 8))

        box_nav = ttk.LabelFrame(right, text="导航")
        box_nav.pack(fill=tk.X, pady=(8, 0))
        nav = ttk.Frame(box_nav)
        nav.pack(fill=tk.X, padx=8, pady=8)
        ttk.Button(nav, text="上一页", command=self.on_prev).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 4))
        ttk.Button(nav, text="下一页", command=self.on_next).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(4, 0))

        bottom = ttk.Frame(outer)
        bottom.pack(fill=tk.X)
        ttk.Button(bottom, text="选择PDF", command=self._choose_pdf).pack(side=tk.LEFT)
        ttk.Button(bottom, text="完成", command=self.on_finish).pack(side=tk.RIGHT)

        self.bind("<Configure>", lambda e: self._render_current())

    def _choose_pdf(self):
        path = filedialog.askopenfilename(title="选择 PDF", filetypes=[("PDF 文件", "*.pdf")])
        if not path:
            return
        try:
            self._load_pdf(path)
            self.lbl_info.config(text=f"文件：{os.path.basename(path)}  |  共 {len(self.page_images)} 页(从第2页起)")
            self.idx = 0
            self.qnum = 1
            self.var_q.set(str(self.qnum))
            self.saved.clear()
            self._render_current()
        except Exception as e:
            messagebox.showerror("错误", f"打开PDF失败：{e}")

    def _load_pdf(self, path: str):
        self.page_images.clear()
        if self.pdf:
            self.pdf.close()
        self.pdf = pdfplumber.open(path)
        total = len(self.pdf.pages)
        if START_PAGE_INDEX >= total:
            raise RuntimeError("PDF 页数不足。")
        for pi in range(START_PAGE_INDEX, total):
            page = self.pdf.pages[pi]
            img = page.to_image(resolution=RENDER_DPI).original
            self.page_images.append((pi, img))

    def _render_current(self):
        if not self.page_images:
            return
        canvas_w = self.canvas.winfo_width() or 800
        canvas_h = self.canvas.winfo_height() or 600
        page_index, pil_img = self.page_images[self.idx]
        img_w, img_h = pil_img.size
        scale = min(canvas_w / img_w, canvas_h / img_h)
        scale = max(min(scale, 1.0), 0.05)
        show_w, show_h = int(img_w * scale), int(img_h * scale)
        img_resized = pil_img.resize((show_w, show_h), Image.LANCZOS)
        self.tk_img = ImageTk.PhotoImage(img_resized)
        self.canvas.delete("all")
        self.canvas.create_image(canvas_w // 2, canvas_h // 2, image=self.tk_img)
        self.title(f"逐页截图  ｜ 第 {self.idx+1}/{len(self.page_images)} 页（原PDF第 {page_index+1} 页）")

    def on_dec(self):
        try:
            cur = int(self.var_q.get())
        except ValueError:
            cur = self.qnum
        cur = max(1, cur - 1)
        self.qnum = cur
        self.var_q.set(str(self.qnum))

    def on_confirm(self):
        try:
            q = int(self.var_q.get())
        except ValueError:
            messagebox.showwarning("提示", "题号必须为数字。")
            return
        os.makedirs(QUESTIONS_DIR, exist_ok=True)
        page_index, pil_img = self.page_images[self.idx]
        fname = f"Q{q}.png"
        out_path = os.path.join(QUESTIONS_DIR, fname)
        if os.path.exists(out_path):
            fname = f"Q{q}-p{page_index+1}.png"
            out_path = os.path.join(QUESTIONS_DIR, fname)
        pil_img.save(out_path)
        self.saved.append((q, fname, page_index+1))
        self.qnum = q + 1
        self.var_q.set(str(self.qnum))
        self.on_next()

    def on_skip(self):
        self.on_next()

    def on_prev(self):
        if self.idx > 0:
            self.idx -= 1
            self._render_current()

    def on_next(self):
        if self.idx < len(self.page_images)-1:
            self.idx += 1
            self._render_current()
        else:
            messagebox.showinfo("完成", "已经是最后一页。")

    def on_finish(self):
        self.destroy()

# ========== 合并工具 ==========
NAME_RE = re.compile(r"^(Q\d+)(?:-p(\d+))?\.(png|jpg|jpeg|tif|tiff|bmp)$", re.IGNORECASE)

def find_question_groups():
    groups = defaultdict(list)
    for fn in os.listdir(QUESTIONS_DIR):
        m = NAME_RE.match(fn)
        if not m:
            continue
        qid = m.group(1)
        pno = int(m.group(2)) if m.group(2) else 0
        full = os.path.join(QUESTIONS_DIR, fn)
        groups[qid].append((full, pno))
    for qid in groups:
        groups[qid].sort(key=lambda tup: tup[1])
    return groups

def open_as_rgb(path: str) -> Image.Image:
    img = Image.open(path)
    if img.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", img.size, (255,255,255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    elif img.mode != "RGB":
        return img.convert("RGB")
    return img

def save_as_multipage_pdf(qid: str, image_paths: List[str]):
    os.makedirs(MERGED_DIR, exist_ok=True)
    out_path = os.path.join(MERGED_DIR, f"{qid}.pdf")
    images = [open_as_rgb(p) for p in image_paths]
    if not images: return None
    first, rest = images[0], images[1:]
    first.save(out_path, "PDF", resolution=300, save_all=True, append_images=rest)
    return out_path

def merge_all():
    groups = find_question_groups()
    if not groups:
        print("[WARN] 没有找到题图")
        return
    print(f"找到 {len(groups)} 道题，开始合并 …")
    for qid, items in sorted(groups.items(), key=lambda kv: int(kv[0][1:])):
        paths = [p for (p,_pno) in items]
        out = save_as_multipage_pdf(qid, paths)
        if out:
            print(f"[OK] {qid} -> {out}")
    print("=== 合并完成 ===")

# ========== 主入口 ==========
if __name__ == "__main__":
    app = PageScreener()
    app.mainloop()
    merge_all()
