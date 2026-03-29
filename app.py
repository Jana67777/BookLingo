from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import requests
import os
import re

app = Flask(__name__)
app.config['SECRET_KEY'] = 'andersen_secret_key_12345'
# 允许上传文件大小限制为 16MB
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Vercel 部署环境适配：Vercel 的根目录是只读的，SQLite 需要写在 /tmp 目录下，或者使用 PostgreSQL
if os.environ.get('SQLALCHEMY_DATABASE_URI'):
    # 如果用户在 Vercel 配置了外部数据库（如 Postgres），优先使用
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('SQLALCHEMY_DATABASE_URI').replace("postgres://", "postgresql://", 1)
elif os.environ.get('VERCEL_ENV') or os.environ.get('VERCEL') or '/var/task' in os.path.abspath(__file__):
    # 注意：Vercel 是 Serverless 环境，/tmp 目录下的数据在实例销毁时会丢失。
    # 推荐后续替换为 Vercel Postgres 等云数据库
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////tmp/andersen.db'
else:
    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'andersen.db')
    
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- 数据库模型 (Task 3) ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    vocabs = db.relationship('Vocab', backref='user', lazy=True)

class Vocab(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    word = db.Column(db.String(100), nullable=False)
    translation = db.Column(db.String(200), nullable=False)
    context = db.Column(db.Text, nullable=True) # 出处句子
    source = db.Column(db.String(100), nullable=True) # 来源故事
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# 初始化数据库表
with app.app_context():
    db.create_all()

# --- 阅读器全局变量 (用于简单的内存缓存，在Serverless环境中不持久，仅作为示例缓存) ---
# 注意：在真实的 Vercel 部署中，如果需要支持多用户同时读不同的书，应将书籍内容或进度存入数据库。
# 考虑到纯展示和简化，这里暂用全局变量（每次请求可能丢失状态），但前端可以通过上传重置它。
GLOBAL_TEXT = ""
GLOBAL_PAGES = []
GLOBAL_BOOK_TITLE = "安徒生童话"
PAGE_SIZE = 2000

def paginate_text(text: str, page_size: int):
    if not text:
        return []
    pages = []
    i = 0
    n = len(text)
    while i < n:
        end = min(i + page_size, n)
        if end < n:
            window_start = max(i, end - 200)
            chunk = text[window_start:end]
            m = None
            for match in re.finditer(r"\s", chunk):
                m = match
            if m:
                safe_end = window_start + m.start()
                if safe_end <= i:
                    safe_end = end
            else:
                forward_end = min(n, end + 200)
                fchunk = text[end:forward_end]
                fm = re.search(r"\s", fchunk)
                if fm:
                    safe_end = end + fm.start()
                else:
                    safe_end = end
        else:
            safe_end = end
        pages.append(text[i:safe_end])
        i = safe_end
    return pages

# 初始化加载默认的童话
default_book_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Andersen's_fairy_tales.txt")
if os.path.exists(default_book_path):
    try:
        with open(default_book_path, "r", encoding="utf-8") as f:
            GLOBAL_TEXT = f.read()
            GLOBAL_PAGES = paginate_text(GLOBAL_TEXT, PAGE_SIZE)
    except Exception as e:
        print("Failed to load default book:", e)

# --- 路由 (Task 1: Auth) ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        if user:
            flash('用户名已存在', 'error')
            return redirect(url_for('register'))
            
        new_user = User(username=username, password_hash=generate_password_hash(password, method='pbkdf2:sha256'))
        db.session.add(new_user)
        db.session.commit()
        
        flash('注册成功，请登录', 'success')
        return redirect(url_for('login'))
        
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash('登录成功', 'success')
            return redirect(url_for('index'))
        else:
            flash('用户名或密码错误', 'error')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

# --- 核心业务路由 (Task 2 & Task 3) ---

@app.route('/api/translate', methods=['POST'])
@login_required
def translate_word():
    data = request.get_json()
    word = data.get('word', '').strip()
    
    if not word:
        return jsonify({'error': 'No word provided'}), 400
        
    # 调用免费翻译API (MyMemory)
    url = "https://api.mymemory.translated.net/get"
    try:
        response = requests.get(url, params={'q': word, 'langpair': 'en|zh-CN'})
        if response.status_code == 200:
            result = response.json()
            translation = result['responseData']['translatedText']
            return jsonify({'word': word, 'translation': translation})
        return jsonify({'error': 'Translation API failed'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/vocab/add', methods=['POST'])
@login_required
def add_vocab():
    data = request.get_json()
    word = data.get('word')
    translation = data.get('translation')
    context = data.get('context')
    source = data.get('source', '安徒生童话')
    
    if not word or not translation:
        return jsonify({'error': 'Missing word or translation'}), 400
        
    # 检查是否已在生词本中
    existing = Vocab.query.filter_by(user_id=current_user.id, word=word).first()
    if existing:
        return jsonify({'message': '已在生词本中'})
        
    new_vocab = Vocab(
        word=word,
        translation=translation,
        context=context,
        source=source,
        user_id=current_user.id
    )
    db.session.add(new_vocab)
    db.session.commit()
    return jsonify({'message': '成功加入生词本', 'id': new_vocab.id})

@app.route('/vocab')
@login_required
def vocab_book():
    vocabs = Vocab.query.filter_by(user_id=current_user.id).order_by(Vocab.id.desc()).all()
    return render_template('vocab.html', vocabs=vocabs)

# --- 阅读器相关路由 (移植自旧版本) ---
@app.route('/api/page')
def api_page():
    total = max(1, len(GLOBAL_PAGES))
    try:
        page = int(request.args.get("page", "1"))
    except Exception:
        page = 1
    if page < 1:
        page = 1
    if page > total:
        page = total
    content = GLOBAL_PAGES[page-1] if GLOBAL_PAGES else ""
    return jsonify({
        "page": page, 
        "total_pages": total, 
        "page_size": PAGE_SIZE, 
        "content": content, 
        "book_title": GLOBAL_BOOK_TITLE
    })

@app.route('/api/upload', methods=['POST'])
def upload_file():
    global GLOBAL_TEXT, GLOBAL_PAGES, GLOBAL_BOOK_TITLE
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    try:
        content = file.read()
        text = None
        for enc in ['utf-8', 'gbk', 'gb18030', 'latin-1']:
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        
        if text is None:
            return jsonify({"error": "Unsupported encoding"}), 400
            
        GLOBAL_TEXT = text
        GLOBAL_PAGES = paginate_text(GLOBAL_TEXT, PAGE_SIZE)
        GLOBAL_BOOK_TITLE = os.path.splitext(file.filename)[0]
        
        return jsonify({"success": True, "title": GLOBAL_BOOK_TITLE, "total_pages": len(GLOBAL_PAGES)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    # host='0.0.0.0' allows it to be accessed on the local network
    app.run(debug=True, host='0.0.0.0', port=5000)
