import os
import subprocess
import zipfile
import json
import logging

logger = logging.getLogger(__name__)

BASE_PATH = os.getcwd()

WORK_DIR = os.path.abspath(os.path.join(BASE_PATH, "app" ,"data", "submissions"))
RESULT_DIR = os.path.abspath(os.path.join(BASE_PATH, "app" ,"data", "results"))

JAVA = "java"
JPLAG_JAR = os.path.abspath(r"app/core/plagiarism/jplag/jplag.jar")

def run_jplag_service(assignment_id: int = 0, language: str = "javascript", work_dir: str = WORK_DIR, result_dir: str = RESULT_DIR):
    os.makedirs(result_dir, exist_ok=True)
    result_name = f"report_{assignment_id}" if assignment_id else "report"

    # Map generic language names to jplag supported values
    lang_map = {
        "python": "python3",
        "js": "javascript",
        "ts": "typescript",
        "java": "java",
        "c": "c",
        "cpp": "cpp",
        "c++": "cpp",
        "go": "go", # Depending on jplag version, go might be supported
        "frontend": "text",
        "html": "text",
    }
    jplag_lang = lang_map.get(language.lower(), language.lower())

    cmd = [
        JAVA,
        "--enable-native-access=ALL-UNNAMED",
        "-jar", JPLAG_JAR,
        "--mode", "RUN", 
        "-l", jplag_lang,
        "-r", result_name,
        "--overwrite",
        "-m", "0.0",          #ตรวจสอบทุกระดับความเหมือนแม้จะ 0%
        "-t", "1",            #บังคับตรวจแม้โค้ดจะสั้นมาก (1 token)
    ]
    
    # If the text parser is used (for HTML/frontend), we must explicitly tell JPlag to scan web extensions
    # NOTE: JPlag suffixes should NOT have dots (e.g. 'html' instead of '.html')
    if jplag_lang == "text":
        cmd.extend(["-p", "html,css,js,jsx,ts,tsx"])

    cmd.append(work_dir)
    msg = f"DEBUG: Running JPlag command: {' '.join(cmd)}"
    logger.info(msg)
    print(msg, flush=True)

    # List files to see if they are actually there
    try:
        subdirs = [d for d in os.listdir(work_dir) if os.path.isdir(os.path.join(work_dir, d))]
        logger.info(f"DEBUG: Found {len(subdirs)} submissions in {work_dir}")
        for sd in subdirs:
            files = os.listdir(os.path.join(work_dir, sd))
            logger.info(f"DEBUG: Submission '{sd}' contains: {files}")
    except Exception as e:
        logger.error(f"DEBUG: Failed to list files: {e}")

    try:
        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            cwd=result_dir
        )
        
        logger.info(f"DEBUG: JPlag Return Code: {process.returncode}")
        logger.info(f"DEBUG: JPlag STDOUT: {process.stdout}")
        logger.info(f"DEBUG: JPlag STDERR: {process.stderr}")
        print(f"DEBUG: JPlag STDOUT: {process.stdout}", flush=True)

        expected_file = os.path.join(result_dir, f"{result_name}.jplag")
        
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