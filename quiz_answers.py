import os
import re
import glob
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Dict, List, Set, Tuple

# ---- 只用 PyPDF2 合并 PDF（兼容新旧类名） ----
try:
    from PyPDF2 import PdfMerger            # 新版 PyPDF2
except Exception:
    from PyPDF2 import PdfFileMerger as PdfMerger  # 旧名

# ---- 从你的 topics.py 读取卷别与 topics ----
# 需要 topics.py 与本文件在同一目录（项目根）下
from topics import list_components, get_topics

APP_TITLE = "Quiz 答案生成器（按年/季/卷别/Topics）"

# ====== 路径基于你的目录结构 ======
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
QP_DIR = DATA_DIR / "output"           # 题目目录（qp）
MS_DIR = DATA_DIR / "output_answers"   # 答案目录（ms）
QUIZ_ANS_DIR = DATA_DIR / "quiz_answers"  # 输出目录

# 年份、季节
YEARS = [str(y) for y in range(2018, 2026)]
SEASON_CODE = {"Winter": "w", "Summer": "s", "Spring": "m"}  # w/s/m

# 目录名：题目：9709_w24_qp_12；答案：9709_w24_ms_12
FOLDER_QP_RE = re.compile(
    r"^(?P<subject>\d{4})_(?P<season>[wsm])(?P<yy>\d{2})_qp_(?P<comp>\d{2})$",
    re.IGNORECASE,
)
FOLDER_MS_RE = re.compile(
    r"^(?P<subject>\d{4})_(?P<season>[wsm])(?P<yy>\d{2})_ms_(?P<comp>\d{2})$",
    re.IGNORECASE,
)

# 题目 PDF 名需包含：_Q<number>_ （例如 ..._Q8_Coordinate_geometry.pdf）
Q_PART_RE = re.compile(r"(?i)_Q(\d+)_")

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def season_matches(selected_seasons: List[str], season_char: str) -> bool:
    for name, code in SEASON_CODE.items():
        if code == season_char and name in selected_seasons:
            return True
    return False

def normalize_tokens(s: str) -> List[str]:
    # 小写后提取字母数字片段作为 tokens
    return re.findall(r"[a-z0-9]+", s.lower())

def filename_topics_tokens(pdf_stem: str) -> Set[str]:
    """
    从题目文件名中抽取 topics tokens：
    找到 _Q<digits>_ 之后的所有部分，用下划线拆，再 normalize
    例：..._Q8_Coordinate_geometry -> {"coordinate","geometry"}
    """
    m = Q_PART_RE.search(pdf_stem)
    if not m:
        return set()
    start = m.end()
    tail = pdf_stem[start:]
    toks: Set[str] = set()
    for seg in tail.split("_"):
        toks.update(normalize_tokens(seg))
    return toks

def selection_topics_tokens(selected_topic_names: List[str]) -> Set[str]:
    toks: Set[str] = set()
    for name in selected_topic_names:
        toks.update(normalize_tokens(name))
    return toks

Key = Tuple[str, str, str, str]  # (subject, season_char, yy, comp2)

def list_candidate_qp_folders(selected_years: List[str],
                              selected_seasons: List[str],
                              selected_component: str) -> List[Path]:
    """
    在 QP_DIR 下找到满足 年份 + 季节 + 卷别(组件首位) 的题目文件夹
    组件首位：例如 comp=12 -> '1'（P1）
    """
    if not QP_DIR.is_dir():
        return []
    folders: List[Path] = []
    for entry in QP_DIR.iterdir():
        if not entry.is_dir():
            continue
        m = FOLDER_QP_RE.match(entry.name)
        if not m:
            continue

        yy = m.group("yy")                       # "24"
        season_char = m.group("season").lower()  # 'w'/'s'/'m'
        comp = m.group("comp")                   # "12"
        comp_first = comp[0] if comp else ""

        if not any(y.endswith(yy) for y in selected_years):
            continue
        if not season_matches(selected_seasons, season_char):
            continue
        if comp_first != selected_component:
            continue

        folders.append(entry)
    return folders

def build_selected_questions(qp_folders: List[Path],
                             selected_tokens: Set[str]) -> Dict[Key, Set[int]]:
    """
    遍历题目文件夹，找出命中 topics 的题目，按 (subject, season_char, yy, comp) 记录其题号集合
    """
    selected: Dict[Key, Set[int]] = {}
    for folder in qp_folders:
        m = FOLDER_QP_RE.match(folder.name)
        if not m:
            continue
        subject = m.group("subject")
        season_char = m.group("season").lower()
        yy = m.group("yy")
        comp = m.group("comp")  # 两位

        key: Key = (subject, season_char, yy, comp)

        for pdf_path_str in glob.glob(str(folder / "*.pdf")):
            path = Path(pdf_path_str)
            stem = path.stem
            mq = Q_PART_RE.search(stem)
            if not mq:
                continue  # 不是题目页
            qnum = int(mq.group(1))
            file_tokens = filename_topics_tokens(stem)
            if not file_tokens:
                continue
            if selected_tokens & file_tokens:
                selected.setdefault(key, set()).add(qnum)
    return selected

