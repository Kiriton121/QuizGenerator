
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_TITLE = "Past Paper 管理器 · 多选UI"
WINDOW_MIN_W, WINDOW_MIN_H = 980, 480

YEARS = [str(y) for y in range(2018, 2026)]
SEASONS = ["Winter", "Spring", "Summer"]
SUBJECTS = ["Pure 1", "Pure 2&3", "M1", "S"]  # 单选

PAPER_TOPICS = {
    "Pure 1":   ["Functions", "Algebra", "Trigonometry", "Calculus (basic)"],
    "Pure 2&3": ["Advanced Algebra", "Series & Sequences", "Differentiation", "Integration", "Complex Numbers"],
    "M1":       ["Kinematics", "Forces", "Equilibrium", "Work & Energy", "Momentum"],
    "S":        ["Probability", "Distributions", "Estimation", "Hypothesis Testing"],
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

        self._build_ui()
        self._refresh_topics()

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
        self._make_radio_row(subject_box, SUBJECTS, self.subject_var, command=self._refresh_topics)

        # 行3：Topic（随“考试科目”变化，可多选）
        row3 = ttk.LabelFrame(root, text="Topic（可多选，随考试科目变化）", padding=(10, 8))
        row3.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        self.lb_topics = tk.Listbox(row3, height=10, exportselection=False, selectmode=tk.MULTIPLE)
        self.lb_topics.pack(fill=tk.BOTH, expand=True)

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

    # =============== 行为（占位） ===============
    def _refresh_topics(self):
        subject = self.subject_var.get()
        topics = PAPER_TOPICS.get(subject, [])
        self.lb_topics.delete(0, tk.END)
        for t in topics:
            self.lb_topics.insert(tk.END, t)

    def _on_import_pdf(self):
        filedialog.askopenfilenames(title="选择 PDF 文件", filetypes=[("PDF 文件", "*.pdf")])
        messagebox.showinfo("提示", "当前为 UI 原型：仅选择文件，不做任何处理。")

    def _on_generate_quiz(self):
        years = [y for y, v in self.year_vars.items() if v.get()]
        seasons = [s for s, v in self.season_vars.items() if v.get()]
        subject = self.subject_var.get()
        topics = [self.lb_topics.get(i) for i in self.lb_topics.curselection()]

        messagebox.showinfo(
            "生成 Quiz（占位）",
            "Year(s): " + (", ".join(years) if years else "未选") + "\n"
            "Season(s): " + (", ".join(seasons) if seasons else "未选") + "\n"
            f"Subject: {subject}\n"
            "Topic(s): " + (", ".join(topics) if topics else "未选")
        )

if __name__ == "__main__":
    App().mainloop()
