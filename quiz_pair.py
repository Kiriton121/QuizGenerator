# quiz_pair.py
# 依据 UI 选择（年/季/卷别/Topics）从 data/output 与 data/output_answers
# 匹配题目与答案 PDF，并按同一顺序合并输出到 data/quiz 与 data/quiz_answers。
# 题目合并 PDF 会在每道题的第 1 页叠加新的题号（Q1、Q2、…），
# 且当同一道题跨多页时，后续页会用“空白矩形”覆盖同一位置的页码（仅覆盖不写字）。
#
# 依赖：
#   - PyPDF2 或 pypdf（二选一，自动兼容）
#   - reportlab（用于覆盖/写字；缺失时退回“只合并不编号”）

from __future__ import annotations

import glob
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# ====== 兼容多种 PDF 后端 ======
PdfMerger = PdfReader = PdfWriter = None
try:
    from PyPDF2 import PdfMerger  # 优先
except Exception:
    try:
        from pypdf import PdfMerger  # 备选
    except Exception:
        PdfMerger = None

try:
    if PdfMerger is None:
        from PyPDF2 import PdfReader, PdfWriter
except Exception:
    try:
        from pypdf import PdfReader, PdfWriter
    except Exception:
        PdfReader = PdfWriter = None

# reportlab（用于叠加新题号/覆盖页码）
try:
    from io import BytesIO
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.lib.colors import black, white
except Exception:  # pragma: no cover
    canvas = None  # 运行时检测


# ====== 目录结构 ======
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
QP_DIR = DATA_DIR / "output"           # 题目目录（每个试卷一个子文件夹）
MS_DIR = DATA_DIR / "output_answers"   # 答案目录（每个试卷一个子文件夹）
QUIZ_DIR = DATA_DIR / "quiz"
QUIZ_ANS_DIR = DATA_DIR / "quiz_answers"

# ====== Cambridge 命名规则 ======
# 题目文件夹： 9709_w24_qp_11
# 答案文件夹： 9709_w24_ms_12
FOLDER_QP_RE = re.compile(
    r"^(?P<subject>\d{4})_(?P<season>[wsm])(?P<yy>\d{2})_qp_(?P<comp>\d{2})$",
    re.IGNORECASE,
)
FOLDER_MS_RE = re.compile(
    r"^(?P<subject>\d{4})_(?P<season>[wsm])(?P<yy>\d{2})_ms_(?P<comp>\d{2})$",
    re.IGNORECASE,
)

# 题号特征：_Q<n>_
Q_PART_RE = re.compile(r"(?i)_Q(\d+)_")

# token 提取（忽略大小写，字母数字）
TOKEN_RE = re.compile(r"[a-z0-9]+")

# UI季节 -> 文件夹季节字符
SEASON_CODE = {"Winter": "w", "Summer": "s", "Spring": "m"}


@dataclass(frozen=True)
class QKey:
    subject: str        # 9709
    season: str         # w/s/m
    yy: str             # 两位年份，如 "24"
    comp2: str          # 两位卷别，如 "11"/"12"/"41"...


@dataclass
class QItem:
    key: QKey
    qnum: int
    qp_path: Path
    ms_path: Optional[Path] = None  # 匹配到的答案 PDF（可为空）


# ====== 工具函数 ======
def _normalize_tokens(s: str) -> List[str]:
    return TOKEN_RE.findall(s.lower())


def _filename_topic_tokens(stem: str) -> Set[str]:
    """
    只提取 _Qn_ 之后的片段作为 topic 关键词，支持 Coordinate_geometry -> {'coordinate','geometry'}
    """
    m = Q_PART_RE.search(stem)
    if not m:
        return set()
    tail = stem[m.end():]
    toks: Set[str] = set()
    for seg in tail.split("_"):
        toks.update(_normalize_tokens(seg))
    return toks


def _season_ok(picked: List[str], season_char: str) -> bool:
    for name, code in SEASON_CODE.items():
        if code == season_char and name in picked:
            return True
    return False


def _list_qp_folders(years: List[str], seasons: List[str], comp_no: str) -> List[Path]:
    """
    列出 data/output 下所有匹配 年份/季节/卷别(首位) 的题目文件夹
    """
    if not QP_DIR.is_dir():
        return []
    res: List[Path] = []
    for entry in QP_DIR.iterdir():
        if not entry.is_dir():
            continue
        m = FOLDER_QP_RE.match(entry.name)
        if not m:
            continue
        yy = m.group("yy")
        season = m.group("season").lower()
        comp2 = m.group("comp")  # 例如 "11" / "12" / "41" ...
        if not any(y.endswith(yy) for y in years):
            continue
        if not _season_ok(seasons, season):
            continue
        if (comp2 or "")[:1] != str(comp_no):  # 只看首位：1/2/3/4/5
            continue
        res.append(entry)
    return res


