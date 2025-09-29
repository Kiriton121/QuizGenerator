# read_pdf_questions.py
# 目标：仅输出 data/output/<PDF名>/ 下的合并PDF，不在磁盘保留中间题图
#
# - 布局：题号 -> 页面导航 -> Topic 多选 -> 操作
# - Topic 为可多选的 Checkbutton；确认后会重置勾选
# - “题号 -1 并确认”：自动套用“上一页已确认时勾选的 topics”
# - 不预览；整页入库（内存）
# - 导出 PDF 文件名附带题号与 Topic（多个则用下划线拼接）
# - 新增：支持 initial_pdf / --file 直接加载，不再二次弹“选择PDF”

import os
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from collections import defaultdict
from typing import List, Dict, Optional
from pathlib import Path

import pdfplumber
from PIL import Image, ImageTk

# === topics 映射（依据文件名推断科目/卷别）===
try:
    from topics import parse_filename as ts_parse_filename, get_topics as ts_get_topics
except Exception:
    ts_parse_filename = None
    ts_get_topics = None

# ========= 配置 =========
START_PAGE_INDEX = 1        # 从第2页开始（0=第一页，1=第二页）
RENDER_DPI = 300            # 左侧预览清晰度（300 常用）
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

def _sanitize_for_filename(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[^A-Za-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s

def save_multipage_pdf(pdf_stem: str, qid: str, images: List[Image.Image], out_dir: str,
                       topic_list: Optional[List[str]] = None) -> str:
    """
    将多张 PIL 图片合并为一个多页PDF（每张图一页）。
    输出路径：<out_dir>/<pdf_stem>_<qid>[_<Topic...>].pdf
    """
    if not images:
        return ""
    os.makedirs(out_dir, exist_ok=True)

    # 题号后拼上全部已选 topic（若无则不拼）
    topic_part = ""
    if topic_list:
        topic_part = "_" + "_".join(_sanitize_for_filename(t) for t in topic_list)

    out_path = os.path.join(out_dir, f"{pdf_stem}_{qid}{topic_part}.pdf")

    rgb_imgs = [to_rgb(im) for im in images]
    first, rest = rgb_imgs[0], rgb_imgs[1:]
    first.save(out_path, "PDF", resolution=300, save_all=True, append_images=rest)
    return out_path

# ========= 截图与标号界面 =========
class PageScreener(tk.Tk):
    """
    逐页预览（整页）+ 人工题号标注 + topics 多选：
    - 布局：题号 -> 页面导航 -> Topic 多选 -> 操作
    - “确认（保存到内存）”直接入库，不预览；随后重置 topic 勾选
    - “题号 -1 并确认”：自动套用上一页已确认时的 topics 勾选
    - 不落地中间PNG，退出后合并生成PDF；文件名包含题号与Topic
    - 新增：initial_pdf 参数可直接加载，不再二次弹选择框
    """
    def __init__(self, initial_pdf: str | None = None):
        super().__init__()
        self.title("逐页截图 · 手工标号（整页 · 多选Topic）")
        self.minsize(1000, 760)

        self.pdf: Optional[pdfplumber.PDF] = None
        self.input_pdf_path: Optional[str] = None
        self.input_pdf_stem: Optional[str] = None
        self.page_images: List[tuple[int, Image.Image]] = []  # [(page_index_in_pdf, PIL.Image)]
        self.idx = 0
        self.qnum = 1

        # 采集到的题图（内存）：{'Q7': [img1, img2, ...]}
        self.collected: Dict[str, List[Image.Image]] = defaultdict(list)
        # 每题的 topics：{'Q7': ['Functions', 'Series']}
        self.q_topics: Dict[str, List[str]] = {}

        # —— 记录“每一页确认时”的 topics（用于 -1 并确认时复用）
        self.page_topics_selected: Dict[int, List[str]] = {}

        # 当前文档的 topic 候选（来自文件名推断）
        self.meta: Optional[Dict[str, str]] = None
        self.topic_vars: Dict[str, tk.BooleanVar] = {}   # 主题 -> 选中布尔
        self.topic_box: Optional[ttk.LabelFrame] = None  # 容器（刷新时清空）

        self._build_ui()

        # == 载入 PDF ==
        if initial_pdf:
            try:
                self._load_pdf(initial_pdf)
                fname = os.path.basename(initial_pdf)
                self.lbl_info.config(
                    text=f"文件：{fname}  |  可处理页数：{len(self.page_images)}（从第2页起）"
                )
                self.idx = 0
                self.qnum = 1
                self.var_q.set(str(self.qnum))
                self.collected.clear()
                self.q_topics.clear()
                self.page_topics_selected.clear()

                self.meta = ts_parse_filename(fname) if ts_parse_filename else None
                self._refresh_topic_checkboxes()
                self._render_current()
            except Exception:
                # 失败则回退到手动选择
                self._choose_pdf()
        else:
            self._choose_pdf()

    # ---------- UI ----------
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

        # 左侧整页预览
        self.canvas = tk.Canvas(main, bg="#222", highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 右侧栏
        right = ttk.Frame(main)
        right.pack(side=tk.LEFT, fill=tk.Y, padx=(10, 0))

        # 题号
        box_q = ttk.LabelFrame(right, text="题号")
        box_q.pack(fill=tk.X, pady=(0, 8))
        qrow = ttk.Frame(box_q); qrow.pack(fill=tk.X, padx=8, pady=8)
        ttk.Label(qrow, text="Q").pack(side=tk.LEFT)
        self.var_q = tk.StringVar(value=str(self.qnum))
        self.ent_q = ttk.Entry(qrow, textvariable=self.var_q, width=6, justify="center")
        self.ent_q.pack(side=tk.LEFT, padx=6)

        # 页面导航
        box_nav = ttk.LabelFrame(right, text="页面导航")
        box_nav.pack(fill=tk.X, pady=(8, 0))
        nav = ttk.Frame(box_nav); nav.pack(fill=tk.X, padx=8, pady=8)
        ttk.Button(nav, text="上一页", command=self.on_prev).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 4))
        ttk.Button(nav, text="下一页", command=self.on_next).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(4, 0))

        # Topic 多选
        self.topic_box = ttk.LabelFrame(right, text="Topic（可多选）")
        self.topic_box.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        # 操作
        box_btn = ttk.LabelFrame(right, text="操作")
        box_btn.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(box_btn, text="确认（保存到内存）", command=self.on_confirm).pack(fill=tk.X, padx=8, pady=(8, 4))
        ttk.Button(box_btn, text="题号 -1 并确认", command=self.on_confirm_minus_one).pack(fill=tk.X, padx=8, pady=(0, 4))
        ttk.Button(box_btn, text="放弃（跳过此页）", command=self.on_skip).pack(fill=tk.X, padx=8, pady=(0, 8))

        # 底部
        bottom = ttk.Frame(outer)
        bottom.pack(fill=tk.X)
        ttk.Button(bottom, text="选择PDF", command=self._choose_pdf).pack(side=tk.LEFT)
        ttk.Button(bottom, text="完成并生成PDF", command=self.on_finish).pack(side=tk.RIGHT)

        self.bind("<Configure>", lambda e: self._render_current())

    # ---------- PDF ----------
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
            self.q_topics.clear()
            self.page_topics_selected.clear()

            # 解析文件名 -> 刷新 topics（checkbox）
            self.meta = ts_parse_filename(fname) if ts_parse_filename else None
            self._refresh_topic_checkboxes()

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

    # ---------- Topics（checklist） ----------
    def _refresh_topic_checkboxes(self):
        for child in self.topic_box.winfo_children():
            child.destroy()
        self.topic_vars.clear()

        topics: List[str] = []
        if self.meta and ts_get_topics:
            subj = self.meta.get("subject")
            comp = self.meta.get("component")
            try:
                topics = [t.get("name") for t in (ts_get_topics(subj, comp) or [])]
            except Exception:
                topics = []

        if not topics:
            ttk.Label(self.topic_box, text="(未解析到科目/卷别或未匹配到topics)").pack(padx=8, pady=8, anchor="w")
            return

        grid = ttk.Frame(self.topic_box); grid.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        cols = 1  # 想显示为两列可改为 2
        for i, name in enumerate(topics):
            var = tk.BooleanVar(value=False)
            self.topic_vars[name] = var
            cb = ttk.Checkbutton(grid, text=name, variable=var)
            r, c = divmod(i, cols)
            cb.grid(row=r, column=c, sticky="w", padx=4, pady=2)

    def _current_topic_selection(self) -> List[str]:
        return [name for name, var in self.topic_vars.items() if var.get()]

    def _reset_topic_checks(self):
        for var in self.topic_vars.values():
            var.set(False)

    def _set_topic_checks(self, selected_names: List[str]):
        """按给定列表勾选 topics（用于 -1 并确认时复用上一页设置）"""
        self._reset_topic_checks()
        name_set = set(selected_names or [])
        for name, var in self.topic_vars.items():
            if name in name_set:
                var.set(True)

    # ---------- 渲染 ----------
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
        # 居中显示
        self.canvas.create_image(canvas_w // 2, canvas_h // 2, image=self.tk_img)
        self.title(
            f"逐页截图（整页）｜ 第 {self.idx+1}/{len(self.page_images)} 页（原PDF第 {page_index+1} 页）"
        )

    # ===== 交互 =====
    def _parse_q(self) -> int | None:
        try:
            return int(self.var_q.get())
        except ValueError:
            messagebox.showwarning("提示", "题号必须为数字。")
            return None

    def _save_current_to_memory(self, q: int):
        """把当前页图像存入内存；记录 topics；随后重置勾选。"""
        if not self.page_images:
            return
        qid = f"Q{q}"
        _page_index, pil_img = self.page_images[self.idx]
        self.collected[qid].append(to_rgb(pil_img.copy()))
        topics_now = self._current_topic_selection()
        self.q_topics[qid] = topics_now
        self.page_topics_selected[self.idx] = topics_now[:]
        self._reset_topic_checks()

    def on_confirm(self):
        q = self._parse_q()
        if q is None:
            return
        self._save_current_to_memory(q)
        self.qnum = q + 1
        self.var_q.set(str(self.qnum))
        self.on_next()

    def on_confirm_minus_one(self):
        q = self._parse_q()
        if q is None:
            return
        q = max(1, q - 1)
        self.var_q.set(str(q))

        prev_idx = self.idx - 1
        if prev_idx >= 0 and prev_idx in self.page_topics_selected:
            self._set_topic_checks(self.page_topics_selected[prev_idx])

        self._save_current_to_memory(q)
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
        lines = []
        for qid in sorted(self.collected.keys(), key=lambda s: int(s[1:])):
            topics = self.q_topics.get(qid, [])
            topic_str = ", ".join(topics) if topics else "（未选）"
            lines.append(f"{qid}: {len(self.collected[qid])} 页 | Topic: {topic_str}")
        messagebox.showinfo("已收集题图（内存）", "即将生成合并PDF：\n\n" + "\n".join(lines))
        self.destroy()

# ========= 主入口 =========
if __name__ == "__main__":
    """
    支持从命令行传入 --file 直接加载某个 PDF。
    若未传 --file，保持原先“选择PDF”的流程。
    窗口关闭后，把内存里的题图合并导出到 data/output/<stem>/...
    """
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default=None, help="要直接加载的题目 PDF 路径")
    args = parser.parse_args()

    app = PageScreener(initial_pdf=args.file)
    app.mainloop()

    # 退出后合并导出
    if getattr(app, "collected", None) and getattr(app, "input_pdf_stem", None):
        stem = app.input_pdf_stem
        dest_dir = os.path.join(OUTPUT_ROOT, stem)
        os.makedirs(dest_dir, exist_ok=True)

        for qid in sorted(app.collected.keys(), key=lambda s: int(s[1:])):
            imgs = app.collected[qid]
            topics_for_q = app.q_topics.get(qid, [])
            out = save_multipage_pdf(stem, qid, imgs, dest_dir, topics_for_q)
            if out:
                print(f"[OK] {qid} -> {out}")
        print(f"全部生成完成 → {dest_dir}")
    else:
        print("未收集到任何题图，未生成PDF。")
