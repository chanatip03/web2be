# Deployment Module Guide (`app/deployment`)

เอกสารนี้อธิบายการใช้งานระบบ Deploy ของ `web2be` ที่ถูกย้ายมาจาก backend เดิม ครอบคลุม:
- การเตรียมสภาพแวดล้อม
- สิ่งที่ต้องตั้งค่า (ENV + Docker)
- วิธีทดสอบ End-to-End
- วิธีใช้งานผ่าน Postman

## 1. โมดูลนี้ทำอะไร

`app/deployment` รับผิดชอบงานหลักต่อไปนี้:
- รับโปรเจกต์จาก GitHub / ZIP / Folder Upload
- วิเคราะห์โปรเจกต์
- สร้าง/ปรับ Docker config
- Build + Run container (single service หรือ docker compose)
- จัดการสถานะ deployment (start/stop/rebuild/logs/health)
- ให้ URL สำหรับ preview (`/preview/{project_id}`)

Router ถูก mount ผ่าน `app.main` โดยไม่มี prefix เพิ่มเติม ดังนั้น path ที่เรียกใช้คือ path จริงตามด้านล่าง

## 2. Endpoint สำคัญ (ที่ใช้บ่อย)

### Health/System
- `GET /health`
- `GET /api/system/status`

### Unified Deploy
- `POST /api/deploy` (GitHub)
- `POST /api/deploy/upload` (ZIP)
- `POST /api/deploy/upload-folder` (folder files)
- `GET /api/deploy/{project_id}/status`

### Project Management
- `POST /api/projects/upload`
- `POST /api/projects/upload-folder`
- `POST /api/projects/import-github`
- `GET /api/projects`
- `GET /api/projects/{project_id}`
- `POST /api/projects/{project_id}/re-analyze`
- `GET /api/projects/{project_id}/analysis`
- `DELETE /api/projects/{project_id}`

### Deployment Control
- `POST /api/projects/{project_id}/deploy`
- `GET /api/projects/{project_id}/deployments`
- `GET /api/deployments/{deployment_id}/status`
- `POST /api/deployments/{deployment_id}/start`
- `POST /api/deployments/{deployment_id}/stop`
- `POST /api/deployments/{deployment_id}/rebuild`
- `DELETE /api/deployments/{deployment_id}`
- `GET /api/deployments/{deployment_id}/logs`
- `GET /api/deployments/{deployment_id}/build-logs`
- `GET /api/deployments/{deployment_id}/health`

### Preview
- `GET /preview/{project_id}`
- `GET /preview/{project_id}/swagger`
- `GET /preview/{project_id}/swagger.json`
- `GET /preview/{project_id}/{service}/{path:path}`

## 3. เตรียมสภาพแวดล้อม

## 3.1 Python + dependencies

จาก root `merge/web2be`:

```bash
pip install -r requirement.txt
```

## 3.2 Docker prerequisites (ต้องมี)

ต้องติดตั้งและใช้งานได้:
- Docker Engine
- Docker Compose v2 (`docker compose`)
- User ที่รัน API ต้องสั่ง Docker ได้

เช็กเร็ว:

```bash
docker version
docker compose version
docker ps
```

ถ้า `GET /health` ได้ `docker_available: false` แปลว่า API คุยกับ Docker daemon ไม่ได้

## 3.3 Environment ที่ต้องมีสำหรับรัน `app.main`

เนื่องจาก `web2be` มีโมดูลอื่นในระบบที่บังคับ env ตอน import จำเป็นต้องตั้งอย่างน้อย:
- `DATABASE_URL`
- `SUBMISSIONS_DIR`
- `RESULTS_DIR`

ตัวอย่างขั้นต่ำ (local):

```env
DATABASE_URL=sqlite:///./local.db
SUBMISSIONS_DIR=./data/submissions
RESULTS_DIR=./data/results
```

## 3.4 Environment ที่เกี่ยวกับ deployment

