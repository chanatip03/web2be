# ระบบ Submission

## ภาพรวม

โมดูลนี้คือชั้น orchestration สำหรับ flow การส่งงานของ Web2BE ฝั่ง backend

หน้าที่ของมันคือรวมการส่งงานของนักศึกษาให้กลายเป็น workflow เดียวที่สามารถ:

- รับ source code ที่ส่งเข้ามา
- สร้าง workspace ของ submission ใต้ `data/submissions`
- map `project_type` ของ assignment ไปเป็น execution mode ที่ subsystem เดิมเข้าใจ
- เรียก deployment subsystem เดิม
- เรียก testcase subsystem เดิมใน mode ที่ต้องใช้
- เรียก security scan subsystem เดิม
- เปิด endpoint สำหรับ poll สถานะและดาวน์โหลด artifact

implementation ชุดนี้เป็น phase แรก จึงตั้งใจให้เป็นแบบ filesystem-first ก่อน โดยใช้ `manifest.json` ภายในแต่ละ submission เป็นแหล่งข้อมูลหลัก แทนการเพิ่ม SQL table ใหม่ทันที

## ขอบเขตของโมดูลนี้

โมดูลนี้รับผิดชอบเรื่องต่อไปนี้:

- รับคำขอส่งงานจากนักศึกษา
- ตรวจสอบสิทธิ์ว่าผู้ส่งเป็น student ของห้องเรียนใน assignment จริง
- สร้างโฟลเดอร์ submission ใต้ `data/submissions/<submission_id>/`
- เรียก background pipeline
- อัปเดตสถานะลง `manifest.json` ทีละ step
- เปิด API สำหรับดูสถานะ submission และดาวน์โหลด artifact

โมดูลนี้ไม่ได้เขียน logic deployment, testcase หรือ security scan ใหม่ แต่เป็นการเรียกใช้ subsystem เดิมผ่าน service layer

## โครงสร้างไฟล์ในโมดูล

- `controller.py`
  - FastAPI endpoint สำหรับสร้าง submission, ดูสถานะ, ดูรายการ artifact, ดาวน์โหลด artifact
- `dto.py`
  - request/response schema
- `service.py`
  - orchestration หลักและ background workflow
- `fs.py`
  - helper สำหรับสร้างโฟลเดอร์ submission, อ่านและเขียน manifest, copy artifact, ตรวจ path ให้ปลอดภัย
- `manifest.py`
  - โครงสร้างข้อมูลของ `manifest.json`
- `__init__.py`
  - export router

## API ที่เปิดใช้งาน

router ของโมดูลนี้มี prefix เป็น `/submission` และถูกรวมอยู่ใต้ `/api`

endpoint ที่เรียกจริงคือ:

- `POST /api/submission/{assignment_id}`
- `GET /api/submission/{submission_id}`
- `GET /api/submission/{submission_id}/artifacts`
- `GET /api/submission/{submission_id}/artifacts/{artifact_id}`

ทุก endpoint ใช้การยืนยันตัวตนแบบ cookie `access_token`

## รูปแบบ input ที่รองรับ

endpoint สำหรับสร้าง submission รับ source ได้ครั้งละแบบเดียวเท่านั้น:

- upload zip ผ่าน field `file`
- ส่ง URL ของ public repository ผ่าน field `repo_url`

ถ้าส่งมาทั้งคู่ หรือไม่ส่งเลย ระบบจะ reject

จุดสำคัญ:

- ตอน submit ยังไม่ได้มี field ให้เลือก mode เอง
- mode จะถูกตัดสินจาก assignment ที่อ้างถึงใน path เช่น `POST /api/submission/{assignment_id}`
- พูดอีกแบบคือ ผู้ใช้เลือก assignment และ assignment นั้นเป็นตัวกำหนดว่า submission นี้จะรันเป็น `frontend-only`, `backend-only` หรือ `fullstack`

field เพิ่มเติมที่ส่งได้:

- `env`

## การ map execution mode

ระบบนี้ไม่ได้สร้าง mode ใหม่ แต่ใช้การ map `assignment.project_type_id` ไปเป็น mode ที่ deployment subsystem เดิมใช้อยู่แล้ว

mapping ปัจจุบันคือ:

- `FE` -> `frontend-only`
- `BE` -> `backend-only`
- `Project` -> `fullstack`

ดังนั้น ถ้าอยากเปลี่ยน mode ที่ใช้กับการส่งงาน ตอนนี้ต้องเปลี่ยนที่ชนิดของ assignment หรือ project type ที่ assignment ผูกอยู่ ไม่ใช่ส่ง mode override เข้ามาใน request submit

service layer รองรับ alias เพิ่มเติมด้วย เช่น:

