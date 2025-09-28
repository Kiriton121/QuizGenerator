# topics_shared.py
import re
from pathlib import Path
from typing import Dict, List, Any, Optional

# === 考试科目与考纲，对应 Cambridge A Level Mathematics ===
TOPIC_MAP: Dict[str, Dict[str, Any]] = {
    "9709": {  # 科目代码
        "name": "Cambridge A Level Mathematics",
        "components": {
            "1": {  # Paper 1 – Pure Mathematics 1 (P1)
                "title": "Pure Mathematics 1 (P1)",
                "topics": [
                    {"id": "quadratics", "name": "Quadratics"},
                    {"id": "functions", "name": "Functions"},
                    {"id": "coordinate_geometry", "name": "Coordinate geometry"},
                    {"id": "circular_measure", "name": "Circular measure"},
                    {"id": "trigonometry", "name": "Trigonometry"},
                    {"id": "series", "name": "Series"},
                    {"id": "differentiation", "name": "Differentiation"},
                    {"id": "integration", "name": "Integration"},
                ],
            },
            "2": {  # Paper 2 – Pure Mathematics 2 (P2)
                "title": "Pure Mathematics 2 (P2)",
                "topics": [
                    {"id": "algebra", "name": "Algebra"},
                    {"id": "log_exp", "name": "Logarithmic and exponential functions"},
                    {"id": "trigonometry", "name": "Trigonometry"},
                    {"id": "differentiation", "name": "Differentiation"},
                    {"id": "integration", "name": "Integration"},
                    {"id": "numerical_methods", "name": "Numerical methods"},
                ],
            },
            "3": {  # Paper 3 – Pure Mathematics 3 (P3)
                "title": "Pure Mathematics 3 (P3)",
                "topics": [
                    {"id": "algebra_functions", "name": "Algebra & functions"},
                    {"id": "log_exp", "name": "Logarithmic and exponential functions"},
                    {"id": "trigonometry", "name": "Trigonometry"},
                    {"id": "differentiation", "name": "Differentiation"},
                    {"id": "integration", "name": "Integration"},
                    {"id": "numerical_equations", "name": "Numerical solution of equations"},
                    {"id": "vectors", "name": "Vectors in 2D/3D"},
                    {"id": "diff_eq", "name": "Differential equations"},
                    {"id": "complex_numbers", "name": "Complex numbers"},
                ],
            },
            "4": {  # Paper 4 – Mechanics (M1)
                "title": "Mechanics (M1)",
                "topics": [
                    {"id": "forces_equilibrium", "name": "Forces and equilibrium"},
                    {"id": "kinematics", "name": "Kinematics of motion in a straight line"},
                    {"id": "energy_work_power", "name": "Energy, work and power"},
                    {"id": "momentum_impulse", "name": "Momentum and impulse"},
                    {"id": "projectile", "name": "Motion of a projectile"},
                    {"id": "circular_motion", "name": "Uniform circular motion"},
                    {"id": "centres_mass", "name": "Centres of mass"},
                    {"id": "hooke_law", "name": "Hooke’s law, elastic strings and springs"},
                ],
            },
            "5": {  # Paper 5 – Probability & Statistics 1 (S1)
                "title": "Probability & Statistics 1 (S1)",
                "topics": [
                    {"id": "data", "name": "Representation of data"},
                    {"id": "permutations_combinations", "name": "Permutations and combinations"},
                    {"id": "probability", "name": "Probability"},
                    {"id": "discrete_rv", "name": "Discrete random variables"},
                    {"id": "normal_distribution", "name": "The normal distribution"},
                    {"id": "sampling", "name": "Sampling and estimation"},
                    {"id": "hypothesis_testing", "name": "Hypothesis testing"},
                ],
            },
        },
    }
}

# 文件名格式：9709_w24_qp_11.pdf
_FILENAME_RE = re.compile(
    r"(?i)^(?P<subject>\d{4})_(?P<season>[wms]\d{2})_(?P<kind>qp|ms)_(?P<comp>\d)(?P<variant>\d)\.pdf$"
)

def parse_filename(filename: str) -> Optional[Dict[str, str]]:
    """
    解析文件名，返回 subject/component 等信息
    """
    name = Path(filename).name
    m = _FILENAME_RE.match(name)
    if not m:
        return None
    d = m.groupdict()
    return {
        "subject": d["subject"],
        "component": d["comp"],
        "variant": d["variant"],
        "kind": d["kind"].lower(),
        "season": d["season"].lower(),
    }

def get_topics(subject: str, component: str) -> List[Dict[str, Any]]:
    """
    返回指定科目+卷别的 topics，保持字典里定义的顺序
    """
    subj = TOPIC_MAP.get(str(subject), {})
    comp = (subj.get("components") or {}).get(str(component), {})
    topics = comp.get("topics") or []
    return topics

def list_subjects() -> List[Dict[str, str]]:
    """
    返回所有科目列表
    """
    return [{"code": code, "name": block.get("name") or code}
            for code, block in TOPIC_MAP.items()]

def list_components(subject: str) -> List[Dict[str, str]]:
    """
    返回指定科目的所有卷别
    """
    comps = (TOPIC_MAP.get(str(subject), {}).get("components") or {})
    return [{"component": cno, "title": (cblk.get("title") or cno)}
            for cno, cblk in comps.items()]
