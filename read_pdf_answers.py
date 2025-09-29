# answer_cropping_tool.py
# 手动框选答案并按题号导出（同题多块合并为多页 PDF）
# 输出：data/output_answers/<PDF名>/<PDF名>_Q<题号>_ANS.pdf
#
# 依赖：
#   pip install pdfplumber pillow

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import pdfplumber
from PIL import Image, ImageTk

# ===== 配置 =====
START_PAGE_INDEX = 1          # 从第2页开始
RENDER_DPI = 180              # 渲染清晰度
OUTPUT_ROOT = Path("data/output_answers")

def to_rgb(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    elif img.mode != "RGB":
        return img.convert("RGB")
    return img

def save_multipage_pdf(stem: str, qid: str, images: List[Image.Image], out_dir: Path) -> str:
    if not images:
        return ""
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{stem}_{qid}_ANS.pdf"
    rgb = [to_rgb(im) for im in images]
    first, rest = rgb[0], rgb[1:]
    first.save(str(out_path), "PDF", resolution=300, save_all=True, append_images=rest)
    return str(out_path)

class AnswerCropper(tk.Tk):
    """
    - 选择 MS PDF（或通过 initial_pdf 直接加载）
    - 画布显示页面（自适应缩放+居中）
    - 鼠标拖拽框选；只显示“已选择/未选择”
    - 按钮：
        * 确认（先弹出预览 -> 确认后保存至内存；题号不自动变化）
        * 题号 +1 并确认（先 +1，再弹预览并保存）
        * 清除当前选区
    - 完成后每个题号导出一个多页 PDF：<stem>_Qn_ANS.pdf
    """
    def __init__(self, initial_pdf: Optional[str] = None):
        super().__init__()
        self.title("答案截取（手动框选 · 预览确认）")
        self.minsize(1000, 760)

        self.pdf: Optional[pdfplumber.PDF] = None
        self.stem: Optional[str] = None
        self.page_imgs: List[Tuple[int, Image.Image]] = []  # [(page_index, PIL)]
        self.idx = 0

        # 显示参数
        self.scale = 1.0         # 显示图与原图的比例：show = original * scale
        self.img_left = 0        # 显示图在画布中的左上角 x
        self.img_top = 0         # 显示图在画布中的左上角 y
        self.show_img: Optional[Image.Image] = None
        self.tk_img: Optional[ImageTk.PhotoImage] = None

        # 选区（画布坐标）
        self.sel_start: Optional[Tuple[int, int]] = None
        self.sel_bbox_canvas: Optional[Tuple[int, int, int, int]] = None

        # 已收集：{'Q7': [img1,img2,...]}
        self.collected: Dict[str, List[Image.Image]] = {}

        # 题号
        self.qnum = 1

        self._build_ui()

        # —— 关键：如果传入 initial_pdf，就直接加载；否则走原来的选择流程
        if initial_pdf:
            try:
                self.load_pdf(initial_pdf)
                self.info.config(text=f"文件：{Path(initial_pdf).name} ｜ 可处理页数：{len(self.page_imgs)}（从第2页起）")
                self.idx = 0
                self.qnum = 1
                self.var_q.set(str(self.qnum))
                self.collected.clear()
                self.render_current()
            except Exception:
                # 加载失败则回退到手动选择
                self._choose_pdf()
        else:
            self._choose_pdf()

    # ---------- UI ----------
    def _build_ui(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(root); top.pack(fill=tk.X)
        self.info = ttk.Label(top, text="未选择PDF"); self.info.pack(side=tk.LEFT)

        main = ttk.Frame(root); main.pack(fill=tk.BOTH, expand=True, pady=(10, 6))

        # 画布
        self.canvas = tk.Canvas(main, bg="#222", highlightthickness=0, cursor="tcross")
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self.on_canvas_down)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_up)
        self.bind("<Configure>", lambda e: self.render_current())

        # 右侧
        right = ttk.Frame(main); right.pack(side=tk.LEFT, fill=tk.Y, padx=(10, 0))

        # 题号
        lf_q = ttk.LabelFrame(right, text="题号"); lf_q.pack(fill=tk.X, pady=(0, 8))
        row = ttk.Frame(lf_q); row.pack(fill=tk.X, padx=8, pady=8)
        ttk.Label(row, text="Q").pack(side=tk.LEFT)
        self.var_q = tk.StringVar(value=str(self.qnum))
        self.ent_q = ttk.Entry(row, textvariable=self.var_q, width=6, justify="center")
        self.ent_q.pack(side=tk.LEFT, padx=6)

        # 选区状态（只显示“已选择/未选择”）
        self.sel_label = ttk.Label(lf_q, text="未选择")
        self.sel_label.pack(fill=tk.X, padx=8, pady=(0, 8))

        # 操作
        lf_ops = ttk.LabelFrame(right, text="操作"); lf_ops.pack(fill=tk.X)
        ttk.Button(lf_ops, text="确认（预览后保存）", command=self.on_confirm).pack(fill=tk.X, padx=8, pady=(8, 4))
        ttk.Button(lf_ops, text="题号 +1 并确认", command=self.on_confirm_plus_one).pack(fill=tk.X, padx=8, pady=(0, 4))
        ttk.Button(lf_ops, text="清除当前选区", command=self.clear_selection).pack(fill=tk.X, padx=8, pady=(0, 8))

        # 导航
        lf_nav = ttk.LabelFrame(right, text="页面导航"); lf_nav.pack(fill=tk.X, pady=(8, 0))
        nav = ttk.Frame(lf_nav); nav.pack(fill=tk.X, padx=8, pady=8)
        ttk.Button(nav, text="上一页", command=self.on_prev).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 4))
        ttk.Button(nav, text="下一页", command=self.on_next).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(4, 0))

        # 底部
        bottom = ttk.Frame(root); bottom.pack(fill=tk.X)
        ttk.Button(bottom, text="选择PDF", command=self._choose_pdf).pack(side=tk.LEFT)
        ttk.Button(bottom, text="完成并导出", command=self.on_finish).pack(side=tk.RIGHT)

    # ---------- PDF ----------
    def _choose_pdf(self):
        path = filedialog.askopenfilename(title="选择答案（Mark Scheme）PDF", filetypes=[("PDF 文件", "*.pdf")])
        if not path:
            return
        try:
            self.load_pdf(path)
            self.info.config(text=f"文件：{Path(path).name} ｜ 可处理页数：{len(self.page_imgs)}（从第2页起）")
            self.idx = 0
            self.qnum = 1
            self.var_q.set(str(self.qnum))
            self.collected.clear()
            self.render_current()
        except Exception as e:
            messagebox.showerror("错误", f"打开PDF失败：{e}")

    def load_pdf(self, path: str):
        if self.pdf:
            self.pdf.close()
        self.pdf = pdfplumber.open(path)
        self.stem = Path(path).stem
        total = len(self.pdf.pages)
        if START_PAGE_INDEX >= total:
            raise RuntimeError("PDF 页数不足。")
        self.page_imgs.clear()
        for pi in range(START_PAGE_INDEX, total):
            page = self.pdf.pages[pi]
            pil = page.to_image(resolution=RENDER_DPI).original
            self.page_imgs.append((pi, pil))

    # ---------- 渲染 ----------
    def render_current(self):
        if not self.page_imgs:
            return
        canvas_w = self.canvas.winfo_width() or 800
        canvas_h = self.canvas.winfo_height() or 600
        _pi, pil = self.page_imgs[self.idx]
        ow, oh = pil.size
        scale = min(canvas_w / ow, canvas_h / oh)
        scale = max(min(scale, 1.0), 0.05)
        self.scale = scale
        show_w, show_h = int(ow * scale), int(oh * scale)

        # 居中位置
        self.img_left = (canvas_w - show_w) // 2
        self.img_top = (canvas_h - show_h) // 2

        show = pil.resize((show_w, show_h), Image.LANCZOS)
        self.show_img = show
        self.tk_img = ImageTk.PhotoImage(show)

        self.canvas.delete("all")
        self.canvas.create_image(self.img_left, self.img_top, image=self.tk_img, anchor="nw")
        self.canvas.image = self.tk_img  # 防GC
        self.clear_selection(draw_only=True)
        self.title(f"答案截取 ｜ 第 {self.idx+1}/{len(self.page_imgs)} 页")

    # ---------- 选区交互 ----------
    def on_canvas_down(self, event):
        # 点击必须落在图片区域内
        if not self._point_in_image(event.x, event.y):
            return
        self.clear_selection(draw_only=True)
        self.sel_start = (event.x, event.y)
        self.sel_bbox_canvas = (event.x, event.y, event.x, event.y)
        self._draw_selection()
        self.sel_label.config(text="已选择")

    def on_canvas_drag(self, event):
        if not self.sel_start:
            return
        x0, y0 = self.sel_start
        x1, y1 = event.x, event.y
        # 限制在图片范围内
        x1 = min(max(x1, self.img_left), self.img_left + (self.show_img.width if self.show_img else 0))
        y1 = min(max(y1, self.img_top),  self.img_top  + (self.show_img.height if self.show_img else 0))
        x0 = min(max(x0, self.img_left), self.img_left + (self.show_img.width if self.show_img else 0))
        y0 = min(max(y0, self.img_top),  self.img_top  + (self.show_img.height if self.show_img else 0))
        self.sel_bbox_canvas = (min(x0,x1), min(y0,y1), max(x0,x1), max(y0,y1))
        self._draw_selection()
        self.sel_label.config(text="已选择")

    def on_canvas_up(self, event):
        if not self.sel_bbox_canvas:
            self.sel_label.config(text="未选择")

    def _draw_selection(self):
        self.canvas.delete("sel")
        if self.sel_bbox_canvas:
            x0,y0,x1,y1 = self.sel_bbox_canvas
            self.canvas.create_rectangle(x0,y0,x1,y1, outline="#00e0ff", width=2, tags="sel")

    def clear_selection(self, draw_only=False):
        self.canvas.delete("sel")
        if not draw_only:
            self.sel_start = None
            self.sel_bbox_canvas = None
            self.sel_label.config(text="未选择")

    def _point_in_image(self, x: int, y: int) -> bool:
        if not self.show_img:
            return False
        return (self.img_left <= x <= self.img_left + self.show_img.width) and \
               (self.img_top  <= y <= self.img_top  + self.show_img.height)

    # ---------- 坐标换算：画布 -> 原始渲染像素 ----------
    def _canvas_box_to_original(self, box) -> Optional[Tuple[int,int,int,int]]:
        if not box:
            return None
        x0,y0,x1,y1 = box
        # 去掉居中偏移，再除以缩放
        inv = 1.0 / max(self.scale, 1e-6)
        rx0 = int((x0 - self.img_left) * inv)
        ry0 = int((y0 - self.img_top ) * inv)
        rx1 = int((x1 - self.img_left) * inv)
        ry1 = int((y1 - self.img_top ) * inv)
        # 裁剪到原图边界
        _pi, pil = self.page_imgs[self.idx]
        rx0 = max(0, min(pil.width,  rx0))
        rx1 = max(0, min(pil.width,  rx1))
        ry0 = max(0, min(pil.height, ry0))
        ry1 = max(0, min(pil.height, ry1))
        if rx1 <= rx0 or ry1 <= ry0:
            return None
        return (rx0, ry0, rx1, ry1)

    # ---------- 预览 & 保存 ----------
    def _parse_q(self) -> Optional[int]:
        try:
            return int(self.var_q.get())
        except ValueError:
            messagebox.showwarning("提示", "题号必须为数字。")
            return None

    def _crop_current_selection(self) -> Optional[Image.Image]:
        if not self.sel_bbox_canvas:
            messagebox.showwarning("提示", "请先用鼠标拖拽选区。")
            return None
        box = self._canvas_box_to_original(self.sel_bbox_canvas)
        if not box:
            messagebox.showwarning("提示", "选区无效。")
            return None
        _pi, pil = self.page_imgs[self.idx]
        return pil.crop(box)

    def _preview_and_maybe_save(self, q: int):
        """弹预览 → 确认后保存到内存；不自动改题号"""
        crop = self._crop_current_selection()
        if crop is None:
            return
        # 预览窗口
        top = tk.Toplevel(self)
        top.title(f"预览：Q{q}")
        top.transient(self)
        top.grab_set()

        # 让预览尽量不超过 800 宽
        show = crop
        maxw = 800
        if show.width > maxw:
            ratio = maxw / show.width
            show = show.resize((int(show.width*ratio), int(show.height*ratio)), Image.LANCZOS)
        tkimg = ImageTk.PhotoImage(show)

        canvas = tk.Canvas(top, width=show.width, height=show.height, highlightthickness=0)
        canvas.pack(padx=10, pady=10)
        canvas.create_image(0, 0, image=tkimg, anchor="nw")
        canvas.image = tkimg  # 防GC

        btns = ttk.Frame(top); btns.pack(pady=(0,10))
        def do_confirm():
            qid = f"Q{q}"
            self.collected.setdefault(qid, []).append(to_rgb(crop))
            top.destroy()
            self.focus_set()
            self.clear_selection()

        ttk.Button(btns, text="确认保存", command=do_confirm).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text="取消", command=top.destroy).pack(side=tk.LEFT, padx=6)

        top.wait_window(top)

    def on_confirm(self):
        q = self._parse_q()
        if q is None:
            return
        self._preview_and_maybe_save(q)

    def on_confirm_plus_one(self):
        q = self._parse_q()
        if q is None:
            return
        q = q + 1
        self.var_q.set(str(q))
        self._preview_and_maybe_save(q)

    # ---------- 导航 ----------
    def on_prev(self):
        if self.idx > 0:
            self.idx -= 1
            self.render_current()

    def on_next(self):
        if self.idx < len(self.page_imgs)-1:
            self.idx += 1
            self.render_current()

    def on_finish(self):
        if not self.collected:
            if messagebox.askyesno("确认", "还没有保存任何选区，是否直接退出？"):
                self.destroy()
            return
        dest = OUTPUT_ROOT / (self.stem or "output")
        dest.mkdir(parents=True, exist_ok=True)
        for qid in sorted(self.collected.keys(), key=lambda s: int(s[1:])):
            out = save_multipage_pdf(self.stem or "output", qid, self.collected[qid], dest)
            print(f"[OK] {qid} -> {out}")
        messagebox.showinfo("完成", f"已导出到：\n{dest.resolve()}")
        self.destroy()

# ===== 主入口 =====
if __name__ == "__main__":
    """
    支持从命令行传入 --file 直接加载某个答案 PDF。
    未传 --file 时，保持原有“选择PDF”的流程。
    """
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default=None, help="要直接加载的答案 PDF 路径")
    args = parser.parse_args()

    app = AnswerCropper(initial_pdf=args.file)
    app.mainloop()
