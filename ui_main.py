import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_TITLE = "Past Paper 管理器 · 多选UI"
WINDOW_MIN_W, WINDOW_MIN_H = 980, 520

YEARS = [str(y) for y in range(2018, 2026)]
SEASONS = ["Winter", "Spring", "Summer"]

# ---- 科目（单选，用短代号）----
SUBJECTS = ["pure1", "pure2", "pure3", "M1", "S1"]

# 短代号 -> 全名（用于显示/提示）
SUBJECT_TITLES = {
    "pure1": "Pure Mathematics 1 (P1)",
    "pure2": "Pure Mathematics 2 (P2)",
    "pure3": "Pure Mathematics 3 (P3)",
    "M1":    "Mechanics (M1)",
    "S1":    "Probability & Statistics 1 (S1)",
}

# 短代号 -> topics 列表（顺序即显示顺序）
PAPER_TOPICS = {
    "pure1": [
        "Quadratics",
        "Functions",
        "Coordinate geometry",
        "Circular measure",
        "Trigonometry",
        "Series",
        "Differentiation",
        "Integration",
    ],
    "pure2": [
        "Algebra",
        "Logarithmic and exponential functions",
        "Trigonometry",
        "Differentiation",
        "Integration",
        "Numerical methods",
    ],
    "pure3": [
        "Algebra & functions",
        "Logarithmic and exponential functions",
        "Trigonometry",
        "Differentiation",
        "Integration",
        "Numerical solution of equations",
        "Vectors in 2D/3D",
        "Differential equations",
        "Complex numbers",
    ],
    "M1": [
        "Forces and equilibrium",
        "Kinematics of motion in a straight line",
        "Energy, work and power",
        "Momentum and impulse",
        "Motion of a projectile",
        "Uniform circular motion",
        "Centres of mass",
        "Hooke’s law, elastic strings and springs",
    ],
    "S1": [
        "Representation of data",
        "Permutations and combinations",
        "Probability",
        "Discrete random variables",
        "The normal distribution",
        "Sampling and estimation",
        "Hypothesis testing",
    ],
}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(WINDOW_MIN_W, WINDOW_MIN_H)

        # 状态变量
        self.year_vars: dict[str, tk.BooleanVar] = {}
        self.season_vars: dict[str, tk.BooleanVar] = {}
        self.subject_var = tk.StringVar(value=SUBJECTS[0])

        # topic 勾选变量
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
        self._make_radio_row(subject_box, SUBJECTS, self.subject_var, command=self._on_subject_changed)

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

    # —— 工具：一行横向 Radiobutton 组（单选）
    def _make_radio_row(self, parent: ttk.Frame, options: list[str], var: tk.StringVar, command=None):
        row = ttk.Frame(parent)
        row.pack(fill=tk.X)
        for text in options:
            rb = ttk.Radiobutton(row, text=text, value=text, variable=var, command=command)
            rb.pack(side=tk.LEFT, padx=(0, 10))

    # =============== 行为 ===============
    def _on_subject_changed(self):
        """更新科目提示和 topics 区域"""
        short = self.subject_var.get()
        full = SUBJECT_TITLES.get(short, short)
        self.lbl_subject_full.config(text=f"当前科目：{full}")
        self._refresh_topics_checkbuttons()

    def _refresh_topics_checkbuttons(self):
        """根据科目重建 topics 勾选框"""
        for child in self.topic_box.winfo_children():
            child.destroy()
        self.topic_vars.clear()

        subject_key = self.subject_var.get()
        topics = PAPER_TOPICS.get(subject_key, [])

        if not topics:
            ttk.Label(self.topic_box, text="（无可选 Topic）", foreground="#888").pack(anchor="w", padx=8, pady=8)
            return

        # 平铺小方框
        cols = 2  # 改为 1/3 也行
        for i, t in enumerate(topics):
            var = tk.BooleanVar(value=False)
            self.topic_vars[t] = var
            cb = ttk.Checkbutton(self.topic_box, text=t, variable=var)
            r, c = divmod(i, cols)
            cb.grid(row=r, column=c, sticky="w", padx=6, pady=4)

        for c in range(cols):
            self.topic_box.grid_columnconfigure(c, weight=1)

    def _get_selected_topics(self) -> list[str]:
        return [name for name, var in self.topic_vars.items() if var.get()]

    def _on_import_pdf(self):
        filedialog.askopenfilenames(title="选择 PDF 文件", filetypes=[("PDF 文件", "*.pdf")])
        messagebox.showinfo("提示", "当前为 UI 原型：仅选择文件，不做任何处理。")

    def _on_generate_quiz(self):
        years = [y for y, v in self.year_vars.items() if v.get()]
        seasons = [s for s, v in self.season_vars.items() if v.get()]
        subject_key = self.subject_var.get()
        subject_full = SUBJECT_TITLES.get(subject_key, subject_key)
        topics = self._get_selected_topics()

        messagebox.showinfo(
            "生成 Quiz（占位）",
            "Year(s): " + (", ".join(years) if years else "未选") + "\n"
            "Season(s): " + (", ".join(seasons) if seasons else "未选") + "\n"
            f"Subject: {subject_key}  ·  {subject_full}\n"
            "Topic(s): " + (", ".join(topics) if topics else "未选")
        )


if __name__ == "__main__":
    App().mainloop()