- `frontend`
- `backend`
- `fullstack`
- `fullstack-db`
- `fullstack+db`

## กติกาการทำงานในแต่ละ mode

### `frontend-only`

- deploy แบบ `frontend-only`
- รัน testcase กับ preview URL
- รัน cyber scan

### `backend-only`

- deploy แบบ `backend-only`
- รัน testcase กับ preview URL
- รัน cyber scan

### `fullstack`

- deploy แบบ `fullstack`
- รัน cyber scan
- ข้าม testcase ใน phase แรก

### plagiarism

- ยังไม่ถูกเรียกอัตโนมัติใน flow การส่งงานของนักศึกษา
- สถานะเริ่มต้นใน manifest คือ `not_requested`
- ตั้งใจให้เป็น flow แยกที่ครู trigger เองในภายหลัง

## โครงสร้างการเก็บข้อมูลของ submission

แต่ละ submission จะมี root หนึ่งชุด:

```text
data/submissions/<submission_id>/
├── original/
├── source/
├── artifacts/
│   ├── cyber/
│   ├── deployment/
│   ├── testcase/
│   └── plagiarism/
└── manifest.json
```

ความหมายของแต่ละส่วน:

- `original/`
  - เก็บไฟล์ zip ต้นฉบับ ถ้า input มาจากการ upload
- `source/`
  - เก็บ source code ที่ extract จาก zip หรือ clone มาจาก repo
- `artifacts/`
  - เก็บผลลัพธ์ที่ copy กลับมาจาก subsystem ต่าง ๆ
- `manifest.json`
  - แหล่งข้อมูลหลักของ submission ใน phase แรก

## โครงสร้าง manifest

`manifest.json` เป็น source of truth ของ flow นี้ใน phase แรก

ข้อมูลหลักที่เก็บมี:

- metadata ของ submission
- `assignment_id`
- `student_id`
- `execution_mode`
- `pipeline_status`
- สถานะราย step ใน `steps`
- สรุปผล deployment
- สรุปผล testcase
- สรุปผล cyber scan
- สถานะ plagiarism
- รายการ artifact และ route สำหรับดาวน์โหลด

field สำคัญในระดับบนสุด ได้แก่:

- `submission_id`
- `assignment_id`
- `execution_mode`
- `pipeline_status`
- `steps`
- `deployment`
- `testcase`
- `cyber`
- `plagiarism`
- `artifacts`

## ลำดับการทำงานของ pipeline

background pipeline ปัจจุบันเรียงลำดับแบบนี้:

1. `prepare`
2. `cyber`
3. `deployment`
4. `testcase` ถ้า mode นั้นต้องใช้
5. `plagiarism` คงไว้เป็น `not_requested`

หมายเหตุ:

- ถ้า cyber scan ล้มเหลว deployment ยังทำงานต่อ
- ถ้า testcase ล้มเหลว deployment ที่สำเร็จแล้วจะไม่ถูกล้าง
- ค่า `pipeline_status` ตอนจบจะเป็น:
  - `success` ถ้า step ที่เกี่ยวข้องสำเร็จหรือถูกข้ามโดยตั้งใจ
  - `partial_success` ถ้ามีทั้ง step ที่สำเร็จและล้มเหลว
  - `error` ถ้า step ที่เกี่ยวข้องล้มเหลวโดยไม่มีส่วนที่สำเร็จมาชดเชย

## Subsystem เดิมที่ถูก reuse

โมดูลนี้ reuse โค้ดเดิมของระบบแทนการเขียนซ้ำ

### ตรวจ assignment และสิทธิ์นักศึกษา

- `app.core.assignment.repository.get_assignment_by_id`
- `app.core.user.repository.get_student_by_user_id`
- `app.core.classroommember.repository.is_student_in_classroom`
- `app.utils.validator.get_current_user`

### Deployment subsystem

- `app.deployment.services.deployer.pipeline.run_deployment`
- `app.deployment.services.deployer.pipeline.project_store`
- `app.deployment.services.deployer.pipeline.deployment_store`
- `app.deployment.models.project.ProjectMetadata`
- `app.deployment.models.deployment.DeploymentStatus`

### Testcase subsystem

- `app.core.generatetestcase.services.runner.run_robot_tests_with_suite_content`

### Security scan subsystem

- `app.core.security_scan.fs.validate_submission`
- `app.core.security_scan.snyk_code.scan_source_code`
- `app.core.security_scan.normalizer.normalize_code_result`

## วิธีทดสอบผ่าน Postman

ส่วนนี้เป็น workflow ที่ใช้ยิง submission flow จริงผ่าน API ของระบบ โดยต้องสร้าง `assignment` ก่อนทุกครั้ง เพราะ endpoint ส่งงานอ้าง `assignment_id` โดยตรง