def _build_manifest(years: List[str], seasons: List[str], comp_no: str, topic_names: List[str]) -> List[QItem]:
    """
    汇总所有命中的题目 PDF，生成 QItem 列表（尚未绑定答案）。
    """
    qp_folders = _list_qp_folders(years, seasons, comp_no)
    if not qp_folders:
        return []

    # 选中 topics 的 token 集（OR 策略）
    sel_tokens: Set[str] = set()
    for name in topic_names:
        sel_tokens.update(_normalize_tokens(name))

    manifest: List[QItem] = []
    seen_qp: Set[Path] = set()

    for folder in qp_folders:
        m = FOLDER_QP_RE.match(folder.name)
        key = QKey(
            subject=m.group("subject"),
            season=m.group("season").lower(),
            yy=m.group("yy"),
            comp2=m.group("comp"),
        )
        for s in glob.glob(str(folder / "*.pdf")):
            p = Path(s)
            if p in seen_qp:
                continue
            stem = p.stem
            mq = Q_PART_RE.search(stem)
            if not mq:
                continue
            qnum = int(mq.group(1))
            if not sel_tokens:
                manifest.append(QItem(key=key, qnum=qnum, qp_path=p))
                seen_qp.add(p)
                continue
            ftoks = _filename_topic_tokens(stem)
            if sel_tokens & ftoks:  # 有交集即命中
                manifest.append(QItem(key=key, qnum=qnum, qp_path=p))
                seen_qp.add(p)

    manifest.sort(key=lambda it: (it.key.subject, it.key.season, it.key.yy, it.key.comp2, it.qnum, it.qp_path.name))
    return manifest


def _index_ms_folders() -> Dict[QKey, Path]:
    """
    把答案文件夹建立索引：QKey -> 文件夹 Path
    """
    idx: Dict[QKey, Path] = {}
    if not MS_DIR.is_dir():
        return idx
    for entry in MS_DIR.iterdir():
        if not entry.is_dir():
            continue
        m = FOLDER_MS_RE.match(entry.name)
        if not m:
            continue
        key = QKey(
            subject=m.group("subject"),
            season=m.group("season").lower(),
            yy=m.group("yy"),
            comp2=m.group("comp"),
        )
        idx[key] = entry
    return idx


def _attach_answers(manifest: List[QItem]) -> Tuple[List[QItem], List[QItem]]:
    """
    为每个 QItem 匹配答案 PDF（若有）
    返回：(已附答案的清单, 未匹配成功的清单)
    """
    idx = _index_ms_folders()
    missing: List[QItem] = []
    for it in manifest:
        ms_folder = idx.get(it.key)
        if not ms_folder:
            missing.append(it)
            continue
        candidates = sorted(Path(p) for p in glob.glob(str(ms_folder / "*.pdf")))
        pat = re.compile(rf"(?i)_Q{it.qnum}(?:_|$)")
        found = None
        for p in candidates:
            if pat.search(p.stem):
                found = p
                break
        if found:
            it.ms_path = found
        else:
            missing.append(it)
    return manifest, missing


