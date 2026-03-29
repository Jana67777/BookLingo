# 安徒生童话在线阅读器 (Web版)

这是一个支持多端适配（手机、平板、电脑）的在线童话阅读器，集成了免费翻译API与生词本功能。

## 功能列表 (Features)
- **多端适配**：使用 Tailwind CSS 进行响应式设计，完美适配手机、平板、电脑。
- **注册/登录系统**：用户认证和个人数据隔离。
- **划词翻译**：在阅读界面鼠标选中（或手机长按）英文单词或短语，即可弹出中文翻译。
- **生词本**：一键将不认识的单词、释义及原句上下文加入个人生词本。

## 部署到公网 (Deployment)

推荐使用 **Vercel** 进行快速免费部署。

### 部署到 Vercel (当前配置已支持)
由于 Vercel 是 Serverless（无服务器）环境，代码目录是只读的，默认使用 SQLite 时数据会被写入到临时的 `/tmp` 目录。**请注意：在 `/tmp` 中的数据会在实例销毁时丢失，且多实例间数据不共享。**

**推荐做法：使用外部云数据库（如 Vercel Postgres 或 Supabase）**
1. 注册并登录 [Vercel](https://vercel.com/)。
2. 将 `web_app` 文件夹上传到你的 GitHub 仓库。
3. 在 Vercel 面板中导入该 GitHub 仓库进行部署。
4. 如果你要使用持久化数据库，请在 Vercel 中添加 Postgres 附加组件，或使用 Supabase 获得一个 PostgreSQL 连接字符串，然后将其添加为 Vercel 的环境变量 `SQLALCHEMY_DATABASE_URI`。
5. （可选）如果你只是为了体验，目前代码已适配了 Vercel 的临时目录，可以直接部署，但注册的用户和生词本数据可能会丢失。

### 方法 2：部署到 Render (适合使用 SQLite)
1. 将 `web_app` 文件夹内的代码推送到你的 GitHub 仓库。
2. 登录 [Render](https://render.com/)，选择 **New Web Service**。
3. 连接你的 GitHub 仓库，填写以下配置：
   - **Environment**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn wsgi:app`
4. 点击部署，完成后 Render 会提供一个公网可访问的 HTTPS 域名（例如 `your-app.onrender.com`）。

### 方法 2：部署到 PythonAnywhere
1. 注册 [PythonAnywhere](https://www.pythonanywhere.com/) 账号。
2. 将代码打包上传，或者在 Console 中 `git clone` 你的仓库。
3. 在 Web 选项卡中创建一个新的 Web App，选择 Flask 框架，Python 3.10+。
4. 修改 WSGI 配置文件，将其指向你的 `app.py` 所在的路径，并导入 `app`。
5. 在 Console 中运行 `pip install -r requirements.txt`。
6. 点击 Reload，即可通过 `<你的用户名>.pythonanywhere.com` 访问。

### 方法 3：本地/云服务器自建运行
如果在有公网IP的服务器（如阿里云、腾讯云）上运行：

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 使用 Gunicorn 运行服务 (暴露在 5000 端口)
gunicorn -w 4 -b 0.0.0.0:5000 wsgi:app
```
然后配置 Nginx 反向代理至 5000 端口并绑定域名。