## สิ่งที่ต้องมีล่วงหน้า

- backend รันอยู่ เช่น `http://127.0.0.1:8000`
- Docker Desktop พร้อมใช้งาน และ `GET /health` ต้องได้ `docker_available: true`
- ถ้าจะให้ cyber scan ทำงาน ต้องมี `SNYK_TOKEN` และติดตั้ง `snyk` CLI ใน `PATH`
- ถ้าจะ submit แบบ `repo_url` ต้องมี `git` ใน `PATH`
- ถ้าจะทดสอบผ่าน ngrok ให้ใช้ base URL ของ ngrok และเพิ่ม header `ngrok-skip-browser-warning: true`

## สรุปลำดับจริง

1. login teacher
2. create classroom
3. login student
4. student join classroom ด้วย code
5. login teacher อีกรอบ
6. create assignment
7. login student อีกรอบ
8. submit repo หรือ zip เข้า assignment
9. poll status จน pipeline จบ
10. list artifacts และ download artifact ที่ต้องการ

## ตัวแปรที่แนะนำใน Postman Environment

```text
base_url = http://127.0.0.1:8000
teacher_email = teacher.e2e@example.com
teacher_password = Passw0rd!123
student_email = student.e2e@example.com
student_password = Passw0rd!123
classroom_id =
classroom_code =
assignment_id =
submission_id =
artifact_id =
```

## 1. Login Teacher

- Method: `POST`
- URL: `{{base_url}}/api/auth/login`
- Body: `raw` -> `JSON`

```json
{
  "email": "{{teacher_email}}",
  "password": "{{teacher_password}}"
}
```

หมายเหตุ:

- response จะคืน `access_token`
- backend จะ set cookie `access_token` ให้ด้วย
- ใน Postman ให้ดูที่ cookie jar ว่ามี cookie สำหรับ domain เดียวกับ `base_url`

## 2. Create Classroom

- Method: `POST`
- URL: `{{base_url}}/api/classroom/`
- Body: `raw` -> `JSON`

```json
{
  "name": "Submission E2E Classroom",
  "semester": "2/2026",
  "description": "Used for submission flow testing",
  "learningoutcomes": "Deploy and verify fullstack projects"
}
```

Test script ที่แนะนำ:

```javascript
const json = pm.response.json();
pm.collectionVariables.set("classroom_id", json.id);
pm.collectionVariables.set("classroom_code", json.code);
```

## 3. Login Student

- Method: `POST`
- URL: `{{base_url}}/api/auth/login`
- Body: `raw` -> `JSON`

```json
{
  "email": "{{student_email}}",
  "password": "{{student_password}}"
}
```

## 4. Join Classroom

- Method: `POST`
- URL: `{{base_url}}/api/classroommember/?code={{classroom_code}}`
- Body: none

หมายเหตุ:

- endpoint นี้รับ `code` เป็น query parameter
- request นี้ต้องใช้ cookie ของ student ไม่ใช่ teacher

## 5. Login Teacher Again

ทำซ้ำ request login ของ teacher เพื่อให้ cookie ปัจจุบันกลับมาเป็นของ teacher ก่อนสร้าง assignment

## 6. Create Assignment

- Method: `POST`
- URL: `{{base_url}}/api/assignment/`
- Body: `form-data`

required fields:

- `title` = `Thailand Tourist Fullstack`
- `description` = `Fullstack submission test`
- `start_date` = `2026-04-02T20:00:00+07:00`
- `due_date` = `2026-04-09T20:00:00+07:00`
- `is_group` = `false`
- `project_type_id` = `3`
- `language_id` = `2`
- `classroom_id` = `{{classroom_id}}`

หมายเหตุ:

- `project_type_id = 3` ต้อง map ไปชื่อ `Project` เพื่อให้ submission กลายเป็น `fullstack`
- `attachment` และ `testcase` เป็น optional

Test script ที่แนะนำ:

```javascript
const json = pm.response.json();
pm.collectionVariables.set("assignment_id", json.id);
```

## 7. Login Student Again

ทำซ้ำ request login ของ student เพื่อให้ cookie ปัจจุบันกลับมาเป็นของ student ก่อน submit

## 8. Submit From Repository

- Method: `POST`
- URL: `{{base_url}}/api/submission/{{assignment_id}}`
- Body: `form-data`

ตัวอย่างสำหรับ thailand-tourist-guide-web:

- `repo_url` = `https://github.com/oreongab/thailand-tourist-guide-web`
- `env` = `production`

ตัวอย่างสำหรับ GoSmooth-WebPro2:

- `repo_url` = `https://github.com/Akanoito89003/GoSmooth-WebPro2`
- `env` = `production`

ข้อสำคัญ:

