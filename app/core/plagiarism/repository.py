import os

BASE_PATH = os.getcwd()

WORK_DIR = os.path.abspath(os.path.join(BASE_PATH, "app" ,"data", "submissions"))

RESULT_DIR = os.path.abspath(os.path.join(BASE_PATH, "app" ,"data", "results"))

def ensure_result_dir():
    os.makedirs(RESULT_DIR, exist_ok=True)

import subprocess
import os
from .repository import ensure_result_dir, WORK_DIR, RESULT_DIR
import zipfile
import json

JAVA = r"C:\Program Files\Java\jdk-25\bin\java.exe"
JPLAG_JAR = os.path.abspath(r"app/core/plagiarism/jplag/jplag.jar")

def run_jplag_service():
    ensure_result_dir()
    result_name = "report"

    cmd = [
        JAVA,
        "--enable-native-access=ALL-UNNAMED",
        "-jar", JPLAG_JAR,
        "--mode", "RUN", 
        "-l", "javascript",
        "-r", result_name,
        "--overwrite",
        "-m", "0.0",          #ตรวจสอบทุกระดับความเหมือนแม้จะ 0%
        "-t", "1",            #บังคับตรวจแม้โค้ดจะสั้นมาก (1 token)
        WORK_DIR
    ]

    try:
        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            cwd=RESULT_DIR
        )

        expected_file = os.path.join(RESULT_DIR, f"{result_name}.jplag")
        
        if process.returncode != 0:
            full_error = f"STDOUT: {process.stdout}\nSTDERR: {process.stderr}"
            raise RuntimeError(f"JPlag Process Failed (Code {process.returncode})\nDetails: {full_error}")

        if not os.path.exists(expected_file):
            raise RuntimeError(f"JPlag finished but result file not found at {expected_file}")

        return expected_file

    except Exception as e:
        raise RuntimeError(f"Service Execution Error: {str(e)}")
    
def extract_avg_comparisons(jplag_file: str):
    extract_dir = jplag_file.replace(".jplag", "_extracted")
    comparisons_dir = os.path.join(extract_dir, "comparisons")

    with zipfile.ZipFile(jplag_file, 'r') as zip_ref:
        zip_ref.extractall(extract_dir)

    if not os.path.exists(comparisons_dir):
        return []

    similarity_map = {}
    students = set()

    for filename in os.listdir(comparisons_dir):
        if not filename.endswith(".json"):
            continue

        with open(os.path.join(comparisons_dir, filename), encoding="utf-8") as f:
            comp = json.load(f)

        s1 = comp.get("firstSubmissionId")
        s2 = comp.get("secondSubmissionId")
        avg = comp.get("similarities", {}).get("AVG", 0)

        if not s1 or not s2:
            continue

        students.update([s1, s2])

        key = frozenset([s1, s2])
        similarity_map[key] = round(avg * 100, 2)

    students = sorted(students)
    result = []

    for s1 in students:
        for s2 in students:
            if s1 == s2:
                continue

            avg = similarity_map.get(frozenset([s1, s2]), 0)

            result.append({
                "student1": s1,
                "student2": s2,
                "avg_similarity": avg
            })

    return result