# ====== 合并函数（降级兼容）======
def merge_pdfs(paths: List[Path], out_path: Path):
    """
    纯合并（不加题号），自动兼容 PyPDF2 / pypdf；
    两者都不可用则抛错。
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not paths:
        raise RuntimeError("没有可合并的 PDF")
    if PdfMerger is not None:
        merger = PdfMerger()
        for p in paths:
            merger.append(str(p))
        with open(out_path, "wb") as f:
            merger.write(f)
        try:
            merger.close()
        except Exception:
            pass
        return
    if PdfReader is not None and PdfWriter is not None:
        writer = PdfWriter()
        for p in paths:
            r = PdfReader(str(p))
            for pg in r.pages:
                writer.add_page(pg)
        with open(out_path, "wb") as f:
            writer.write(f)
        return
    raise RuntimeError("无法合并PDF：未找到可用的 PyPDF2/pypdf")


# ====== 叠加题号：顶部/底部中间，第一页写 “Qn”，其余页白底覆盖 ======
def _box_metrics(box):
    """同时兼容 pypdf / PyPDF2 获取 box 的左下角与宽高"""
    def _get(obj, *names, default=None):
        for n in names:
            if hasattr(obj, n):
                return getattr(obj, n)
        return default

    # 左、下
    left = float(_get(box, "left", default=(getattr(box, "lower_left", (0, 0))[0])))
    bottom = float(_get(box, "bottom", default=(getattr(box, "lower_left", (0, 0))[1])))

    # 宽、高
    width = _get(box, "width", default=None)
    height = _get(box, "height", default=None)
    if width is None or height is None:
        right = float(_get(box, "right", default=(getattr(box, "upper_right", (0, 0))[0])))
        top = float(_get(box, "top", default=(getattr(box, "upper_right", (0, 0))[1])))
        width = float(right - left)
        height = float(top - bottom)
    return left, bottom, float(width), float(height)


def _merge_with_numbers(
    question_pdfs: List[Path],
    out_path: Path,
    label_fmt: str = "Q{n}",
    where: str = "TC",     # TL / TR / BL / BR / TC(顶部中间) / BC(底部中间)
    margin: int = 18,      # 与边缘或上/下边的距离
    font_size: int = 18,
    blank_other_pages: bool = True,  # 同一题的第2页起只覆盖空白，不写字
):
    """
    把编号叠加到每道题的第1页；若题目跨多页，则其余页在同一位置画白底覆盖页码。
    只在 where=TC/BC 时做“白底覆盖”，四角位置通常不需要盖页码。
    """
    if not question_pdfs:
        raise RuntimeError("没有可合并的 PDF")
    if canvas is None:
        # 没有 reportlab 就退回普通合并
        merge_pdfs(question_pdfs, out_path)
        return

    # 选择 Reader/Writer
    Reader = Writer = None
    try:
        from PyPDF2 import PdfReader as Reader, PdfWriter as Writer
    except Exception:
        try:
            from pypdf import PdfReader as Reader, PdfWriter as Writer
        except Exception:
            merge_pdfs(question_pdfs, out_path)
            return

    writer = Writer()
    center_mode = where.upper() in ("TC", "BC")

    for idx, pdf_path in enumerate(question_pdfs, start=1):
        lbl = label_fmt.format(n=idx)
        r = Reader(str(pdf_path))

        # 用标签文字估一个“需要覆盖的宽度”，至少 140pt
        try:
            text_w = stringWidth(lbl, "Helvetica-Bold", font_size)
        except Exception:
            text_w = max(font_size * 0.6 * len(lbl), font_size * 2)
        rect_w = max(140, text_w + 16)       # 覆盖条形码旁边的页码，常用宽度
        rect_h = font_size + 6

        for p_i, page in enumerate(r.pages):
            # 画布/可视区
            mb_left, mb_bottom, mb_w, mb_h = _box_metrics(page.mediabox)
            crop = getattr(page, "cropbox", page.mediabox)
            cb_left, cb_bottom, cb_w, cb_h = _box_metrics(crop)

            need_label = (p_i == 0)
            need_blank = (p_i > 0 and blank_other_pages and center_mode)

            if not need_label and not need_blank:
                # 不需要盖也不需要写
                writer.add_page(page)
                continue

            # 生成覆盖页
            buff = BytesIO()
            c = canvas.Canvas(buff, pagesize=(mb_w, mb_h))
            c.setFont("Helvetica-Bold", font_size)

            # 计算位置（中上 / 中下）
            if where.upper() == "TC":
                rect_x = cb_left + cb_w / 2 - rect_w / 2
                rect_y = cb_bottom + cb_h - margin - rect_h
            elif where.upper() == "BC":
                rect_x = cb_left + cb_w / 2 - rect_w / 2
                rect_y = cb_bottom + margin
            else:
                # 四角模式：第1页写字；其它页不做任何遮挡
                if need_label:
                    # 简单放四角（不覆盖）
                    if where.upper() == "TL":
                        x = cb_left + margin
                        y = cb_bottom + cb_h - margin - font_size
                    elif where.upper() == "TR":
                        x = cb_left + cb_w - margin - text_w
                        y = cb_bottom + cb_h - margin - font_size
                    elif where.upper() == "BL":
                        x = cb_left + margin
                        y = cb_bottom + margin
                    else:  # BR
                        x = cb_left + cb_w - margin - text_w
                        y = cb_bottom + margin
                    c.drawString(x, y, lbl)
                c.save()
                buff.seek(0)
                ov = Reader(buff).pages[0]
                try:
                    page.merge_page(ov)
                except Exception:
                    page.mergePage(ov)
                writer.add_page(page)
                continue

            # —— TC/BC：统一先画白底矩形
            c.setFillColor(white)
            c.rect(rect_x, rect_y, rect_w, rect_h, fill=1, stroke=0)

            if need_label:
                # 第1页写“Qn”（居中）
                c.setFillColor(black)
                text_x = rect_x + (rect_w - text_w) / 2
                text_y = rect_y + (rect_h - font_size) / 2
                c.drawString(text_x, text_y, lbl)

            c.save()
            buff.seek(0)
            ov = Reader(buff).pages[0]
            try:
                page.merge_page(ov)
            except Exception:
                page.mergePage(ov)

            writer.add_page(page)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        writer.write(f)


# ====== 对外主函数 ======
def build_quiz_and_answers(
    years: List[str],
    seasons: List[str],
    comp_no: str,              # 卷别的“首位数字”：'1'/'2'/'3'/'4'/'5'
    topics: List[str],
    shuffle: bool = False,
    seed: Optional[int] = None,
    # 叠加题号（题目合并 PDF）
    renumber_questions: bool = True,
    label_fmt_quiz: str = "Q{n}",
    label_where: str = "TC",   # 顶部中间覆盖
    label_margin: int = 24,
    label_font_size: int = 18,
    # 是否给答案也盖编号（通常不需要）
    renumber_answers: bool = False,
    label_fmt_answers: str = "Q{n}",
):
    """
    返回：(quiz_path, answers_path, stats字典)
    - 若没有匹配到题目：返回 (None, None, {"msg": "未匹配到题目PDF"})
    - stats 含匹配数量、缺失答案数等
    """
    manifest = _build_manifest(years, seasons, comp_no, topics)
    if not manifest:
        return None, None, {"matched_questions": 0, "missing_answers": 0, "msg": "未匹配到题目PDF"}

    manifest, missing = _attach_answers(manifest)

    order = list(range(len(manifest)))
    if shuffle:
        rnd = random.Random(seed)
        rnd.shuffle(order)

    # 输出文件名
    years_str = "-".join(sorted(set(years)))
    seasons_str = "-".join(sorted(seasons))
    ts = time.strftime("%Y%m%d_%H%M%S")

    quiz_path = QUIZ_DIR / f"quiz_{years_str}_{seasons_str}_C{comp_no}_{ts}.pdf"
    ans_path = QUIZ_ANS_DIR / f"quiz_answers_{years_str}_{seasons_str}_C{comp_no}_{ts}.pdf"

    # —— 合并题目（第一页写题号，其它页白盖页码）
    quiz_pages = [manifest[i].qp_path for i in order]
    try:
        if renumber_questions:
            _merge_with_numbers(
                question_pdfs=quiz_pages,
                out_path=quiz_path,
                label_fmt=label_fmt_quiz,
                where=label_where,          # TC/BC 推荐
                margin=label_margin,
                font_size=label_font_size,
                blank_other_pages=True,     # 第2页起仅白盖
            )
        else:
            merge_pdfs(quiz_pages, quiz_path)
    except Exception:
        merge_pdfs(quiz_pages, quiz_path)

    # —— 合并答案（通常不需要编号；若需要可把 renumber_answers=True）
    ans_pages = [manifest[i].ms_path for i in order if manifest[i].ms_path]
    if ans_pages:
        try:
            if renumber_answers:
                _merge_with_numbers(
                    question_pdfs=ans_pages,
                    out_path=ans_path,
                    label_fmt=label_fmt_answers,
                    where=label_where,
                    margin=label_margin,
                    font_size=label_font_size,
                    blank_other_pages=True,
                )
            else:
                merge_pdfs(ans_pages, ans_path)
        except Exception:
            merge_pdfs(ans_pages, ans_path)
    else:
        ans_path = None

    stats = {
        "matched_questions": len(manifest),
        "missing_answers": len(missing),
        "quiz_pages": len(quiz_pages),
        "answer_pages": len(ans_pages),
        "output_quiz": str(quiz_path),
        "output_answers": str(ans_path) if ans_path else None,
    }
    return quiz_path, ans_path, stats


# ====== 命令行调试（可选）======
if __name__ == "__main__":  # 简单自检
    import argparse, json
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="+", default=["2024"])
    ap.add_argument("--seasons", nargs="+", default=["Winter"])
    ap.add_argument("--comp", default="1")
    ap.add_argument("--topics", nargs="+", default=["Quadratics"])
    ap.add_argument("--shuffle", action="store_true")
    args = ap.parse_args()

    qp, apath, st = build_quiz_and_answers(
        years=args.years,
        seasons=args.seasons,
        comp_no=args.comp,
        topics=args.topics,
        shuffle=args.shuffle,
        seed=123,
        renumber_questions=True,
        label_where="TC",       # 顶部中间覆盖
        label_margin=28,
        label_font_size=22,
    )
    print("quiz :", qp)
    print("ans  :", apath)
    print(json.dumps(st, indent=2, ensure_ascii=False))
