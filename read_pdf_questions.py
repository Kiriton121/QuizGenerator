# quiz_generator.py
# 目标：仅输出 data/output/<PDF名>/ 下的合并PDF，不在磁盘保留中间题图
#
# 功能：
# 1) 打开PDF，从第二页开始逐页截图（整页），界面里人工录入题号
# 2) “确认（保存到内存）”仅把当前页图像暂存到内存中对应题号的列表
# 3) 新增“题号 -1 并确认”按钮：先题号 -1，再立即保存当前页
# 4) 关闭界面后，把每个题号的多张页图合并为一个【多页PDF】
#    输出到：data/output/<PDF文件名>/，文件名：<PDF文件名>_Q<题号>.pdf
#


import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from collections import defaultdict
from typing import List, Dict
import pdfplumber
from PIL import Image, ImageTk
from pathlib import Path

# ========= 配置 =========
START_PAGE_INDEX = 1    # 从第2页开始（0=第一页，1=第二页）
RENDER_DPI = 180        # 截图清晰度（越大越清晰，但内存和时间也更高）
OUTPUT_ROOT = os.path.join("data", "output")   # 顶层输出目录

def to_rgb(img: Image.Image) -> Image.Image:
    """PDF 不支持透明，统一转换为 RGB。"""
    if img.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    elif img.mode != "RGB":
        return img.convert("RGB")
    return img

def save_multipage_pdf(pdf_stem: str, qid: str, images: List[Image.Image], out_dir: str) -> str:
    """
    将多张 PIL 图片合并为一个多页PDF（每张图一页）。
    输出路径：<out_dir>/<pdf_stem>_<qid>.pdf
    """
    if not images:
        return ""
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{pdf_stem}_{qid}.pdf")

    # 转 RGB，避免透明通道导致报错
    rgb_imgs = [to_rgb(im) for im in images]
    first, rest = rgb_imgs[0], rgb_imgs[1:]
    first.save(out_path, "PDF", resolution=300, save_all=True, append_images=rest)
    return out_path

