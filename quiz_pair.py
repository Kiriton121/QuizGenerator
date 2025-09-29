# quiz_pair.py
import re, glob, time, random
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Optional, Set

# ==== 尝试多种合并实现（PyPDF2 / pypdf），无需你再安装 ====
PdfMerger = PdfReader = PdfWriter = None
try:
    from PyPDF2 import PdfMerger  # 首选
except Exception:
    try:
        from pypdf import PdfMerger  # 次选
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

def merge_pdfs(paths: List[Path], out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not paths:
        raise RuntimeError("没有可合并的 PDF")
    if PdfMerger is not None:
        merger = PdfMerger()
        for p in paths:
            merger.append(str(p))
        with open(out_path, "wb") as f:
            merger.write(f)
        merger.close()
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

# ==== 目录 ====
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
QP_DIR = DATA_DIR / "output"
MS_DIR = DATA_DIR / "output_answers"
QUIZ_DIR = DATA_DIR / "quiz"
QUIZ_ANS_DIR = DATA_DIR / "quiz_answers"

# ==== Cambridge 命名规则 ====
# 例：9709_w24_qp_12   /   9709_w24_ms_12
FOLDER_QP_RE = re.compile(r"^(?P<subject>\d{4})_(?P<season>[wsm])(?P<yy>\d{2})_qp_(?P<comp>\d{2})$", re.IGNORECASE)
FOLDER_MS_RE = re.compile(r"^(?P<subject>\d{4})_(?P<season>[wsm])(?P<yy>\d{2})_ms_(?P<comp>\d{2})$", re.IGNORECASE)
# 题号：文件名里有 _Q<n>_ 片段
Q_PART_RE = re.compile(r"(?i)_Q(\d+)_")
TOKEN_RE = re.compile(r"[a-z0-9]+")

SEASON_CODE = {"Winter": "w", "Summer": "s", "Spring": "m"}

@dataclass(frozen=True)
class QKey:
    subject: str
    season: str   # w/s/m
    yy: str       # 两位年份
    comp2: str    # 两位，如 "11"/"12"

@dataclass
class QItem:
    key: QKey
    qnum: int
    qp_path: Path
    ms_path: Optional[Path] = None

def _normalize_tokens(s: str) -> List[str]:
    return TOKEN_RE.findall(s.lower())

def _filename_topic_tokens(stem: str) -> Set[str]:
    # 只看 _Qn_ 之后的部分（文件里 topics 用下划线拼接）
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
    if not QP_DIR.is_dir():
        return []
    res = []
    for entry in QP_DIR.iterdir():
        if not entry.is_dir():
            continue
        m = FOLDER_QP_RE.match(entry.name)
        if not m:
            continue
        yy = m.group("yy")
        season = m.group("season").lower()
        comp2 = m.group("comp")  # 如 "11"/"12"
        if not any(y.endswith(yy) for y in years):
            continue
        if not _season_ok(seasons, season):
            continue
        if (comp2 or "")[:1] != comp_no:  # 只看卷别第一位
            continue
        res.append(entry)
    return res

def _build_manifest(years: List[str], seasons: List[str], comp_no: str, topic_names: List[str]) -> List[QItem]:
    qp_folders = _list_qp_folders(years, seasons, comp_no)
    if not qp_folders:
        return []

    # 选中的 topic -> token 集合（支持 “Coordinate geometry” 任一词命中）
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
            if sel_tokens & ftoks:
                manifest.append(QItem(key=key, qnum=qnum, qp_path=p))
                seen_qp.add(p)

    manifest.sort(key=lambda it: (it.key.subject, it.key.season, it.key.yy, it.key.comp2, it.qnum, it.qp_path.name))
    return manifest

def _index_ms_folders() -> dict[QKey, Path]:
    idx: dict[QKey, Path] = {}
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

def _attach_answers(manifest: List[QItem]) -> Tuple[List[QItem], list[QItem]]:
    idx = _index_ms_folders()
    missing: List[QItem] = []
    for it in manifest:
        ms_folder = idx.get(it.key)
        if not ms_folder:
            missing.append(it)
            continue
        # 在该 ms 文件夹内寻找含 _Q<qnum> 的 PDF
        candidates = sorted(Path(p) for p in glob.glob(str(ms_folder / "*.pdf")))
        found = None
        pat = re.compile(rf"(?i)_Q{it.qnum}(?:_|$)")
        for p in candidates:
            if pat.search(p.stem):
                found = p
                break
        if found:
            it.ms_path = found
        else:
            missing.append(it)
    return manifest, missing

def build_quiz_and_answers(
    years: List[str],
    seasons: List[str],
    comp_no: str,           # 科目卷别的“首位数字”，如 "1" = P1, "2" = P2 ...
    topics: List[str],
    shuffle: bool = False,
    seed: Optional[int] = None
):
    manifest = _build_manifest(years, seasons, comp_no, topics)
    if not manifest:
        return None, None, {"matched_questions": 0, "missing_answers": 0, "msg": "未匹配到题目PDF"}

    manifest, missing = _attach_answers(manifest)

    order = list(range(len(manifest)))
    if shuffle:
        rnd = random.Random(seed)
        rnd.shuffle(order)

    quiz_pages: List[Path] = []
    ans_pages: List[Path] = []
    for i in order:
        quiz_pages.append(manifest[i].qp_path)
        if manifest[i].ms_path:
            ans_pages.append(manifest[i].ms_path)

    years_str = "-".join(sorted(set(years)))
    seasons_str = "-".join(sorted(seasons))
    ts = time.strftime("%Y%m%d_%H%M%S")

    quiz_path = QUIZ_DIR / f"quiz_{years_str}_{seasons_str}_C{comp_no}_{ts}.pdf"
    ans_path  = QUIZ_ANS_DIR / f"quiz_answers_{years_str}_{seasons_str}_C{comp_no}_{ts}.pdf"

    merge_pdfs(quiz_pages, quiz_path)
    if ans_pages:
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
