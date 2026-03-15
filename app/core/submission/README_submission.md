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
- `app.core.student.repository.get_student_by_user_id`
- `app.core.classroommember.repository.is_student_in_classroom`
- `app.utils.validator.get_current_user`

### Deployment subsystem

- `app.deployment.services.deployer.pipeline.run_deployment`
- `app.deployment.services.deployer.pipeline.project_store`
- `app.deployment.services.deployer.pipeline.deployment_store`
- `app.deployment.models.project.ProjectMetadata`
- `app.deployment.models.deployment.DeploymentStatus`

### Testcase subsystem

- `app.testcase.services.runner.run_robot_tests_with_suite_content`

### Security scan subsystem

- `app.core.security_scan.fs.validate_submission`
- `app.core.security_scan.snyk_code.scan_source_code`
- `app.core.security_scan.normalizer.normalize_code_result`

## วิธีทดสอบผ่าน Postman

ส่วนนี้ตั้งใจเขียนสำหรับการทดสอบด้วย Postman โดยตรง แทนการใช้ `curl`

### 1. เตรียม server

ต้องมีเงื่อนไขพื้นฐานดังนี้:

- PostgreSQL ใช้งานได้ตาม `DATABASE_URL`
- backend รันอยู่ เช่น `http://127.0.0.1:8000`
- ถ้าจะทดสอบผ่าน ngrok ให้ `PUBLIC_BASE_URL` ชี้ไปที่ URL ของ tunnel ปัจจุบัน
- ถ้าจะให้ cyber scan ทำงานจริง ต้องมี `SNYK_TOKEN` และต้องติดตั้ง `snyk` CLI ไว้ใน `PATH`

### 2. Login เพื่อรับ `access_token`

submission endpoint ใช้ cookie auth ดังนั้นใน Postman ต้อง login ก่อน

request สำหรับ login ของระบบนี้คือ:

- Method: `POST`
- URL: `http://127.0.0.1:8000/api/auth/login`
- Headers:
  - `Content-Type: application/json`
- Body:
  - เลือก `raw`
  - เลือกชนิด `JSON`

ตัวอย่าง body:

```json
{
  "email": "submission-student@example.com",
  "password": "your-password"
}
```

เมื่อ login สำเร็จ backend จะ set cookie `access_token` กลับมาให้ และ Postman ควรเก็บ cookie นี้ไว้ใน domain ของ backend โดยอัตโนมัติ

สิ่งที่ควรตรวจหลัง login:

- response status สำเร็จ
- Postman มี cookie `access_token`
- cookie ถูกผูกกับ domain ที่จะใช้ยิง request ต่อไปจริง

ถ้า Postman ไม่เก็บ cookie ให้อัตโนมัติ ให้เปิด cookie manager แล้วเพิ่ม `access_token` เองให้ตรงกับ domain ที่จะยิง

### 3. สร้าง request สำหรับส่งงานจาก repo

ตัวอย่างสำหรับ `POST /api/submission/{assignment_id}`

หมายเหตุ:

- `assignment_id` ไม่ได้ใช้แค่ระบุว่าส่งงานชิ้นไหน แต่ยังเป็นตัวกำหนด execution mode ของ submission นี้ด้วย
- ตัวอย่างเช่น ถ้า assignment นั้นผูกกับ `Project` ระบบจะ map เป็น `fullstack` ให้อัตโนมัติ

ตั้งค่าใน Postman แบบนี้:

- Method: `POST`
- URL: `http://127.0.0.1:8000/api/submission/1`
- Auth: ไม่ต้องใส่ Bearer ถ้าใช้ cookie อยู่แล้ว
- Headers:
  - `ngrok-skip-browser-warning: true` เฉพาะกรณีเรียกผ่าน ngrok free tier
- Body:
  - เลือก `form-data`
  - เพิ่ม key `repo_url` ชนิด Text
  - value เช่น `https://github.com/oreongab/thailand-tourist-guide-web`

เมื่อสำเร็จ response จะเป็นลักษณะ accepted หรือ queued และจะได้ `submission_id` กลับมา

### 4. สร้าง request สำหรับส่งงานจาก zip

ตั้งค่าใน Postman แบบนี้:

- Method: `POST`
- URL: `http://127.0.0.1:8000/api/submission/1`
- Headers:
  - `ngrok-skip-browser-warning: true` ถ้าเรียกผ่าน ngrok
- Body:
  - เลือก `form-data`
  - เพิ่ม key `file`
  - เปลี่ยนชนิดเป็น File
  - เลือกไฟล์ zip ของโปรเจกต์

ข้อสำคัญ:

- ส่ง `file` หรือ `repo_url` อย่างใดอย่างหนึ่งเท่านั้น
- ถ้าจะส่ง `env` ก็ใส่เพิ่มเป็น Text field ใน `form-data`

### 5. Poll สถานะของ submission

หลังจากได้ `submission_id` แล้ว ให้สร้าง request ใหม่:

- Method: `GET`
- URL: `http://127.0.0.1:8000/api/submission/<submission_id>`

field สำคัญที่ควรดูใน response:

- `pipeline_status`
- `steps`
- `deployment`
- `testcase`
- `cyber`
- `artifacts`

ถ้าเป็น `fullstack` ใน phase นี้ ให้คาดหวังว่า:

- deployment ทำงาน
- cyber scan ทำงาน
- testcase ถูก mark เป็น skipped

### 6. ดูรายการ artifact

สร้าง request:

- Method: `GET`
- URL: `http://127.0.0.1:8000/api/submission/<submission_id>/artifacts`

response จะบอกว่า submission นี้มี artifact อะไรบ้าง เช่น scan result, deployment bundle, log หรือไฟล์ผลลัพธ์อื่น ๆ

### 7. ดาวน์โหลด artifact

เมื่อได้ `artifact_id` จากขั้นก่อนหน้า ให้สร้าง request:

- Method: `GET`
- URL: `http://127.0.0.1:8000/api/submission/<submission_id>/artifacts/<artifact_id>`

ใน Postman ให้กด `Send and Download` ถ้าต้องการบันทึกไฟล์ลงเครื่องโดยตรง

### 8. ทดสอบผ่าน ngrok

ถ้าจะทดสอบจาก URL ภายนอก เช่น:

- `https://fa89-34-63-19-90.ngrok-free.app`

ให้เปลี่ยน URL ของทุก request เป็น domain ของ ngrok และเพิ่ม header นี้ใน Postman:

- `ngrok-skip-browser-warning: true`

กรณีที่ Postman ใช้ cookie ผ่าน ngrok ให้ตรวจว่าคุกกี้ถูกผูกกับ domain ของ ngrok ไม่ใช่ domain ของ localhost

## ตัวอย่าง flow แนะนำใน Postman

ถ้าจะจัดเป็น collection สำหรับทดสอบ แนะนำลำดับนี้:

1. Login
2. Submit from Repo หรือ Submit from Zip
3. Get Submission Status
4. List Submission Artifacts
5. Download Selected Artifact

ตัวแปรที่ควรเก็บใน Postman environment หรือ collection variables:

- `base_url`
- `assignment_id`
- `submission_id`

ตัวอย่างค่า:

```text
base_url = http://127.0.0.1:8000
assignment_id = 1
```

ตัวอย่าง test script ใน Postman เพื่อเก็บ `submission_id` จาก response ของการ submit:

```javascript
const json = pm.response.json();
if (json.submission_id) {
  pm.collectionVariables.set("submission_id", json.submission_id);
}
```

จากนั้น request ถัดไปสามารถอ้าง URL แบบนี้ได้:

```text
{{base_url}}/api/submission/{{submission_id}}
```

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