ค่าเหล่านี้มี default ใน `app/deployment/core/config.py` และปรับเพิ่มได้ผ่าน `.env`:
- `LITAI_API_KEY`
- `LITAI_MODEL` (default `lightning-ai/DeepSeek-V3.1`)
- `LITAI_API_URL`
- `LLM_ADVISORY_ONLY` (default `false`)
- `DATA_DIR` (default `./data`)
- `PROJECTS_DIR` (default `./data/projects`)
- `DEPLOYMENTS_DIR` (default `./data/deployments`)
- `BASE_PREVIEW_PORT` (default `3000`)
- `DOCKER_NETWORK` (default `deployer-shared`)
- `DOCKER_BUILD_TIMEOUT_SECONDS` (default `1200`)
- `PUBLIC_BASE_URL` (เช่น ngrok/public URL ของ API ตัวนี้)

หมายเหตุ:
- โหมดปกติของระบบนี้ต้องใช้ `LITAI_API_KEY`; ถ้าไม่ตั้งค่า จะ fail ตอนเรียก LLM
- ถ้าต้องการรันแบบไม่ใช้ LLM จริง ให้ตั้ง `LLM_ADVISORY_ONLY=true` เพื่อให้ระบบใช้ deterministic fallback แทนบางส่วน
- ถ้าจะเปิดใช้งานผ่าน ngrok หรือ reverse proxy ควรตั้ง `PUBLIC_BASE_URL` ให้เป็น base URL ภายนอก เพื่อให้ preview/linking ตรงกับ URL ที่ผู้ใช้เข้าจริง
- โฟลเดอร์ `data` จะถูกใช้เก็บ metadata และ artifact
- ระบบจะเรียก LLM แบบเข้าคิวทีละงาน และจะถือคิวไว้ตลอดช่วง retry/backoff ของงานนั้น เพื่อไม่ให้ deployment หลายตัว interleave request ใส่ provider พร้อมกัน
- ถ้าเจอ `429 Too Many Requests` จาก Lightning AI deployment จะช้าลงหรือ fail ได้ เพราะระบบมี retry อัตโนมัติแต่ยังขึ้นกับ quota ของ provider


วิธีรัน
```
cd /web2be
pip install -r requirement.txt
export DATABASE_URL='sqlite:///./runtime_server.db'
/home/zeus/miniconda3/bin/conda run -p /home/zeus/miniconda3 --no-capture-output python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```


## 4. วิธีทดสอบการใช้งาน (แนะนำ)

## 4.1 Smoke test ระบบ

1. เรียก `GET /health` ต้องได้ response และ `docker_available` เป็น `true`
2. เรียก `GET /api/system/status` เพื่อดูภาพรวม projects/deployments

## 4.2 E2E Deploy (GitHub)

1. `POST /api/deploy`
2. เก็บค่า `id` (ใช้เป็น `project_id` และ `deployment_id`)
3. Poll `GET /api/deploy/{id}/status` จน deployment เป็น `success` หรือ `error`
4. เปิด `GET /preview/{id}`
5. เช็ก logs ผ่าน `GET /api/deployments/{id}/logs`

หมายเหตุจากการทดสอบจริง:
- `frontend-only` เปิดผ่าน `GET /preview/{id}`
- `backend-only` มักเช็กได้ผ่าน `GET /preview/{id}/swagger` หรือ endpoint health ของ backend ที่ถูก proxy ออกมา
- `fullstack` มักมี frontend ที่ `GET /preview/{id}` และ backend ที่ `GET /preview/{id}/backend/...`

ตัวอย่าง body:

```json
{
  "repo_url": "https://github.com/<owner>/<repo>.git",
  "deploy_mode": "auto",
  "name": "demo-project",
  "subdir": ""
}
```

ค่า `deploy_mode` ที่ใช้ได้:
- `frontend-only`
- `backend-only`
- `fullstack`
- `auto`

## 4.3 E2E Deploy (ZIP)

1. `POST /api/deploy/upload` แบบ `form-data`
2. field ที่ต้องส่ง:
   - `file` (ZIP)
   - `name`
   - `deploy_mode`
3. Poll status ตามข้อ 4.2