def find_answer_pdfs(question_selection: Dict[Key, Set[int]]) -> List[Tuple[Path, str, int]]:
    """
    在 MS_DIR 中查找与 question_selection 对应的答案 PDF。
    返回 [(path, ms_folder_name, qnum)]，便于排序。
    """
    results: List[Tuple[Path, str, int]] = []
    if not MS_DIR.is_dir():
        return results

    # 为快速查找，把 keys 按 (subject, season, yy, comp) 做成集合
    wanted_keys = set(question_selection.keys())

    for entry in MS_DIR.iterdir():
        if not entry.is_dir():
            continue
        mm = FOLDER_MS_RE.match(entry.name)
        if not mm:
            continue

        key: Key = (
            mm.group("subject"),
            mm.group("season").lower(),
            mm.group("yy"),
            mm.group("comp"),
        )

        if key not in wanted_keys:
            continue

        wanted_qs = question_selection[key]
        if not wanted_qs:
            continue

        # 在该 ms 文件夹里找 Q号匹配的 pdf
        for pdf_path_str in glob.glob(str(entry / "*.pdf")):
            p = Path(pdf_path_str)
            m_q = re.search(r"(?i)_Q(\d+)(?:_|$)", p.stem)
            if not m_q:
                continue
            qnum = int(m_q.group(1))
            if qnum in wanted_qs:
                results.append((p, entry.name, qnum))

    # 排序：先按 ms 文件夹名，再按题号
    results.sort(key=lambda t: (t[1], t[2], t[0].name))
    return results

def merge_pdfs(paths: List[Path], out_path: Path):
    merger = PdfMerger()
    for p in paths:
        merger.append(str(p))
    ensure_dir(out_path.parent)
    with open(out_path, "wb") as f:
        merger.write(f)
    merger.close()

# ---------------- GUI ----------------
class MultiSelectListbox(ttk.Frame):
    def __init__(self, master, options, height=10):
        super().__init__(master)
        self.listbox = tk.Listbox(self, selectmode=tk.MULTIPLE, height=height, exportselection=False)
        for opt in options:
            self.listbox.insert(tk.END, opt)
        self.listbox.pack(fill=tk.BOTH, expand=True)
    def get_selected(self) -> List[str]:
        idxs = self.listbox.curselection()
        return [self.listbox.get(i) for i in idxs]

