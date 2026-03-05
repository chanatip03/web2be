# Testcase Module Guide (`app/testcase`)

เอกสารนี้อธิบายการใช้งานระบบ Testcase (สร้าง test จาก prompt + run Robot Framework) ครอบคลุม:
- สิ่งที่ระบบต้องมี
- วิธีทดสอบ API แบบครบ flow
- วิธียิงผ่าน Postman
- สิ่งที่ควรทดสอบเพิ่ม

## 1. โมดูลนี้ทำอะไร

`app/testcase` ให้ความสามารถหลัก:
- สร้าง test definition จาก prompt
- เก็บ/แก้ suite content (`.robot`)
- สั่งรัน test กับโปรเจกต์ที่ deploy แล้ว
- ดูประวัติและผลการรัน
- มี legacy endpoint สำหรับยิง API endpoint รายตัว

Router ถูก mount ตรง ๆ ใน `app.main` โดยใช้ prefix `/api/tests`

## 2. Endpoint สำคัญ

## 2.1 Definition lifecycle
- `POST /api/tests/generate`
- `POST /api/tests/definitions/generate` (alias)
- `GET /api/tests/definitions/{test_id}`
- `GET /api/tests/definitions/{test_id}/suite`
- `PUT /api/tests/definitions/{test_id}/suite`

## 2.2 Run lifecycle
- `POST /api/tests/definitions/{test_id}/run`
- `GET /api/tests/definitions/{test_id}/runs`
- `GET /api/tests/runs/{run_id}`

## 2.3 Legacy API endpoint testing
- `GET /api/tests/api/{project_id}/endpoints`
- `POST /api/tests/api/{project_id}/endpoints/{endpoint_id}/test`

## 3. สภาพแวดล้อมที่ต้องมี

## 3.1 Python packages

ต้องติดตั้งจาก `requirement.txt` โดยเฉพาะ:
- `robotframework`
- `robotframework-requests`
- (ถ้าต้องใช้ browser) `robotframework-seleniumlibrary`

คำสั่ง:

```bash
pip install -r requirement.txt
```

## 3.2 Dependency กับ deployment

`testcase` พึ่งข้อมูลจาก `app/deployment` โดยตรง:
- project metadata (project_store)
- deployment metadata (deployment_store)
- preview URL ของโปรเจกต์

ดังนั้นก่อน run test ควรมี project/deployment ที่พร้อมใช้งานแล้ว

## 3.3 Environment พื้นฐานของ web2be

สำหรับรัน `app.main` ต้องมีขั้นต่ำ:
- `DATABASE_URL`
- `SUBMISSIONS_DIR`
- `RESULTS_DIR`

ตัวอย่าง:

```env
DATABASE_URL=sqlite:///./local.db
SUBMISSIONS_DIR=./data/submissions
RESULTS_DIR=./data/results
```

## 4. วิธีทดสอบการใช้งาน (E2E)

## 4.1 เตรียมโปรเจกต์ให้มี preview ก่อน

1. Deploy โปรเจกต์ด้วย endpoint ใน `app/deployment`
2. ให้ได้ `project_id`
3. เช็กว่า preview เปิดได้ เช่น `GET /preview/{project_id}`

## 4.2 สร้าง test definition

- Method: `POST`
- URL: `/api/tests/definitions/generate`
- Body:

```json
{
  "prompt": "ทดสอบ login flow ว่าตอบ 200 และ token ถูกส่งกลับ"
}
```

Response จะได้:
- `test_id`
- `suite_content`
- `suite_file`

## 4.3 แก้ suite เพิ่มเอง (optional)

- Method: `PUT`
- URL: `/api/tests/definitions/{test_id}/suite`
- Body:

```json
{
  "content": "*** Settings ***\nLibrary    RequestsLibrary\n\n*** Test Cases ***\nHealth check\n    Create Session    api    http://localhost:8000\n    ${resp}=    GET On Session    api    /health\n    Status Should Be    200\n"
}
```

## 4.4 รัน test definition

- Method: `POST`
- URL: `/api/tests/definitions/{test_id}/run`
- Body:

```json
{
  "project_id": "<project_id>",
  "preview_url": "http://127.0.0.1:8000/preview/<project_id>"
}
```

หมายเหตุ:
- `preview_url` ใส่ก็ได้ไม่ใส่ก็ได้
- ถ้าไม่ใส่ ระบบจะพยายามหาให้จาก deployment_store

## 4.5 ตรวจผลการรัน

- รายการ run ของ definition:
  - `GET /api/tests/definitions/{test_id}/runs`
- ดู run เดียว:
  - `GET /api/tests/runs/{run_id}`

## 5. Postman Workflow

ตั้งค่า Environment:
- `baseUrl` = `http://127.0.0.1:8000`
- `projectId` = project ที่ deploy แล้ว
- `testId` = ว่าง
- `runId` = ว่าง

ลำดับ request ที่แนะนำ:

1. `Generate Test Definition`
- `POST {{baseUrl}}/api/tests/definitions/generate`
- raw JSON:

```json
{
  "prompt": "สร้าง API test สำหรับ health endpoint"
}
```

- Tests script (เก็บ testId):

```javascript
const data = pm.response.json();
pm.environment.set("testId", data.test_id);
```

2. `Get Definition`
- `GET {{baseUrl}}/api/tests/definitions/{{testId}}`

3. `Run Definition`
- `POST {{baseUrl}}/api/tests/definitions/{{testId}}/run`
- raw JSON:

```json
{
  "project_id": "{{projectId}}"
}
```

- Tests script (เก็บ runId):

```javascript
const data = pm.response.json();
pm.environment.set("runId", data.run_id);
```

4. `Get Run Result`
- `GET {{baseUrl}}/api/tests/runs/{{runId}}`

5. `List Runs`
- `GET {{baseUrl}}/api/tests/definitions/{{testId}}/runs`

## 6. Legacy endpoint testing (ผ่าน Postman)

1. ดึง endpoint list:
- `GET {{baseUrl}}/api/tests/api/{{projectId}}/endpoints`

2. เลือก `endpoint_id` (เช่น `ep-1`) แล้วยิง test:
- `POST {{baseUrl}}/api/tests/api/{{projectId}}/endpoints/ep-1/test`
- raw JSON ตัวอย่าง:

```json
{
  "resolvedPath": "/api/users/1",
  "query": {},
  "headers": {
    "Content-Type": "application/json"
  },
  "body": {}
}
```

## 7. สิ่งที่ควรใส่ในการทดสอบให้ครบ

ควรครอบคลุมอย่างน้อย:
- Generate definition จาก prompt หลายรูปแบบ
- อัปเดต suite แล้ว version ต้องเพิ่ม
- Run โดยไม่ส่ง `preview_url` (ให้ระบบ resolve เอง)
- Run โดยส่ง `preview_url` ตรง ๆ
- กรณี project ไม่มี preview แล้วควรได้ error ที่อ่านง่าย
- ตรวจผล run ว่ามี pass/fail/log ครบ

## 8. Troubleshooting

- Error: `Project not found`
  - เช็ก `project_id` ว่ามีจริง

- Error: `Project has no active preview URL`
  - ต้อง deploy ให้สำเร็จก่อน
  - เช็ก deployment status ในโมดูล deployment

- Robot run fail เพราะ endpoint ไม่ตรง
  - แก้ suite ด้วย `PUT /api/tests/definitions/{test_id}/suite`
  - ใส่ URL/path ให้ตรงกับ preview จริง
