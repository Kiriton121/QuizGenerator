import sys
import subprocess
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# 从 topics.py 动态获取卷别与 topics
from topics import list_components, get_topics
# 生成 Quiz/答案的大合并逻辑
from quiz_pair import build_quiz_and_answers


APP_TITLE = "Past Paper 管理器 · 多选UI"
WINDOW_MIN_W, WINDOW_MIN_H = 980, 520

# 年份 / 季节（与 quiz_pair 一致）
YEARS = [str(y) for y in range(2018, 2026)]
SEASONS = ["Winter", "Spring", "Summer"]

# 科目代码（你的 topics.py 里定义的是 9709）
SUBJECT_CODE = "9709"

# 从 topics.py 读出卷别（component）及其标题
COMPONENTS = list_components(SUBJECT_CODE)             # [{'component':'1','title':'Pure Mathematics 1 (P1)'}, ...]
SUBJECTS = [c["component"] for c in COMPONENTS]        # ['1','2','3','4','5']
SUBJECT_TITLES = {c["component"]: c["title"] for c in COMPONENTS}

BASE_DIR = Path(__file__).resolve().parent


def _guess_kind_by_name(filename: str) -> str | None:
    """根据文件名判断是题目(qp)还是答案(ms)。"""
    n = filename.lower()
    if "_qp_" in n:
        return "qp"
    if "_ms_" in n:
        return "ms"
    return None