class SingleSelectListbox(ttk.Frame):
    def __init__(self, master, options, height=8):
        super().__init__(master)
        self.listbox = tk.Listbox(self, selectmode=tk.SINGLE, height=height, exportselection=False)
        for opt in options:
            self.listbox.insert(tk.END, opt)
        self.listbox.pack(fill=tk.BOTH, expand=True)
        if options:
            self.listbox.selection_set(0)
    def get_selected(self) -> str:
        sel = self.listbox.curselection()
        return self.listbox.get(sel[0]) if sel else ""

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(1080, 640)

        left = ttk.Frame(self)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        ttk.Label(left, text="年份（多选）").pack(anchor="w")
        self.year_box = MultiSelectListbox(left, YEARS, height=8)
        self.year_box.pack(fill=tk.BOTH, expand=True, pady=(0,10))

        ttk.Label(left, text="季节（多选）").pack(anchor="w")
        self.season_box = MultiSelectListbox(left, list(SEASON_CODE.keys()), height=6)
        self.season_box.pack(fill=tk.BOTH, expand=True, pady=(0,10))

        ttk.Label(left, text="卷别（单选）").pack(anchor="w")
        # 读取 9709 的卷别
        self.components_data = list_components("9709")  # [{"component":"1","title":"Pure Mathematics 1 (P1)"}, ...]
        component_titles = [f'{c["component"]} — {c["title"]}' for c in self.components_data]
        self.comp_box = SingleSelectListbox(left, component_titles, height=8)
        self.comp_box.pack(fill=tk.BOTH, expand=True, pady=(0,10))

        right = ttk.Frame(self)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.topic_label = ttk.Label(right, text="Topics（多选）")
        self.topic_label.pack(anchor="w")

        self.topic_box = MultiSelectListbox(right, [], height=18)
        self.topic_box.pack(fill=tk.BOTH, expand=True)

        bottom = ttk.Frame(self)
        bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)

        ttk.Button(bottom, text="根据卷别刷新 Topics", command=self.refresh_topics).pack(side=tk.LEFT, padx=(0,10))
        ttk.Button(bottom, text="生成 Quiz 答案", command=self.run_generation).pack(side=tk.LEFT)
        ttk.Button(bottom, text="选择题目目录 (data/output)", command=self.pick_qp_dir).pack(side=tk.LEFT, padx=(10,0))
        ttk.Button(bottom, text="选择答案目录 (data/output_answers)", command=self.pick_ms_dir).pack(side=tk.LEFT, padx=(10,0))

        self.status = tk.StringVar(value=f"题目：{QP_DIR}｜答案：{MS_DIR}")
        ttk.Label(bottom, textvariable=self.status).pack(side=tk.RIGHT)

        # 初次载入 topics
        self.refresh_topics()

    def _current_component_no(self) -> str:
        sel = self.comp_box.get_selected()
        if not sel:
            return ""
        # 形如 "1 — Pure Mathematics 1 (P1)" -> 取左侧编号
        return sel.split("—", 1)[0].strip().split()[0]

    def refresh_topics(self):
        comp_no = self._current_component_no()
        topics = get_topics("9709", comp_no)  # List[{"id","name"}]
        names = [t["name"] for t in topics]
        self.topic_box.destroy()
        parent = self.topic_label.master
        self.topic_box = MultiSelectListbox(parent, names, height=18)
        self.topic_box.pack(fill=tk.BOTH, expand=True)

    def pick_qp_dir(self):
        global QP_DIR
        new_dir = filedialog.askdirectory(initialdir=str(QP_DIR), title="选择 data/output（题目目录）")
        if new_dir:
            QP_DIR = Path(new_dir)
            self.status.set(f"题目：{QP_DIR}｜答案：{MS_DIR}")

    def pick_ms_dir(self):
        global MS_DIR
        new_dir = filedialog.askdirectory(initialdir=str(MS_DIR), title="选择 data/output_answers（答案目录）")
        if new_dir:
            MS_DIR = Path(new_dir)
            self.status.set(f"题目：{QP_DIR}｜答案：{MS_DIR}")

    def run_generation(self):
        years = self.year_box.get_selected()
        seasons = self.season_box.get_selected()
        comp_no = self._current_component_no()
        topic_names = self.topic_box.get_selected()

        if not years or not seasons or not comp_no or not topic_names:
            messagebox.showwarning("提示", "请至少选择：年份(≥1)、季节(≥1)、卷别(=1)、topics(≥1)")
            return

        # 1) 从题目目录收集命中 topics 的题号
        selected_tokens = selection_topics_tokens(topic_names)
        qp_folders = list_candidate_qp_folders(years, seasons, comp_no)
        if not qp_folders:
            messagebox.showinfo("结果", f"未在题目目录找到匹配文件夹\n题目目录：{QP_DIR}\n示例：9709_w24_qp_12")
            return
        selected_questions = build_selected_questions(qp_folders, selected_tokens)
        total_qs = sum(len(v) for v in selected_questions.values())
        if total_qs == 0:
            messagebox.showinfo("结果", "在题目目录中未找到与所选 topics 匹配的题号")
            return

        # 2) 在答案目录中找对应题号的答案 PDF
        ans_items = find_answer_pdfs(selected_questions)
        if not ans_items:
            messagebox.showinfo("结果", f"在答案目录中未找到对应题号\n答案目录：{MS_DIR}\n命名示例：9709_w24_ms_12_Q4_ANS.pdf")
            return

        # 3) 合并输出
        ensure_dir(QUIZ_ANS_DIR)
        years_str = "-".join(sorted(set(years)))
        seasons_str = "-".join(sorted(seasons))
        ts = time.strftime("%Y%m%d_%H%M%S")
        out_name = f"quiz_answers_{years_str}_{seasons_str}_C{comp_no}_{ts}.pdf"
        out_path = QUIZ_ANS_DIR / out_name

        try:
            merge_pdfs([p for (p, _, _) in ans_items], out_path)
        except Exception as e:
            messagebox.showerror("合并失败", f"合并答案 PDF 时出错：{e}")
            return

        messagebox.showinfo(
            "完成",
            f"已生成：{out_path}\n\n命中题号共 {total_qs} 个；合并答案 PDF 共 {len(ans_items)} 个。"
        )

if __name__ == "__main__":
    app = App()
    app.mainloop()
