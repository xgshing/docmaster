# DocMaster

基于 `Electron + Vue3 + TypeScript + Django` 的桌面文档管理系统。

## 当前交付内容

- Django 后端已接入 `MySQL` 配置、`COS` 存储链路、`OnlyOffice` 在线编辑配置与回调、`JWT` 签名支持
- 文档能力已覆盖共享空间、全局重名处理、回收站、归档、PDF 导出、强制解锁、日志清理命令
- 桌面端已提供登录、共享树、个人文档库同步、共享上传、导出、直接打印、回收站、管理员面板
- 部署目录已补充 `requirements.txt`、`systemd`、`nginx`、初始化脚本

## 目录

- `backend/` Django 服务端
- `desktop/` Electron + Vue 桌面端
- `deploy/` 生产部署脚本与示例配置
- `dev_documentation.md` 项目需求文档

## 关键环境变量

```env
DJANGO_SECRET_KEY=
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=doc.yuntuxia.top,127.0.0.1,localhost
CORS_ALLOWED_ORIGINS=https://doc.yuntuxia.top,https://office.yuntuxia.top

MYSQL_DATABASE=docmaster
MYSQL_USER=docmaster_user
MYSQL_PASSWORD=
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306

DOCMASTER_STORAGE_ROOT=/opt/docmaster/runtime
DOCMASTER_ONLYOFFICE_URL=https://office.yuntuxia.top
DOCMASTER_ONLYOFFICE_JWT_SECRET=
DOCMASTER_ONLYOFFICE_VERIFY_SSL=1

DOCMASTER_COS_BUCKET=
DOCMASTER_COS_REGION=
TENCENT_SECRET_ID=
TENCENT_SECRET_KEY=
DOCMASTER_DEFAULT_ADMIN_PASSWORD=Docmstr1
```

## 后端启动

```powershell
cd backend
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_docmaster
python manage.py runserver
```

## 桌面端启动

```powershell
cd desktop
npm install
npm run build
```

开发模式可继续使用：

```powershell
cd desktop
npm run dev
```

## 管理命令

```powershell
python manage.py seed_docmaster
python manage.py cleanup_docmaster
```

## 部署提示

- 建议为 OnlyOffice 启用 `DOCMASTER_ONLYOFFICE_JWT_SECRET`
- 共享文件、回收站文件和导出文件统一走 `COS`，服务端保留本地缓存
- `deploy/systemd/` 和 `deploy/nginx/` 提供生产示例，可按你的服务器路径调整