- ส่ง `repo_url` หรือ `file` อย่างใดอย่างหนึ่งเท่านั้น
- request นี้ต้องใช้ cookie ของ student

Test script ที่แนะนำ:

```javascript
const json = pm.response.json();
if (json.submission_id) {
  pm.collectionVariables.set("submission_id", json.submission_id);
}
```

## 9. Poll Submission Status

- Method: `GET`
- URL: `{{base_url}}/api/submission/{{submission_id}}`

field สำคัญที่ควรดู:

- `pipeline_status`
- `steps.cyber.status`
- `steps.deployment.status`
- `steps.testcase.status`
- `deployment.preview_url`
- `artifacts`

การตีความผลสำหรับ `fullstack`:

- `cyber` ควรเป็น `success` หรือ `error`
- `deployment` ควรเป็น `success`
- `testcase` จะเป็น `skipped` โดย design ของ phase ปัจจุบัน
- `pipeline_status` มักเป็น `success` หรือ `partial_success`

## 10. List Artifacts

- Method: `GET`
- URL: `{{base_url}}/api/submission/{{submission_id}}/artifacts`

Test script ที่แนะนำ:

```javascript
const json = pm.response.json();
const firstCyber = (json.artifacts || []).find(a => a.category === 'cyber');
if (firstCyber) {
  pm.collectionVariables.set('artifact_id', firstCyber.artifact_id);
}
```

## 11. Download Artifact

- Method: `GET`
- URL: `{{base_url}}/api/submission/{{submission_id}}/artifacts/{{artifact_id}}`

ใน Postman ให้ใช้ `Send and Download` ถ้าต้องการบันทึกไฟล์

## 12. Submit From ZIP แทน Repo

ถ้าจะทดสอบแบบ zip ให้ใช้ request เดียวกับข้อ 8 แต่เปลี่ยน body เป็น:

- `file` = เลือก zip file
- `env` = `production`

และต้องไม่ส่ง `repo_url`

## เคสที่ยืนยันแล้วในระบบ

- `https://github.com/oreongab/thailand-tourist-guide-web`
- `https://github.com/Akanoito89003/GoSmooth-WebPro2`

ทั้งสองตัว deploy แบบ `fullstack` ผ่านได้ในระบบ deploy ปัจจุบันบน Windows host นี้

## หมายเหตุสำคัญเรื่อง cyber scan

- ถ้าใน `manifest.json` ไม่มี folder `artifacts/cyber/` แต่ `steps.cyber.status = error` แปลว่า cyber step ถูกเรียกแล้วแต่ล้มเหลวก่อนเขียน artifact
- ในกรณีของ submission เก่าที่เกิดก่อน fix ล่าสุดบน Windows อาจเจอ error จากการ decode output ของ `snyk` ทำให้ไม่ได้ `scan.json`
- submission เก่าจะไม่ย้อนกลับมา rerun cyber ให้อัตโนมัติ ต้อง submit ใหม่ถ้าต้องการ artifact ใหม่

## ผลการทดสอบที่ยืนยันแล้ว

โมดูลนี้ถูกทดสอบกับ public repository นี้แล้ว:

- `https://github.com/oreongab/thailand-tourist-guide-web`

ผลที่ยืนยันแล้วใน flow ปัจจุบัน:

- สร้าง submission ได้สำเร็จ
- fullstack deployment สำเร็จ
- preview ใช้งานผ่าน ngrok ได้
- ดาวน์โหลด deployment bundle ผ่าน ngrok ได้
- cyber scan สร้าง `scan.json` ได้หลังติดตั้ง Snyk CLI

## ข้อจำกัดปัจจุบัน

implementation นี้เป็น backend-first รุ่นแรก จึงมีข้อจำกัดที่ตั้งใจไว้ดังนี้:

- สถานะ submission ยังเก็บแบบ filesystem-first ไม่ใช่ SQL-first
- ยังไม่มีตาราง SQL สำหรับ submission โดยเฉพาะ
- plagiarism ยังไม่อยู่ใน auto-submit flow
- `fullstack` ยังข้าม testcase โดยตั้งใจ
- ยังไม่มี API สำหรับ list submission ตาม assignment หรือ student
- ความสอดคล้องของสถานะขึ้นอยู่กับการเขียน `manifest.json` สำเร็จครบแต่ละ step

## แนวทางต่อยอดที่แนะนำ

- mirror ข้อมูลสรุปจาก manifest ลง SQL เพื่อ query ได้แบบ LMS-native
- เพิ่ม teacher-triggered plagiarism flow
- เพิ่ม list endpoint เช่น submissions by assignment และ submissions by student
- เพิ่ม rerun capability โดยไม่จำเป็นต้องสร้าง workflow ใหม่ทุกครั้ง