## 4.4 คำสั่งควบคุม deployment

หลัง deploy แล้วสามารถทดสอบต่อ:
- Start: `POST /api/deployments/{deployment_id}/start`
- Stop: `POST /api/deployments/{deployment_id}/stop`
- Rebuild: `POST /api/deployments/{deployment_id}/rebuild`
- Health: `GET /api/deployments/{deployment_id}/health`

## 5. Postman Workflow (ใช้งานจริง)

ตั้งค่า Environment ใน Postman:
- `baseUrl` = `http://127.0.0.1:8000` หรือ public URL เช่น ngrok (`https://<your-ngrok>.ngrok-free.app`)
- `projectId` = ว่างก่อน
- `deploymentId` = ว่างก่อน

ลำดับ request ที่ควรมีใน collection:

1. `Health`
- Method: `GET`
- URL: `{{baseUrl}}/health`

2. `Deploy from GitHub`
- Method: `POST`
- URL: `{{baseUrl}}/api/deploy`
- Body: raw JSON ตามตัวอย่างด้านบน
- Tests script (optional): เก็บ id

```javascript
const data = pm.response.json();
pm.environment.set("projectId", data.id);
pm.environment.set("deploymentId", data.id);
```

3. `Check Deploy Status`
- Method: `GET`
- URL: `{{baseUrl}}/api/deploy/{{projectId}}/status`

4. `Get Deployment Logs`
- Method: `GET`
- URL: `{{baseUrl}}/api/deployments/{{deploymentId}}/logs`

5. `Open Preview`
- Method: `GET`
- URL: `{{baseUrl}}/preview/{{projectId}}`

6. `Deployment Health`
- Method: `GET`
- URL: `{{baseUrl}}/api/deployments/{{deploymentId}}/health`

ถ้าเป็น public usage ผ่าน ngrok และตั้ง `PUBLIC_BASE_URL` ไว้แล้ว preview ที่เปิดใน browser ควรใช้รูปแบบ:

```text
{{baseUrl}}/preview/{{projectId}}
{{baseUrl}}/preview/{{projectId}}/swagger
{{baseUrl}}/preview/{{projectId}}/backend/<path>
```

## 6. สิ่งที่ควรใส่เพิ่มในการทดสอบ (แนะนำทีม)

เพื่อให้การทดสอบมีคุณภาพ ควรครอบคลุม:
- กรณี Docker ใช้งานไม่ได้ (`docker_available=false`)
- กรณี repo clone ไม่ได้ / zip เสีย
- กรณี deploy สำเร็จแต่ endpoint app ไม่พร้อม
- ทดสอบ fullstack route ผ่าน `/preview/{project_id}/backend/...`
- ทดสอบ start/stop/rebuild แล้วสถานะต้องเปลี่ยนถูกต้อง

## 7. Troubleshooting

- Error: `Cannot connect to Docker daemon`
  - เช็ก `docker ps`
  - เช็กสิทธิ์ user ที่รัน API

- Error: `DATABASE_URL is not set`
  - ตั้ง `DATABASE_URL` ก่อนรัน `app.main`

- Error: preview เปิดไม่ขึ้น
  - เช็ก `GET /api/deployments/{deployment_id}/status`
  - เช็ก `build-logs` และ `logs`
  - ถ้าเป็น `fullstack` ให้ลอง path ของ backend ผ่าน `/preview/{project_id}/backend/...`

- Error: `LITAI_API_KEY is not set`
  - ตั้ง `LITAI_API_KEY` ใน `.env`
  - หรือสลับเป็น `LLM_ADVISORY_ONLY=true` ถ้าต้องการใช้ deterministic fallback

- Error: `429 Too Many Requests`
  - เป็น quota/rate-limit ของ Lightning AI
  - ลดจำนวน deploy พร้อมกัน หรือรอ retry/backoff ให้ครบก่อนสรุปว่า fail

- Error: รัน compose ไม่ได้
  - เช็กว่าเครื่องมี `docker compose` (v2) ไม่ใช่ `docker-compose` เก่า