# ========= 截图与标号界面 =========
class PageScreener(tk.Tk):
    """
    逐页预览 + 人工题号标注：
    - 题号栏只显示输入框（可手动输入），不再有 -1 按钮
    - 操作栏新增“题号 -1 并确认”按钮：先将题号减 1（不少于 1），然后保存当前页
    - “确认（保存到内存）”只把图像存入内存队列，不落地PNG
    关闭窗口后，主程序会把这些列表合并为PDF。
    """
    def __init__(self):
        super().__init__()
        self.title("逐页截图 · 手工标号（仅输出合并PDF）")
        self.minsize(980, 720)

        self.pdf = None
        self.input_pdf_path: str | None = None      # 选择的PDF完整路径
        self.input_pdf_stem: str | None = None      # PDF 文件名（无扩展名），用于输出命名
        self.page_images: List[tuple[int, Image.Image]] = []  # [(page_index, PIL.Image)]
        self.idx = 0
        self.qnum = 1

        # 采集到的题图（内存）：{'Q7': [img1, img2, ...], ...}
        self.collected: Dict[str, List[Image.Image]] = defaultdict(list)

        self._build_ui()
        self._choose_pdf()

    def _build_ui(self):
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        # 顶部信息
        top = ttk.Frame(outer)
        top.pack(fill=tk.X)
        self.lbl_info = ttk.Label(top, text="未选择PDF")
        self.lbl_info.pack(side=tk.LEFT)

        # 主体：左图右控件
        main = ttk.Frame(outer)
        main.pack(fill=tk.BOTH, expand=True, pady=(10, 6))

        self.canvas = tk.Canvas(main, bg="#222", highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right = ttk.Frame(main)
        right.pack(side=tk.LEFT, fill=tk.Y, padx=(10, 0))

        # 题号：仅输入框（不再有 -1 按钮）
        box_q = ttk.LabelFrame(right, text="题号")
        box_q.pack(fill=tk.X, pady=(0, 8))
        qrow = ttk.Frame(box_q)
        qrow.pack(fill=tk.X, padx=8, pady=8)
        ttk.Label(qrow, text="Q").pack(side=tk.LEFT)
        self.var_q = tk.StringVar(value=str(self.qnum))
        self.ent_q = ttk.Entry(qrow, textvariable=self.var_q, width=6, justify="center")
        self.ent_q.pack(side=tk.LEFT, padx=6)

        # 操作：新增“题号 -1 并确认”
        box_btn = ttk.LabelFrame(right, text="操作")
        box_btn.pack(fill=tk.X)
        ttk.Button(box_btn, text="确认（保存到内存）", command=self.on_confirm).pack(fill=tk.X, padx=8, pady=(8, 4))
        ttk.Button(box_btn, text="题号 -1 并确认", command=self.on_confirm_minus_one).pack(fill=tk.X, padx=8, pady=(0, 4))
        ttk.Button(box_btn, text="放弃（跳过此页）", command=self.on_skip).pack(fill=tk.X, padx=8, pady=(0, 8))

        # 导航
        box_nav = ttk.LabelFrame(right, text="导航")
        box_nav.pack(fill=tk.X, pady=(8, 0))
        nav = ttk.Frame(box_nav)
        nav.pack(fill=tk.X, padx=8, pady=8)
        ttk.Button(nav, text="上一页", command=self.on_prev).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 4))
        ttk.Button(nav, text="下一页", command=self.on_next).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(4, 0))

        # 底部
        bottom = ttk.Frame(outer)
        bottom.pack(fill=tk.X)
        ttk.Button(bottom, text="选择PDF", command=self._choose_pdf).pack(side=tk.LEFT)
        ttk.Button(bottom, text="完成并生成PDF", command=self.on_finish).pack(side=tk.RIGHT)

        self.bind("<Configure>", lambda e: self._render_current())

    def _choose_pdf(self):
        path = filedialog.askopenfilename(title="选择 PDF", filetypes=[("PDF 文件", "*.pdf")])
        if not path:
            return
        try:
            self._load_pdf(path)
            fname = os.path.basename(path)
            self.lbl_info.config(
                text=f"文件：{fname}  |  可处理页数：{len(self.page_images)}（从第2页起）"
            )
            self.idx = 0
            self.qnum = 1
            self.var_q.set(str(self.qnum))
            self.collected.clear()
            self._render_current()
        except Exception as e:
            messagebox.showerror("错误", f"打开PDF失败：{e}")

    def _load_pdf(self, path: str):
        self.input_pdf_path = path
        self.input_pdf_stem = Path(path).stem

        self.page_images.clear()
        if self.pdf:
            self.pdf.close()
        self.pdf = pdfplumber.open(path)
        total = len(self.pdf.pages)
        if START_PAGE_INDEX >= total:
            raise RuntimeError("PDF 页数不足。")
        for pi in range(START_PAGE_INDEX, total):
            page = self.pdf.pages[pi]
            pil = page.to_image(resolution=RENDER_DPI).original  # PIL.Image
            self.page_images.append((pi, pil))

    def _render_current(self):
        if not self.page_images:
            return
        canvas_w = self.canvas.winfo_width() or 800
        canvas_h = self.canvas.winfo_height() or 600
        page_index, pil_img = self.page_images[self.idx]

        # 自适应缩放以展示
        img_w, img_h = pil_img.size
        scale = min(canvas_w / img_w, canvas_h / img_h)
        scale = max(min(scale, 1.0), 0.05)
        show_w, show_h = int(img_w * scale), int(img_h * scale)
        show_img = pil_img.resize((show_w, show_h), Image.LANCZOS)

        self.tk_img = ImageTk.PhotoImage(show_img)
        self.canvas.delete("all")
        self.canvas.create_image(canvas_w // 2, canvas_h // 2, image=self.tk_img)
        self.title(
            f"逐页截图（仅输出合并PDF）｜ 第 {self.idx+1}/{len(self.page_images)} 页（原PDF第 {page_index+1} 页）"
        )

    # ===== 交互 =====
    def _parse_q(self) -> int | None:
        try:
            return int(self.var_q.get())
        except ValueError:
            messagebox.showwarning("提示", "题号必须为数字。")
            return None

    def _save_current_to_memory(self, q: int):
        """把当前页图像存入内存的题号队列，不落地PNG。"""
        if not self.page_images:
            return
        qid = f"Q{q}"
        _page_index, pil_img = self.page_images[self.idx]
        self.collected[qid].append(to_rgb(pil_img.copy()))

    def on_confirm(self):
        q = self._parse_q()
        if q is None:
            return
        self._save_current_to_memory(q)
        # 自动 +1 并跳到下一页；若跨页同一题，使用“题号 -1 并确认”
        self.qnum = q + 1
        self.var_q.set(str(self.qnum))
        self.on_next()

    def on_confirm_minus_one(self):
        """先题号 -1（不少于 1），再把当前页保存为该题号并跳到下一页。"""
        q = self._parse_q()
        if q is None:
            return
        q = max(1, q - 1)
        self.var_q.set(str(q))
        self._save_current_to_memory(q)
        # 保存后仍遵循“确认”的行为：题号 +1 并下一页
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
        if self.idx < len(self.page_images) - 1:
            self.idx += 1
            self._render_current()
        else:
            messagebox.showinfo("完成", "已经是最后一页。")

    def on_finish(self):
        total_imgs = sum(len(v) for v in self.collected.values())
        if total_imgs == 0:
            if messagebox.askyesno("确认", "还没有保存任何题目页。是否直接退出？"):
                self.destroy()
            return
        # 汇总提示
        msg = "\n".join([f"{qid}: {len(pages)} 页" for qid, pages in self.collected.items()])
        messagebox.showinfo("已收集题图（内存）", f"即将生成合并PDF：\n\n{msg}")
        self.destroy()

# ========= 主入口 =========
if __name__ == "__main__":
    app = PageScreener()
    app.mainloop()

    # 窗口关闭后，把内存中的题图合并成 PDF
    if getattr(app, "collected", None) and app.input_pdf_stem:
        pdf_stem = app.input_pdf_stem
        # 输出目录：data/output/<PDF文件名>/
        dest_dir = os.path.join(OUTPUT_ROOT, pdf_stem)
        os.makedirs(dest_dir, exist_ok=True)

        print(f"开始生成合并PDF → 输出目录：{os.path.abspath(dest_dir)}")
        # 题号按数字排序：Q7, Q8, ...
        for qid in sorted(app.collected.keys(), key=lambda s: int(s[1:])):
            imgs = app.collected[qid]
            out = save_multipage_pdf(pdf_stem, qid, imgs, dest_dir)
            if out:
                print(f"[OK] {qid} -> {out}")
        print("全部生成完成。")
    else:
        print("未收集到任何题图，未生成PDF。")