def _launch_tool(kind: str, pdf_path: str):
    """用当前解释器启动对应脚本，并把 --file 传过去。"""
    script = BASE_DIR / ("read_pdf_questions.py" if kind == "qp" else "read_pdf_answers.py")
    if not script.exists():
        messagebox.showerror("错误", f"找不到脚本：{script}")
        return
    try:
        subprocess.Popen([sys.executable, str(script), "--file", pdf_path])
    except Exception as e:
        messagebox.showerror("启动失败", f"无法启动 {script.name}：\n{e}")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(WINDOW_MIN_W, WINDOW_MIN_H)

        # 状态变量
        self.year_vars: dict[str, tk.BooleanVar] = {}
        self.season_vars: dict[str, tk.BooleanVar] = {}
        # 直接存“卷别数字”作为 value（'1'/'2'/...）
        self.subject_var = tk.StringVar(value=(SUBJECTS[0] if SUBJECTS else ""))

        # topic 勾选变量（随科目变化）
        self.topic_vars: dict[str, tk.BooleanVar] = {}

        self._build_ui()
        self._on_subject_changed()  # 初始化时刷新

    # =============== UI ===============
    def _build_ui(self):
        root = ttk.Frame(self, padding=16)
        root.pack(fill=tk.BOTH, expand=True)

        # 行1：年份（多选，横向展开）
        row1 = ttk.LabelFrame(root, text="年份（可多选）", padding=(10, 8))
        row1.pack(fill=tk.X)
        self._make_check_row(row1, YEARS, self.year_vars)

        # 行2：季节（多选） + 考试科目（单选）
        row2 = ttk.Frame(root)
        row2.pack(fill=tk.X, pady=(12, 0))

        season_box = ttk.LabelFrame(row2, text="季节（可多选）", padding=(10, 8))
        season_box.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self._make_check_row(season_box, SEASONS, self.season_vars)

        subject_box = ttk.LabelFrame(row2, text="考试科目（单选）", padding=(10, 8))
        subject_box.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 单选：显示标题，value 为卷别数字
        self._make_radio_row_pairs(
            subject_box,
            [(c["component"], c["title"]) for c in COMPONENTS],
            self.subject_var,
            command=self._on_subject_changed
        )

        # 科目全名提示
        self.lbl_subject_full = ttk.Label(root, text="", foreground="#555")
        self.lbl_subject_full.pack(anchor="w", pady=(6, 0))

        # 行3：Topic（随科目变化，可多选）
        self.topic_box = ttk.LabelFrame(root, text="Topic（可多选，随考试科目变化）", padding=(10, 8))
        self.topic_box.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

        # 行4：按钮
        row4 = ttk.Frame(root)
        row4.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(row4, text="导入 PDF", command=self._on_import_pdf).pack(side=tk.LEFT)
        ttk.Button(row4, text="生成 Quiz", command=self._on_generate_quiz).pack(side=tk.LEFT, padx=10)

    # —— 工具：一行横向 Checkbutton 组
    def _make_check_row(self, parent: ttk.Frame, options: list[str], var_dict: dict[str, tk.BooleanVar]):
        row = ttk.Frame(parent)
        row.pack(fill=tk.X)
        for text in options:
            var = tk.BooleanVar(value=False)
            var_dict[text] = var
            cb = ttk.Checkbutton(row, text=text, variable=var)
            cb.pack(side=tk.LEFT, padx=(0, 10))

    # —— 工具：一行横向 Radiobutton 组（value/label）
    def _make_radio_row_pairs(self, parent: ttk.Frame, options: list[tuple[str, str]], var: tk.StringVar, command=None):
        row = ttk.Frame(parent)
        row.pack(fill=tk.X)
        for value, label in options:
            rb = ttk.Radiobutton(row, text=label, value=value, variable=var, command=command)
            rb.pack(side=tk.LEFT, padx=(0, 10))

    # =============== 行为 ===============
    def _on_subject_changed(self):
        """更新科目提示和 topics 区域"""
        comp_no = self.subject_var.get()                   # '1' / '2' / ...
        full = SUBJECT_TITLES.get(comp_no, comp_no)
        self.lbl_subject_full.config(text=f"当前科目： {full}")
        self._refresh_topics_checkbuttons()

    def _refresh_topics_checkbuttons(self):
        """根据科目重建 topics 勾选框（来自 topics.py）"""
        for child in self.topic_box.winfo_children():
            child.destroy()
        self.topic_vars.clear()

        comp_no = self.subject_var.get()
        topics = [t["name"] for t in (get_topics(SUBJECT_CODE, comp_no) or [])]

        if not topics:
            ttk.Label(self.topic_box, text="（无可选 Topic 或未解析到）", foreground="#888").pack(anchor="w", padx=8, pady=8)
            return

        # 平铺小方框
        cols = 2  # 可调整列数
        grid = ttk.Frame(self.topic_box)
        grid.pack(fill=tk.BOTH, expand=True)
        for i, t in enumerate(topics):
            var = tk.BooleanVar(value=False)
            self.topic_vars[t] = var
            cb = ttk.Checkbutton(grid, text=t, variable=var)
            r, c = divmod(i, cols)
            cb.grid(row=r, column=c, sticky="w", padx=6, pady=4)
        for c in range(cols):
            grid.grid_columnconfigure(c, weight=1)

    def _get_selected_topics(self) -> list[str]:
        return [name for name, var in self.topic_vars.items() if var.get()]

    def _on_import_pdf(self):
        paths = filedialog.askopenfilenames(
            title="选择 PDF 文件（可多选）",
            filetypes=[("PDF 文件", "*.pdf")]
        )
        if not paths:
            return

        for p in paths:
            p = str(p)
            kind = _guess_kind_by_name(Path(p).name)
            if kind is None:
                # 文件名无法直接判断时，给一次手动选择
                is_qp = messagebox.askyesno(
                    "无法判断类型",
                    f"无法从文件名识别是题目(qp)还是答案(ms)：\n\n{p}\n\n"
                    "选择“是”按题目(qp)打开；“否”按答案(ms)打开。"
                )
                kind = "qp" if is_qp else "ms"
            _launch_tool(kind, p)

    def _on_generate_quiz(self):
        try:
            # 1) 取 UI 选择
            years   = [y for y, v in self.year_vars.items()   if v.get()]
            seasons = [s for s, v in self.season_vars.items() if v.get()]
            comp_no = self.subject_var.get()                  # 直接就是 '1'/'2'/...
            topics  = self._get_selected_topics()

            if not years or not seasons or not comp_no or not topics:
                messagebox.showwarning("提示", "请至少选择：年份(≥1)、季节(≥1)、科目(=1)、Topics(≥1)")
                return

            # 2) 调用生成器（是否随机可按需开关）
            quiz_path, ans_path, stats = build_quiz_and_answers(
                years=years,
                seasons=seasons,
                comp_no=str(comp_no),
                topics=topics,
                shuffle=False,   # 想随机就 True；题目与答案会按同一顺序
                seed=None,
            )

            # 3) 结果提示
            if not quiz_path:
                messagebox.showinfo("结果", stats.get("msg", "未生成任何文件"))
                return

            msg = f"题目已生成：\n{stats['output_quiz']}\n\n"
            if ans_path:
                msg += f"答案已生成：\n{stats['output_answers']}\n\n"
            else:
                msg += "未生成答案PDF（未找到任何对应答案）。\n\n"
            msg += f"匹配题目：{stats['matched_questions']}；题目页数：{stats['quiz_pages']}；答案页数：{stats['answer_pages']}\n"
            if stats.get("missing_answers", 0):
                msg += f"缺失答案：{stats['missing_answers']}（请检查 data/output_answers 的命名是否含 _Qn_）"
            messagebox.showinfo("完成", msg)

        except Exception as e:
            messagebox.showerror("合并失败", f"{e}\n\n{traceback.format_exc()}")


if __name__ == "__main__":
    App().mainloop()
